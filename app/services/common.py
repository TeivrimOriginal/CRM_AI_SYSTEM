"""Общие помощники сервисов: доступ, версии, история, настройки, DNC."""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.enums import ActivityType, DealStage, Role
from app.models import Activity, AppSetting, Company, Deal, User
from app.timeutils import utcnow

DNC_MESSAGE = "Компания или контакт в списке «Не связываться» — действие заблокировано"

# Настройки, которые руководитель может менять через интерфейс
SETTING_KEYS = {
    "SALE_CONFIRMATION_CRITERION",
    "BELARUS_CHECK_REQUIRED_BEFORE",
    "BELARUS_CHECKER_ROLE",
}
SALE_CRITERIA = {"manual", "contract_signed", "prepayment", "custom"}
BELARUS_CHECKPOINTS = {"proposal_sent", "handoff", "none"}
BELARUS_ROLES = {"manager", "supervisor"}


def normalize_domain(url: Optional[str]) -> Optional[str]:
    """Нормализованный домен для поиска дублей: без схемы, www и пути."""
    if not url:
        return None
    value = url.strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "http://" + value
    try:
        host = urlparse(value).netloc.lower()
    except Exception:
        return None
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def is_supervisor(user: User) -> bool:
    return getattr(user, "role", None) == Role.SUPERVISOR


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row is not None else default


def set_setting(db: Session, key: str, value: str) -> AppSetting:
    if key not in SETTING_KEYS:
        raise HTTPException(status_code=422, detail={"key": "Неизвестная настройка"})
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value or "")
        db.add(row)
    else:
        row.value = value or ""
    db.commit()
    return row


def validate_setting(key: str, value: str) -> str:
    value = (value or "").strip()
    if key == "SALE_CONFIRMATION_CRITERION" and value and value not in SALE_CRITERIA:
        raise HTTPException(status_code=422, detail={"value": "Допустимо: manual, contract_signed, prepayment, custom или пусто"})
    if key == "BELARUS_CHECK_REQUIRED_BEFORE" and value not in BELARUS_CHECKPOINTS:
        raise HTTPException(status_code=422, detail={"value": "Допустимо: proposal_sent, handoff, none"})
    if key == "BELARUS_CHECKER_ROLE" and value not in BELARUS_ROLES:
        raise HTTPException(status_code=422, detail={"value": "Допустимо: manager, supervisor"})
    return value


def company_visibility_filter(user: User):
    """Условие доступа менеджера к компании: своя компания ИЛИ назначенная сделка."""
    if is_supervisor(user):
        return None
    own_deal = select(Deal.company_id).where(Deal.owner_id == user.id)
    return or_(Company.owner_id == user.id, Company.id.in_(own_deal))


def get_company_or_404(db: Session, company_id: int, actor: User, *, include_archived: bool = False) -> Company:
    company = db.get(Company, company_id)
    if company is None or (company.archived_at is not None and not include_archived):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
    if not is_supervisor(actor):
        if company.owner_id != actor.id:
            has_deal = db.scalar(
                select(Deal.id).where(Deal.company_id == company.id, Deal.owner_id == actor.id).limit(1)
            )
            if not has_deal:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к компании")
    return company


def get_deal_or_404(db: Session, deal_id: int, actor: User, *, include_archived: bool = False) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None or (deal.archived_at is not None and not include_archived):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if not is_supervisor(actor) and deal.owner_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к сделке")
    return deal


def is_blocked(company: Company, contact=None) -> bool:
    return bool(company.do_not_contact) or bool(contact is not None and contact.do_not_contact)


def ensure_not_blocked(company: Company, contact=None, *, action: str = "связи") -> None:
    if is_blocked(company, contact):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"do_not_contact": DNC_MESSAGE, "action": action},
        )


def ensure_version(entity, expected: Optional[int]) -> None:
    """409 при конкурентном изменении: клиент получает свежую версию записи."""
    if expected is None:
        return
    current = int(getattr(entity, "version", 1) or 1)
    if int(expected) != current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "version_conflict",
                "message": "Запись изменена другим пользователем. Обновите страницу и повторите действие.",
                "current_version": current,
                "your_version": int(expected),
            },
        )


def bump_version(entity) -> None:
    entity.version = int(getattr(entity, "version", 1) or 1) + 1


def touch(entity) -> None:
    entity.updated_at = utcnow()


def log_activity(
    db: Session,
    *,
    actor: Optional[User] = None,
    company_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    activity_type: ActivityType,
    notes: Optional[str] = None,
) -> Activity:
    activity = Activity(
        company_id=company_id,
        deal_id=deal_id,
        contact_id=contact_id,
        actor_id=getattr(actor, "id", None),
        activity_type=activity_type,
        notes=notes,
        occurred_at=utcnow(),
    )
    db.add(activity)
    return activity


def paginate(stmt, db: Session, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


def normalize_name(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def stage_value(stage) -> str:
    return getattr(stage, "value", stage)


def is_active_stage(stage) -> bool:
    return stage_value(stage) not in (DealStage.LOST.value, DealStage.SALE_CONFIRMED.value)


def clean_currency(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    code = value.strip().upper()
    if not code:
        return None
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise HTTPException(status_code=422, detail={"currency": "Код валюты: 3 латинские буквы, например KZT"})
    return code


def ensure_user(db: Session, user_id: int, *, field: str = "owner_id") -> User:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=422, detail={field: "Пользователь не найден или неактивен"})
    return user


def parse_ids(values: Optional[Iterable[int]]) -> list[int]:
    return [int(v) for v in (values or [])]
