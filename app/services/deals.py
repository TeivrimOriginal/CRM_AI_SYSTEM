"""Сделки, воронка, КП, задачи, передача заказа и подтверждение продажи."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.enums import (
    ACTIVE_STAGES, ActivityType, DealStage, ImportKind, MarketCheckStatus,
    ProposalState, TaskActionType, TaskState,
)
from app.models import (
    Activity, City, Company, Contact, Country, Deal, Handoff, Journal, Niche,
    Proposal, Service, Task, User,
)
from app.schemas_companies import (
    DealCreate, DealUpdate, HandoffRequest, NoteCreate, TransitionRequest,
)
from app.services.common import (
    bump_version,
    clean_currency,
    ensure_not_blocked,
    ensure_user,
    ensure_version,
    get_deal_or_404,
    get_setting,
    is_supervisor,
    log_activity,
    stage_value,
    touch,
)
from app.timeutils import parse_datetime, to_naive_utc, utcnow

# Разрешённые явные переходы. Отправка КП, передача заказа и подтверждение
# продажи имеют отдельные операции и здесь намеренно запрещены.
TRANSITIONS: dict[DealStage, set[DealStage]] = {
    DealStage.FOUND: {DealStage.VERIFIED, DealStage.LOST, DealStage.DEFERRED},
    DealStage.VERIFIED: {DealStage.DM_FOUND, DealStage.LOST, DealStage.DEFERRED},
    DealStage.DM_FOUND: {DealStage.NEGOTIATION, DealStage.LOST, DealStage.DEFERRED},
    DealStage.PROPOSAL_SENT: {DealStage.NEGOTIATION, DealStage.LOST, DealStage.DEFERRED},
    DealStage.NEGOTIATION: {DealStage.TERMS_AGREED, DealStage.LOST, DealStage.DEFERRED},
    DealStage.TERMS_AGREED: {DealStage.LOST, DealStage.DEFERRED},
    DealStage.HANDED_OVER: {DealStage.LOST},
    DealStage.SALE_CONFIRMED: set(),
    DealStage.LOST: set(),
    DealStage.DEFERRED: set(),
}

TERMINAL_STAGES = {DealStage.SALE_CONFIRMED, DealStage.LOST}
COMMUNICATION_TASKS = {
    TaskActionType.CALL, TaskActionType.MESSAGE, TaskActionType.SEND_PROPOSAL,
    TaskActionType.CLARIFY_TERMS, TaskActionType.HANDOFF,
}


# ===== Сделки =====
def create_deal(db: Session, payload: DealCreate, actor: User) -> Deal:
    company = db.get(Company, payload.company_id)
    if company is None or company.archived_at is not None:
        raise HTTPException(status_code=422, detail={"company_id": "Компания не найдена"})
    if not is_supervisor(actor) and company.owner_id != actor.id:
        raise HTTPException(status_code=403, detail="Создавать сделки можно только по своим компаниям")

    owner_id = company.owner_id
    if is_supervisor(actor) and payload.owner_id:
        owner_id = payload.owner_id
    ensure_user(db, owner_id)

    service = db.get(Service, payload.service_id)
    if service is None or service.archived_at is not None:
        raise HTTPException(status_code=422, detail={"service_id": "Услуга не найдена"})
    if payload.contact_id:
        contact = db.get(Contact, payload.contact_id)
        if contact is None or contact.company_id != company.id:
            raise HTTPException(status_code=422, detail={"contact_id": "Контакт не относится к компании"})

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail={"title": "Укажите название сделки"})
    amount = payload.amount
    currency = clean_currency(payload.currency)
    if amount is not None and amount < 0:
        raise HTTPException(status_code=422, detail={"amount": "Сумма не может быть отрицательной"})

    country = db.get(Country, company.country_id)
    deal = Deal(
        company_id=company.id,
        contact_id=payload.contact_id,
        owner_id=owner_id,
        title=title,
        service_id=payload.service_id,
        customer_need=payload.customer_need,
        amount=amount,
        currency=currency,
        stage=DealStage.FOUND,
        market_check_status=(MarketCheckStatus.PENDING if country and country.market_check_required else None),
        version=1,
    )
    db.add(deal)
    db.flush()
    log_activity(
        db, actor=actor, company_id=company.id, deal_id=deal.id,
        activity_type=ActivityType.STAGE_CHANGE, notes="Сделка создана",
    )
    db.commit()
    db.refresh(deal)
    return deal


def update_deal(db: Session, deal: Deal, payload: DealUpdate, actor: User) -> Deal:
    ensure_version(deal, payload.version)
    data = payload.model_dump(exclude_unset=True)
    data.pop("version", None)
    if "contact_id" in data and data["contact_id"]:
        contact = db.get(Contact, data["contact_id"])
        if contact is None or contact.company_id != deal.company_id:
            raise HTTPException(status_code=422, detail={"contact_id": "Контакт не относится к компании"})
    if "service_id" in data and data["service_id"]:
        service = db.get(Service, data["service_id"])
        if service is None or service.archived_at is not None:
            raise HTTPException(status_code=422, detail={"service_id": "Услуга не найдена"})
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
        if not data["title"]:
            raise HTTPException(status_code=422, detail={"title": "Укажите название сделки"})
    if "currency" in data:
        data["currency"] = clean_currency(data["currency"])
    for key, value in data.items():
        setattr(deal, key, value)
    touch(deal)
    bump_version(deal)
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.NOTE, notes="Сделка изменена",
    )
    db.commit()
    db.refresh(deal)
    return deal


def list_deals(
    db: Session,
    actor: User,
    country_id: Optional[int] = None,
    city_id: Optional[int] = None,
    niche_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    stage: Optional[str] = None,
    status_filter: str = "all",
    include_archived: bool = False,
    q: Optional[str] = None,
    limit: int = 500,
) -> list[Deal]:
    stmt = select(Deal)
    if not include_archived:
        stmt = stmt.where(Deal.archived_at.is_(None))
    if not is_supervisor(actor):
        stmt = stmt.where(Deal.owner_id == actor.id)
    elif owner_id:
        stmt = stmt.where(Deal.owner_id == owner_id)
    if stage:
        stmt = stmt.where(Deal.stage == stage)
    if status_filter == "active":
        stmt = stmt.where(Deal.stage.in_([s.value for s in ACTIVE_STAGES]))
    elif status_filter == "closed":
        stmt = stmt.where(Deal.stage.in_([DealStage.SALE_CONFIRMED.value, DealStage.LOST.value]))
    if country_id or niche_id or city_id or q:
        stmt = stmt.join(Company, Company.id == Deal.company_id)
        if country_id:
            stmt = stmt.where(Company.country_id == country_id)
        if city_id:
            stmt = stmt.where(Company.city_id == city_id)
        if niche_id:
            stmt = stmt.where(Company.niche_id == niche_id)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Company.name.ilike(like), Deal.title.ilike(like)))
    return list(db.scalars(stmt.order_by(Deal.created_at.desc()).limit(limit)).all())


def next_open_task(db: Session, deal_id: int) -> Optional[Task]:
    return db.scalar(
        select(Task).where(Task.deal_id == deal_id, Task.state == TaskState.OPEN)
        .order_by(Task.due_at).limit(1)
    )


def allowed_transitions(deal: Deal) -> list[str]:
    current = DealStage(stage_value(deal.stage))
    if current == DealStage.DEFERRED and deal.previous_working_stage:
        return [stage_value(deal.previous_working_stage), DealStage.LOST.value]
    return [s.value for s in TRANSITIONS.get(current, set())]


def _conflict(stage: str, message: str, allowed: list[str]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "transition_conflict", "stage": stage, "message": message, "allowed": allowed},
    )


def assert_belarus_gate(db: Session, deal: Deal, checkpoint: str) -> None:
    country = db.get(Country, deal.company.country_id) if deal.company else None
    if country is None or not country.market_check_required:
        return
    when = get_setting(db, "BELARUS_CHECK_REQUIRED_BEFORE", "proposal_sent")
    if when == "none":
        return
    order = {"proposal_sent": 0, "handoff": 1}
    if order.get(when, 0) <= order.get(checkpoint, 0) and deal.market_check_status != MarketCheckStatus.PASSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "market_check": "Для сделки по Беларуси требуется проверка рынка",
                "status": stage_value(deal.market_check_status) or MarketCheckStatus.PENDING.value,
            },
        )


def _require_open_task(db: Session, deal: Deal, message: str) -> None:
    if next_open_task(db, deal.id) is None:
        raise HTTPException(status_code=422, detail={"task": message})


def transition_deal(db: Session, deal: Deal, payload: TransitionRequest, actor: User) -> Deal:
    ensure_version(deal, payload.version)
    try:
        new_stage = DealStage(payload.stage)
    except ValueError:
        raise HTTPException(status_code=422, detail={"stage": "Неизвестная стадия"})

    old_stage = DealStage(stage_value(deal.stage))
    allowed = allowed_transitions(deal)
    if new_stage == DealStage.PROPOSAL_SENT:
        raise _conflict(new_stage.value, "Отправка КП фиксируется отдельной операцией по версии КП", allowed)
    if new_stage == DealStage.HANDED_OVER:
        raise _conflict(new_stage.value, "Передача заказа оформляется отдельной операцией", allowed)
    if new_stage == DealStage.SALE_CONFIRMED:
        raise _conflict(new_stage.value, "Продажа подтверждается отдельной операцией", allowed)
    if new_stage.value not in allowed:
        raise _conflict(new_stage.value, "Недопустимый переход из текущей стадии", allowed)

    if new_stage == DealStage.VERIFIED:
        source_url = (payload.source_url or "").strip()
        result = (payload.verification_result or payload.notes or "").strip()
        missing = {}
        if not source_url:
            missing["source_url"] = "Укажите источник проверки"
        if not result:
            missing["verification_result"] = "Укажите результат проверки"
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        deal.company.source_url = source_url
        if deal.company.verified_at is None:
            deal.company.verified_at = utcnow()
        activity_note = f"Проверено. Источник: {source_url}. Результат: {result}"

    elif new_stage == DealStage.DM_FOUND:
        if not payload.contact_id:
            raise HTTPException(status_code=422, detail={"contact_id": "Выберите ЛПР"})
        contact = db.get(Contact, payload.contact_id)
        if contact is None or contact.company_id != deal.company_id:
            raise HTTPException(status_code=422, detail={"contact_id": "Контакт не относится к компании"})
        if not contact.is_decision_maker:
            raise HTTPException(status_code=422, detail={"contact_id": "Контакт не отмечен как ЛПР"})
        deal.contact_id = contact.id
        if deal.dm_found_at is None:
            deal.dm_found_at = utcnow()
        activity_note = f"ЛПР найден: {contact.name or contact.position or contact.id}"

    elif new_stage == DealStage.NEGOTIATION:
        result = (payload.notes or "").strip()
        if not result:
            raise HTTPException(status_code=422, detail={"notes": "Укажите ответ клиента или результат разговора"})
        _require_open_task(db, deal, "Для переговоров нужен следующий шаг (открытая задача)")
        if deal.negotiated_at is None:
            deal.negotiated_at = utcnow()
        activity_note = f"Переговоры: {result}"

    elif new_stage == DealStage.TERMS_AGREED:
        missing = {}
        if not (payload.agreed_scope or "").strip():
            missing["agreed_scope"] = "Укажите объём работ"
        if payload.amount is None:
            missing["amount"] = "Укажите сумму"
        if not payload.currency:
            missing["currency"] = "Укажите валюту"
        if not (payload.agreed_deadline_or_note or "").strip():
            missing["agreed_deadline_or_note"] = "Укажите срок или отметку о согласовании"
        if not (payload.agreement_reference or "").strip():
            missing["agreement_reference"] = "Укажите ссылку на подтверждение клиента"
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        deal.agreed_scope = payload.agreed_scope.strip()
        deal.amount = payload.amount
        deal.currency = clean_currency(payload.currency)
        deal.agreed_deadline_or_note = payload.agreed_deadline_or_note.strip()
        deal.agreement_reference = payload.agreement_reference.strip()
        activity_note = f"Условия согласованы: {deal.agreed_scope}, {deal.amount} {deal.currency}"

    elif new_stage == DealStage.DEFERRED:
        defer_until = to_naive_utc(payload.defer_until)
        if defer_until is None:
            raise HTTPException(status_code=422, detail={"defer_until": "Укажите дату возврата"})
        if defer_until <= utcnow():
            raise HTTPException(status_code=422, detail={"defer_until": "Дата возврата должна быть в будущем"})
        _require_open_task(db, deal, "Для откладывания нужна задача на дату возврата")
        if old_stage != DealStage.DEFERRED:
            deal.previous_working_stage = old_stage
        deal.defer_until = defer_until
        activity_note = f"Отложено до {defer_until.isoformat()}"

    elif new_stage == DealStage.LOST:
        reason = (payload.loss_reason or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail={"loss_reason": "Укажите причину отказа"})
        deal.loss_reason = reason
        if deal.lost_at is None:
            deal.lost_at = utcnow()
        activity_note = f"Отказ: {reason}"

    elif old_stage == DealStage.DEFERRED:
        # Возобновление: возвращаемся на рабочую стадию, сохранённую ранее
        deal.defer_until = None
        activity_note = f"Возобновлено после откладывания: {new_stage.value}"

    else:
        activity_note = f"{old_stage.value} -> {new_stage.value}"

    deal.stage = new_stage
    touch(deal)
    bump_version(deal)
    notes = activity_note + (f" | {payload.notes}" if payload.notes and new_stage != DealStage.NEGOTIATION else "")
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        contact_id=deal.contact_id, activity_type=ActivityType.STAGE_CHANGE, notes=notes,
    )
    db.commit()
    db.refresh(deal)
    return deal


# ===== КП =====
def create_proposal(db: Session, deal: Deal, payload, actor: User) -> Proposal:
    if deal.stage in (DealStage.LOST, DealStage.SALE_CONFIRMED):
        raise HTTPException(status_code=409, detail="По закрытой сделке нельзя создать КП")
    last_version = db.scalar(
        select(Proposal.version).where(Proposal.deal_id == deal.id)
        .order_by(Proposal.version.desc()).limit(1)
    )
    proposal = Proposal(
        deal_id=deal.id,
        version=(last_version or 0) + 1,
        link=(payload.link or "").strip() or None,
        state=(ProposalState.READY if payload.ready else ProposalState.DRAFT),
    )
    db.add(proposal)
    db.flush()
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.NOTE, notes=f"Создана версия КП v{proposal.version}",
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def send_proposal(db: Session, proposal: Proposal, payload, actor: User) -> Proposal:
    deal = db.get(Deal, proposal.deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    if proposal.state == ProposalState.SENT:
        raise HTTPException(status_code=409, detail="Эта версия КП уже отправлена")

    contact = db.get(Contact, payload.sent_contact_id)
    if contact is None or contact.company_id != deal.company_id:
        raise HTTPException(status_code=422, detail={"sent_contact_id": "Контакт не относится к компании"})
    ensure_not_blocked(deal.company, contact, action="отправки КП")
    if deal.stage in (DealStage.FOUND, DealStage.VERIFIED):
        raise _conflict(
            deal.stage, "Сначала зафиксируйте ЛПР: отправка возможна со стадии «ЛПР найден»",
            [DealStage.DM_FOUND.value],
        )
    if deal.stage in (DealStage.LOST, DealStage.SALE_CONFIRMED):
        raise HTTPException(status_code=409, detail="По закрытой сделке нельзя отправить КП")
    assert_belarus_gate(db, deal, "proposal_sent")

    link = (payload.link or "").strip()
    if not link:
        raise HTTPException(status_code=422, detail={"link": "Укажите ссылку на КП"})
    channel = (payload.sent_channel or "").strip()
    if not channel:
        raise HTTPException(status_code=422, detail={"sent_channel": "Укажите канал отправки"})

    proposal.link = link
    proposal.state = ProposalState.SENT
    proposal.sent_at = utcnow()
    proposal.sent_by = actor.id
    proposal.sent_contact_id = contact.id
    proposal.sent_channel = channel

    if deal.stage in (DealStage.DM_FOUND,):
        deal.stage = DealStage.PROPOSAL_SENT
    if deal.contact_id is None:
        deal.contact_id = contact.id
    touch(deal)
    bump_version(deal)
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id, contact_id=contact.id,
        activity_type=ActivityType.PROPOSAL_SENT,
        notes=f"КП v{proposal.version} отправлено через {channel}: {link}",
    )
    db.commit()
    db.refresh(proposal)
    return proposal


# ===== Задачи =====
def _task_access(task: Task, actor: User) -> None:
    if not is_supervisor(actor) and task.assignee_id != actor.id:
        raise HTTPException(status_code=403, detail="Нет доступа к задаче")


def create_task(db: Session, payload, actor: User) -> Task:
    deal = get_deal_or_404(db, payload.deal_id, actor)
    if deal.stage in (DealStage.LOST, DealStage.SALE_CONFIRMED):
        raise HTTPException(status_code=409, detail="По закрытой сделке нельзя создать задачу")
    action_type = payload.action_type
    valid_types = {t.value for t in TaskActionType}
    if action_type not in valid_types:
        raise HTTPException(status_code=422, detail={"action_type": "Неизвестный тип действия"})
    if action_type in {t.value for t in COMMUNICATION_TASKS}:
        contact = db.get(Contact, deal.contact_id) if deal.contact_id else None
        ensure_not_blocked(deal.company, contact, action="новой задачи связи")

    assignee_id = actor.id
    if payload.assignee_id and payload.assignee_id != actor.id:
        if not is_supervisor(actor):
            raise HTTPException(status_code=403, detail="Назначать задачу другому сотруднику может руководитель")
        assignee_id = payload.assignee_id
    ensure_user(db, assignee_id, field="assignee_id")

    due_at = to_naive_utc(payload.due_at)
    if due_at is None:
        raise HTTPException(status_code=422, detail={"due_at": "Укажите срок"})
    summary = payload.summary.strip()
    if not summary:
        raise HTTPException(status_code=422, detail={"summary": "Укажите, что сделать"})

    task = Task(
        deal_id=deal.id, assignee_id=assignee_id, action_type=action_type,
        summary=summary, due_at=due_at, state=TaskState.OPEN,
    )
    db.add(task)
    db.flush()
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.NOTE,
        notes=f"Назначена задача: {summary} (до {due_at.isoformat()} UTC)",
    )
    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, task: Task, actor: User) -> Task:
    _task_access(task, actor)
    if task.state == TaskState.DONE:
        return task
    if task.state == TaskState.CANCELLED:
        raise HTTPException(status_code=409, detail="Отменённую задачу нельзя выполнить")
    task.state = TaskState.DONE
    task.completed_at = utcnow()
    deal = db.get(Deal, task.deal_id)
    log_activity(
        db, actor=actor, company_id=deal.company_id if deal else None, deal_id=task.deal_id,
        activity_type=ActivityType.NOTE, notes=f"Задача выполнена: {task.summary}",
    )
    db.commit()
    db.refresh(task)
    return task


def cancel_task(db: Session, task: Task, actor: User) -> Task:
    _task_access(task, actor)
    if task.state == TaskState.DONE:
        raise HTTPException(status_code=409, detail="Выполненную задачу нельзя отменить")
    task.state = TaskState.CANCELLED
    db.commit()
    db.refresh(task)
    return task


def reschedule_task(db: Session, task: Task, due_at: datetime, actor: User) -> Task:
    _task_access(task, actor)
    if task.state != TaskState.OPEN:
        raise HTTPException(status_code=409, detail="Перенести можно только открытую задачу")
    new_due = to_naive_utc(due_at)
    if new_due is None:
        raise HTTPException(status_code=422, detail={"due_at": "Укажите новый срок"})
    task.due_at = new_due
    deal = db.get(Deal, task.deal_id)
    log_activity(
        db, actor=actor, company_id=deal.company_id if deal else None, deal_id=task.deal_id,
        activity_type=ActivityType.NOTE, notes=f"Задача перенесена на {new_due.isoformat()} UTC",
    )
    db.commit()
    db.refresh(task)
    return task


def list_tasks_for_user(db: Session, user: User) -> list[Task]:
    return list(db.scalars(
        select(Task).where(Task.assignee_id == user.id, Task.state == TaskState.OPEN)
        .order_by(Task.due_at)
    ).all())


def list_deal_tasks(db: Session, deal_id: int) -> list[Task]:
    return list(db.scalars(
        select(Task).where(Task.deal_id == deal_id).order_by(Task.due_at.desc())
    ).all())


# ===== Передача заказа =====
def create_handoff(db: Session, deal: Deal, payload: HandoffRequest, actor: User) -> Handoff:
    ensure_version(deal, payload.version)
    existing = db.scalar(select(Handoff).where(Handoff.deal_id == deal.id).limit(1))
    if existing is not None:
        return existing  # повторный запрос не создаёт вторую передачу

    if DealStage(stage_value(deal.stage)) != DealStage.TERMS_AGREED:
        raise HTTPException(
            status_code=409,
            detail="Передача заказа возможна только после согласования условий",
        )
    assert_belarus_gate(db, deal, "handoff")

    proposal = db.get(Proposal, payload.proposal_id)
    if proposal is None or proposal.deal_id != deal.id:
        raise HTTPException(status_code=422, detail={"proposal_id": "Версия КП не относится к сделке"})
    if proposal.state != ProposalState.SENT:
        raise HTTPException(status_code=422, detail={"proposal_id": "Версия КП ещё не отправлена"})
    latest_sent = db.scalar(
        select(Proposal).where(Proposal.deal_id == deal.id, Proposal.state == ProposalState.SENT)
        .order_by(Proposal.version.desc()).limit(1)
    )
    if latest_sent is not None and latest_sent.id != proposal.id:
        raise HTTPException(
            status_code=422,
            detail={"proposal_id": f"Передавайте актуальную версию КП v{latest_sent.version}"},
        )

    recipient = ensure_user(db, payload.recipient_id, field="recipient_id")
    scope = (payload.agreed_scope or deal.agreed_scope or "").strip()
    price = payload.agreed_price if payload.agreed_price is not None else deal.amount
    currency = clean_currency(payload.currency or deal.currency)
    deadline = (payload.agreed_deadline_or_note or deal.agreed_deadline_or_note or "").strip()
    missing = {}
    if not scope:
        missing["agreed_scope"] = "Укажите объём работ"
    if price is None:
        missing["agreed_price"] = "Укажите сумму"
    if not currency:
        missing["currency"] = "Укажите валюту"
    if not deadline:
        missing["agreed_deadline_or_note"] = "Укажите срок или отметку о согласовании"
    if missing:
        raise HTTPException(status_code=422, detail=missing)

    handoff = Handoff(
        deal_id=deal.id,
        recipient_id=recipient.id,
        proposal_id=proposal.id,
        agreed_scope=scope,
        agreed_price=Decimal(price),
        currency=currency,
        agreed_deadline_or_note=deadline,
        materials_link=(payload.materials_link or "").strip() or None,
        notes=payload.notes,
        created_by=actor.id,
    )
    db.add(handoff)
    deal.stage = DealStage.HANDED_OVER
    deal.handed_over_at = deal.handed_over_at or utcnow()
    deal.agreed_scope = scope
    deal.amount = Decimal(price)
    deal.currency = currency
    deal.agreed_deadline_or_note = deadline
    touch(deal)
    bump_version(deal)
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.HANDOFF,
        notes=f"Заказ передан: {recipient.full_name}, КП v{proposal.version}, {price} {currency}",
    )
    db.commit()
    db.refresh(handoff)
    return handoff


# ===== Подтверждение продажи =====
def confirm_sale(db: Session, deal: Deal, payload, actor: User) -> Deal:
    ensure_version(deal, payload.version)
    criterion = get_setting(db, "SALE_CONFIRMATION_CRITERION", "")
    if not criterion:
        raise HTTPException(
            status_code=409,
            detail="Критерий подтверждения продажи не задан. Обратитесь к руководителю.",
        )
    if deal.confirmed_at is not None:
        return deal  # идемпотентность: повторное сохранение не создаёт второе подтверждение
    if DealStage(stage_value(deal.stage)) != DealStage.HANDED_OVER:
        raise HTTPException(
            status_code=409,
            detail="Подтвердить продажу можно только после передачи заказа",
        )
    reference = (payload.confirmation_reference or payload.notes or "").strip()
    if not reference:
        raise HTTPException(status_code=422, detail={"confirmation_reference": "Укажите ссылку или номер подтверждения"})

    deal.stage = DealStage.SALE_CONFIRMED
    deal.confirmed_at = utcnow()
    deal.confirmation_reference = reference
    touch(deal)
    bump_version(deal)
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.SALE_CONFIRMATION, notes=f"Подтверждено: {reference}",
    )
    db.commit()
    db.refresh(deal)
    return deal


# ===== Заметки и история =====
def add_note(db: Session, deal: Deal, payload: NoteCreate, actor: User) -> Activity:
    allowed = {ActivityType.CALL, ActivityType.MESSAGE, ActivityType.NOTE, ActivityType.AGREEMENT}
    activity_type = payload.activity_type
    if activity_type not in {a.value for a in allowed}:
        raise HTTPException(status_code=422, detail={"activity_type": "Допустимо: call, message, note, agreement"})
    if payload.contact_id:
        contact = db.get(Contact, payload.contact_id)
        if contact is None or contact.company_id != deal.company_id:
            raise HTTPException(status_code=422, detail={"contact_id": "Контакт не относится к компании"})
    text = payload.notes.strip()
    if not text:
        raise HTTPException(status_code=422, detail={"notes": "Заполните заметку"})
    activity = log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        contact_id=payload.contact_id, activity_type=activity_type, notes=text,
    )
    db.commit()
    db.refresh(activity)
    return activity


def deal_history(db: Session, deal: Deal, limit: int = 100) -> list[Activity]:
    return list(db.scalars(
        select(Activity).where(Activity.deal_id == deal.id)
        .order_by(Activity.occurred_at.desc()).limit(limit)
    ).all())


# ===== Беларусь и откат =====
def check_belarus(db: Session, deal: Deal, actor: User) -> dict:
    country = db.get(Country, deal.company.country_id)
    if country is None or not country.market_check_required:
        return {"required": False, "status": MarketCheckStatus.NOT_REQUIRED.value}
    required_role = get_setting(db, "BELARUS_CHECKER_ROLE", "manager")
    if required_role == "supervisor" and not is_supervisor(actor):
        raise HTTPException(status_code=403, detail="Проверку по Беларуси выполняет руководитель")
    deal.market_check_status = MarketCheckStatus.PASSED
    deal.market_check_by = actor.id
    deal.market_check_at = utcnow()
    deal.market_check_note = (deal.market_check_note or "Проверено")
    bump_version(deal)
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.NOTE, notes="Проверка рынка Беларуси пройдена",
    )
    db.commit()
    return {
        "required": True,
        "status": MarketCheckStatus.PASSED.value,
        "by": actor.id,
        "at": deal.market_check_at.isoformat(),
    }


def rollback_stage(db: Session, deal: Deal, target_stage: str, reason: str, actor: User) -> Deal:
    if not is_supervisor(actor):
        raise HTTPException(status_code=403, detail="Откат стадии доступен только руководителю")
    if not (reason or "").strip():
        raise HTTPException(status_code=422, detail={"reason": "Укажите причину отката"})
    try:
        target = DealStage(target_stage)
    except ValueError:
        raise HTTPException(status_code=422, detail={"stage": "Неизвестная стадия"})

    old = DealStage(stage_value(deal.stage))
    if target == old:
        raise HTTPException(status_code=409, detail="Сделка уже на этой стадии")

    order = {s: i for i, s in enumerate(ACTIVE_STAGES)}
    if target in order and old in order and order[target] >= order[old]:
        raise HTTPException(status_code=409, detail="Откат возможен только на более раннюю стадию")

    deal.stage = target
    # Актуальный статус определяет отчётность; история исправления сохраняется.
    if target != DealStage.SALE_CONFIRMED:
        deal.confirmed_at = None
        deal.confirmation_reference = None
    if target not in (DealStage.HANDED_OVER, DealStage.SALE_CONFIRMED):
        deal.handed_over_at = None
        existing = db.scalar(select(Handoff).where(Handoff.deal_id == deal.id).limit(1))
        if existing is not None:
            db.delete(existing)
    if target not in (DealStage.NEGOTIATION, DealStage.PROPOSAL_SENT, DealStage.TERMS_AGREED,
                      DealStage.HANDED_OVER, DealStage.SALE_CONFIRMED):
        deal.negotiated_at = None
    if target in (DealStage.FOUND, DealStage.VERIFIED, DealStage.DEFERRED):
        deal.dm_found_at = None
    if target != DealStage.LOST:
        deal.lost_at = None
        deal.loss_reason = None
    if target == DealStage.DEFERRED and deal.defer_until is None:
        deal.defer_until = utcnow()
    if target != DealStage.DEFERRED:
        deal.defer_until = None

    touch(deal)
    bump_version(deal)
    log_activity(
        db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
        activity_type=ActivityType.STAGE_CHANGE,
        notes=f"ОТКАТ {old.value} -> {target.value}. Причина: {reason.strip()}",
    )
    db.commit()
    db.refresh(deal)
    return deal


def archive_deal(db: Session, deal: Deal, actor: User, reason: Optional[str] = None) -> Deal:
    if not is_supervisor(actor):
        raise HTTPException(status_code=403, detail="Архивировать сделки может только руководитель")
    if deal.archived_at is None:
        deal.archived_at = utcnow()
        bump_version(deal)
        log_activity(
            db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
            activity_type=ActivityType.NOTE, notes=f"Сделка в архиве. {reason or ''}".strip(),
        )
        db.commit()
        db.refresh(deal)
    return deal


def restore_deal(db: Session, deal_id: int, actor: User) -> Deal:
    if not is_supervisor(actor):
        raise HTTPException(status_code=403, detail="Восстановить сделку может только руководитель")
    deal = get_deal_or_404(db, deal_id, actor, include_archived=True)
    if deal.archived_at is not None:
        deal.archived_at = None
        bump_version(deal)
        log_activity(
            db, actor=actor, company_id=deal.company_id, deal_id=deal.id,
            activity_type=ActivityType.NOTE, notes="Сделка восстановлена из архива",
        )
        db.commit()
        db.refresh(deal)
    return deal


def export_deals_csv(
    db: Session,
    actor: User,
    country_id: Optional[int] = None,
    niche_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    stage: Optional[str] = None,
    status_filter: str = "all",
) -> str:
    deals = list_deals(
        db, actor, country_id=country_id, niche_id=niche_id, owner_id=owner_id,
        stage=stage, status_filter=status_filter, limit=100000,
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "id", "company", "owner", "title", "service", "amount", "currency", "stage",
        "next_step", "next_step_due", "created_at", "handed_over_at", "confirmed_at",
    ])
    companies = {c.id: c.name for c in db.scalars(select(Company)).all()}
    users = {u.id: u.full_name for u in db.scalars(select(User)).all()}
    services = {s.id: s.name for s in db.scalars(select(Service)).all()}
    for deal in deals:
        task = next_open_task(db, deal.id)
        writer.writerow([
            deal.id, companies.get(deal.company_id, ""), users.get(deal.owner_id, ""),
            deal.title, services.get(deal.service_id, ""), deal.amount or "", deal.currency or "",
            stage_value(deal.stage), task.summary if task else "",
            task.due_at.isoformat() if task else "",
            deal.created_at.isoformat() if deal.created_at else "",
            deal.handed_over_at.isoformat() if deal.handed_over_at else "",
            deal.confirmed_at.isoformat() if deal.confirmed_at else "",
        ])
    db.add(Journal(kind=ImportKind.EXPORT, entity="deals", actor_id=actor.id,
                   rows_total=len(deals), rows_ok=len(deals)))
    db.commit()
    return out.getvalue()
