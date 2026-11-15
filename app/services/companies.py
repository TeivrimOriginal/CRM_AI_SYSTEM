"""Сервисный слой: компании, контакты, сделки, КП, задачи, импорт, отчёт."""
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import urlparse
from fastapi import HTTPException, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session
from app.enums import (
    ActivityType, DealStage, ImportKind, ProposalState, Role, TaskState,
)
from app.models import (
    Activity, AppSetting, City, Company, Contact, Country, Deal, Handoff,
    Journal, Niche, Proposal, Service, Task, User,
)
from app.schemas_companies import (
    CompanyCreate, CompanyUpdate, ContactCreate, DealCreate, TransitionRequest,
    ProposalCreate, ProposalSentRequest, TaskCreate,
)
DNC_MSG = "Компания в списке «Не связываться» — действие заблокировано"
DNC_CONTACT_MSG = "Контакт в списке «Не связываться» — действие заблокировано"
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
def normalize_domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None
# ===== Companies =====
def get_company_or_404(db: Session, company_id: int, actor: User) -> Company:
    c = db.get(Company, company_id)
    if not c or c.archived_at is not None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    if actor.role != Role.SUPERVISOR:
        has_deal = db.scalar(
            select(Deal.id).where(Deal.company_id == c.id, Deal.owner_id == actor.id).limit(1)
        )
        if c.owner_id != actor.id and not has_deal:
            raise HTTPException(status_code=403, detail="Нет доступа")
    return c
def create_company(db: Session, payload: CompanyCreate, actor: User) -> Company:
    owner_id = payload.owner_id if (actor.role == Role.SUPERVISOR and payload.owner_id) else actor.id
    owner = db.get(User, owner_id)
    if not owner or not owner.is_active:
        raise HTTPException(status_code=422, detail={"owner_id": "Ответственный не найден"})
    if not db.get(Country, payload.country_id):
        raise HTTPException(status_code=422, detail={"country_id": "Страна не найдена"})
    if payload.city_id:
        city = db.get(City, payload.city_id)
        if not city or city.country_id != payload.country_id:
            raise HTTPException(status_code=422, detail={"city_id": "Город не относится к выбранной стране"})
    c = Company(
        name=payload.name.strip(),
        country_id=payload.country_id,
        city_id=payload.city_id,
        niche_id=payload.niche_id,
        website_url=payload.website_url,
        normalized_domain=normalize_domain(payload.website_url),
        source_url=payload.source_url,
        owner_id=owner_id,
        observed_need=payload.observed_need,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
def update_company(db: Session, company: Company, payload: CompanyUpdate, actor: User) -> Company:
    data = payload.model_dump(exclude_unset=True)
    if "website_url" in data:
        data["normalized_domain"] = normalize_domain(data["website_url"])
    for k, v in data.items():
        setattr(company, k, v)
    db.commit()
    db.refresh(company)
    return company
def list_companies(db: Session, actor: User, q=None, country_id=None, city_id=None,
                   niche_id=None, owner_id=None, page=1, page_size=50):
    stmt = select(Company).where(Company.archived_at.is_(None))
    if actor.role != Role.SUPERVISOR:
        has_own_deal = exists().where(Deal.company_id == Company.id, Deal.owner_id == actor.id)
        stmt = stmt.where(or_(Company.owner_id == actor.id, has_own_deal))
    elif owner_id:
        stmt = stmt.where(Company.owner_id == owner_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.normalized_domain.ilike(like)))
    if country_id:
        stmt = stmt.where(Company.country_id == country_id)
    if city_id:
        stmt = stmt.where(Company.city_id == city_id)
    if niche_id:
        stmt = stmt.where(Company.niche_id == niche_id)
    stmt = stmt.order_by(Company.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total
def restore_company(db: Session, company_id: int, actor: User) -> Company:
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    c.archived_at = None
    db.commit()
    return c
def reassign_company(db: Session, company_id: int, new_owner_id: int,
                     reassign_open_deals: bool, actor: User) -> Company:
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    new_owner = db.get(User, new_owner_id)
    if not new_owner or not new_owner.is_active:
        raise HTTPException(status_code=422, detail={"owner_id": "Ответственный не найден"})
    old_owner = c.owner_id
    c.owner_id = new_owner_id
    if reassign_open_deals:
        deals = db.scalars(
            select(Deal).where(
                Deal.company_id == company_id,
                Deal.stage.notin_([DealStage.LOST, DealStage.SALE_CONFIRMED]),
            )
        ).all()
        for d in deals:
            d.owner_id = new_owner_id
    db.add(Activity(
        company_id=c.id, actor_id=actor.id, activity_type=ActivityType.REASSIGNMENT,
        notes=f"{old_owner} -> {new_owner_id} reassign_open_deals={reassign_open_deals}",
    ))
    db.commit()
    return c
# ===== Contacts =====
def add_contact(db: Session, company: Company, payload: ContactCreate, actor: User) -> Contact:
    if company.do_not_contact:
        raise HTTPException(status_code=409, detail=DNC_MSG)
    if not payload.name and not payload.position:
        raise HTTPException(status_code=422, detail={"name": "Укажите имя или должность"})
    c = Contact(company_id=company.id, **payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
def list_contacts(db: Session, company: Company):
    return db.scalars(select(Contact).where(Contact.company_id == company.id).order_by(Contact.id)).all()
# ===== Deals =====
def get_deal_or_404(db: Session, deal_id: int, actor: User) -> Deal:
    d = db.get(Deal, deal_id)
    if not d:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    if actor.role != Role.SUPERVISOR and d.owner_id != actor.id:
        raise HTTPException(status_code=403, detail="Нет доступа")
    return d
def create_deal(db: Session, payload: DealCreate, actor: User) -> Deal:
    company = db.get(Company, payload.company_id)
    if not company or company.archived_at is not None:
        raise HTTPException(status_code=422, detail={"company_id": "Компания не найдена"})
    owner_id = payload.owner_id if (actor.role == Role.SUPERVISOR and payload.owner_id) else actor.id
    owner = db.get(User, owner_id)
    if not owner or not owner.is_active:
        raise HTTPException(status_code=422, detail={"owner_id": "Ответственный не найден"})
    if not db.get(Service, payload.service_id):
        raise HTTPException(status_code=422, detail={"service_id": "Услуга не найдена"})
    d = Deal(
        company_id=payload.company_id,
        contact_id=payload.contact_id,
        owner_id=owner_id,
        title=payload.title.strip(),
        service_id=payload.service_id,
        customer_need=payload.customer_need,
        amount=payload.amount,
        currency=payload.currency,
        stage=DealStage.FOUND,
    )
    db.add(d)
    db.flush()
    db.add(Activity(
        company_id=company.id, deal_id=d.id, actor_id=actor.id,
        activity_type=ActivityType.STAGE_CHANGE, notes="Сделка создана",
    ))
    db.commit()
    db.refresh(d)
    return d
def list_deals(db: Session, actor: User, country_id=None, niche_id=None,
               owner_id=None, stage=None):
    stmt = select(Deal)
    if actor.role != Role.SUPERVISOR:
        stmt = stmt.where(Deal.owner_id == actor.id)
    elif owner_id:
        stmt = stmt.where(Deal.owner_id == owner_id)
    if stage:
        stmt = stmt.where(Deal.stage == stage)
    if country_id:
        stmt = stmt.join(Company, Company.id == Deal.company_id).where(Company.country_id == country_id)
    if niche_id:
        stmt = stmt.join(Company, Company.id == Deal.company_id).where(Company.niche_id == niche_id)
    return db.scalars(stmt.order_by(Deal.created_at.desc()).limit(500)).all()
def transition_deal(db: Session, deal: Deal, payload: TransitionRequest, actor: User) -> Deal:
    if payload.stage not in {s.value for s in DealStage}:
        raise HTTPException(status_code=422, detail={"stage": "Неизвестная стадия"})
    new_stage = DealStage(payload.stage)
    old_stage = deal.stage
    if new_stage == DealStage.VERIFIED:
        if not payload.source_url:
            raise HTTPException(status_code=422, detail={"source_url": "Требуется source_url"})
        deal.company.source_url = payload.source_url
        if not deal.company.verified_at:
            deal.company.verified_at = _utcnow()
    elif new_stage == DealStage.DM_FOUND:
        if not payload.contact_id:
            raise HTTPException(status_code=422, detail={"contact_id": "Укажите ЛПР"})
        c = db.get(Contact, payload.contact_id)
        if not c or c.company_id != deal.company_id or not c.is_decision_maker:
            raise HTTPException(status_code=422, detail={"contact_id": "Контакт не является ЛПР этой компании"})
        deal.contact_id = payload.contact_id
    elif new_stage == DealStage.NEGOTIATION:
        open_task = db.scalar(
            select(Task.id).where(Task.deal_id == deal.id, Task.state == TaskState.OPEN).limit(1)
        )
        if not open_task:
            raise HTTPException(status_code=422, detail={"task": "Нужна открытая задача (следующий шаг)"})
    elif new_stage == DealStage.TERMS_AGREED:
        missing = {}
        if not payload.agreed_scope:
            missing["agreed_scope"] = "Укажите объём"
        if payload.amount is None:
            missing["amount"] = "Укажите сумму"
        if not payload.currency:
            missing["currency"] = "Укажите валюту"
        if not payload.agreed_deadline_or_note:
            missing["agreed_deadline_or_note"] = "Укажите срок"
        if not payload.agreement_reference:
            missing["agreement_reference"] = "Укажите ссылку"
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        deal.agreed_scope = payload.agreed_scope
        deal.amount = payload.amount
        deal.currency = payload.currency
        deal.agreed_deadline_or_note = payload.agreed_deadline_or_note
        deal.agreement_reference = payload.agreement_reference
    elif new_stage == DealStage.DEFERRED:
        if not payload.defer_until:
            raise HTTPException(status_code=422, detail={"defer_until": "Укажите дату"})
        open_task = db.scalar(
            select(Task.id).where(Task.deal_id == deal.id, Task.state == TaskState.OPEN).limit(1)
        )
        if not open_task:
            raise HTTPException(status_code=422, detail={"task": "Нужна открытая задача"})
        deal.previous_working_stage = old_stage
        deal.defer_until = payload.defer_until
    elif new_stage == DealStage.LOST:
        if not payload.loss_reason:
            raise HTTPException(status_code=422, detail={"loss_reason": "Укажите причину"})
        deal.loss_reason = payload.loss_reason
    elif new_stage == DealStage.SALE_CONFIRMED:
        criterion = get_setting(db, "SALE_CONFIRMATION_CRITERION", "")
        if not criterion:
            raise HTTPException(status_code=409, detail="Критерий подтверждения продажи не задан (SALE_CONFIRMATION_CRITERION)")
        deal.confirmed_at = _utcnow()
        deal.confirmation_reference = payload.notes
    deal.stage = new_stage
    db.add(Activity(
        company_id=deal.company_id, deal_id=deal.id, actor_id=actor.id,
        activity_type=ActivityType.STAGE_CHANGE,
        notes=f"{old_stage} -> {new_stage.value}" + (f" | {payload.notes}" if payload.notes else ""),
    ))
    db.commit()
    db.refresh(deal)
    return deal
# ===== Proposals =====
def create_proposal(db: Session, deal: Deal, payload: ProposalCreate, actor: User) -> Proposal:
    last = db.scalar(
        select(Proposal.version).where(Proposal.deal_id == deal.id)
        .order_by(Proposal.version.desc()).limit(1)
    )
    p = Proposal(deal_id=deal.id, version=(last or 0) + 1, link=payload.link, state=ProposalState.DRAFT)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
def send_proposal(db: Session, proposal: Proposal, payload: ProposalSentRequest, actor: User) -> Proposal:
    if proposal.state == ProposalState.SENT:
        raise HTTPException(status_code=409, detail="КП уже отправлено")
    if not payload.link:
        raise HTTPException(status_code=422, detail={"link": "Требуется ссылка"})
    deal = db.get(Deal, proposal.deal_id)
    company = db.get(Company, deal.company_id) if deal else None
    if company and company.do_not_contact:
        raise HTTPException(status_code=409, detail="Компания в списке «Не связываться» — отправка КП заблокирована")
    contact = db.get(Contact, payload.sent_contact_id) if payload.sent_contact_id else None
    if contact and contact.company_id != deal.company_id:
        raise HTTPException(status_code=422, detail={"sent_contact_id": "Контакт не принадлежит компании сделки"})
    if contact and contact.do_not_contact:
        raise HTTPException(status_code=409, detail="Контакт в списке «Не связываться» — отправка КП заблокирована")
    proposal.link = payload.link
    proposal.state = ProposalState.SENT
    proposal.sent_at = _utcnow()
    proposal.sent_by = actor.id
    proposal.sent_contact_id = payload.sent_contact_id
    proposal.sent_channel = payload.sent_channel
    if deal.stage in (DealStage.FOUND, DealStage.VERIFIED, DealStage.DM_FOUND):
        deal.stage = DealStage.PROPOSAL_SENT
    db.add(Activity(
        company_id=deal.company_id, deal_id=deal.id, actor_id=actor.id,
        activity_type=ActivityType.PROPOSAL_SENT, notes=f"v{proposal.version}",
    ))
    db.commit()
    db.refresh(proposal)
    return proposal
# ===== Tasks =====
def create_task(db: Session, payload: TaskCreate, actor: User) -> Task:
    deal = get_deal_or_404(db, payload.deal_id, actor)
    company = db.get(Company, deal.company_id)
    if company and company.do_not_contact and payload.action_type in ("call", "message", "send_proposal"):
        raise HTTPException(status_code=409, detail=DNC_MSG)
    if deal.contact_id:
        contact = db.get(Contact, deal.contact_id)
        if contact and contact.do_not_contact and payload.action_type in ("call", "message", "send_proposal"):
            raise HTTPException(status_code=409, detail=DNC_CONTACT_MSG)
    t = Task(
        deal_id=deal.id, assignee_id=actor.id, action_type=payload.action_type,
        summary=payload.summary, due_at=payload.due_at, state=TaskState.OPEN,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t
def complete_task(db: Session, task: Task, actor: User) -> Task:
    task.state = TaskState.DONE
    task.completed_at = _utcnow()
    db.commit()
    return task
def reschedule_task(db: Session, task: Task, due_at: datetime, actor: User) -> Task:
    task.due_at = due_at
    db.commit()
    return task
def list_tasks_for_user(db: Session, user: User):
    return db.scalars(
        select(Task).where(Task.assignee_id == user.id, Task.state == TaskState.OPEN).order_by(Task.due_at)
    ).all()
# ===== Handoff =====
def create_handoff(db: Session, deal: Deal, payload, actor: User) -> Handoff:
    existing = db.scalar(select(Handoff).where(Handoff.deal_id == deal.id).limit(1))
    if existing:
        return existing
    if not payload.recipient_id or not payload.proposal_id:
        raise HTTPException(status_code=422, detail={"handoff": "Укажите получателя и версию КП"})
    p = db.get(Proposal, payload.proposal_id)
    if not p or p.deal_id != deal.id:
        raise HTTPException(status_code=422, detail={"proposal_id": "КП не принадлежит сделке"})
    h = Handoff(
        deal_id=deal.id, recipient_id=payload.recipient_id, proposal_id=payload.proposal_id,
        agreed_scope=payload.agreed_scope or deal.agreed_scope or "",
        agreed_price=payload.agreed_price or deal.amount or 0,
        currency=payload.currency or deal.currency or "",
        agreed_deadline_or_note=payload.agreed_deadline_or_note or deal.agreed_deadline_or_note or "",
        materials_link=payload.materials_link, notes=payload.notes, created_by=actor.id,
    )
    db.add(h)
    deal.stage = DealStage.HANDED_OVER
    deal.handed_over_at = _utcnow()
    db.add(Activity(
        company_id=deal.company_id, deal_id=deal.id, actor_id=actor.id,
        activity_type=ActivityType.HANDOFF, notes=payload.notes,
    ))
    db.commit()
    db.refresh(h)
    return h
# ===== Confirmation =====
def confirm_sale(db: Session, deal: Deal, payload, actor: User) -> Deal:
    criterion = get_setting(db, "SALE_CONFIRMATION_CRITERION", "")
    if not criterion:
        raise HTTPException(status_code=409, detail="Критерий подтверждения продажи не задан (SALE_CONFIRMATION_CRITERION). Обратитесь к руководителю.")
    if deal.confirmed_at is not None:
        return deal
    deal.stage = DealStage.SALE_CONFIRMED
    deal.confirmed_at = _utcnow()
    deal.confirmation_reference = payload.confirmation_reference or payload.notes
    db.add(Activity(
        company_id=deal.company_id, deal_id=deal.id, actor_id=actor.id,
        activity_type=ActivityType.SALE_CONFIRMATION,
        notes=f"Подтверждено: {deal.confirmation_reference}",
    ))
    db.commit()
    db.refresh(deal)
    return deal
# ===== Belarus / rollback =====
def check_belarus(db: Session, deal: Deal, actor: User) -> dict:
    c = db.get(Company, deal.company_id)
    country = db.get(Country, c.country_id) if c else None
    if not country or not country.market_check_required:
        return {"required": False, "status": "not_required"}
    cfg_role = get_setting(db, "BELARUS_CHECKER_ROLE", "manager")
    if cfg_role == "supervisor" and actor.role != Role.SUPERVISOR:
        raise HTTPException(status_code=403, detail="Проверку по Беларуси выполняет руководитель")
    deal.market_check_status = "passed"
    deal.market_check_by = actor.id
    deal.market_check_at = _utcnow()
    deal.market_check_note = "Проверено"
    db.commit()
    return {"required": True, "status": "passed", "by": actor.id}
def rollback_stage(db: Session, deal: Deal, target_stage: str, reason: str, actor: User) -> Deal:
    if actor.role != Role.SUPERVISOR:
        raise HTTPException(status_code=403, detail="Только руководитель")
    if target_stage not in {s.value for s in DealStage}:
        raise HTTPException(status_code=422, detail={"stage": "Неизвестная стадия"})
    if not reason:
        raise HTTPException(status_code=422, detail={"reason": "Укажите причину"})
    old = deal.stage
    deal.stage = target_stage
    db.add(Activity(
        company_id=deal.company_id, deal_id=deal.id, actor_id=actor.id,
        activity_type=ActivityType.STAGE_CHANGE,
        notes=f"ROLLBACK {old} -> {target_stage} | {reason}",
    ))
    db.commit()
    db.refresh(deal)
    return deal
# ===== Settings =====
def get_setting(db: Session, key: str, default: str = "") -> str:
    s = db.get(AppSetting, key)
    return s.value if s else default
def set_setting(db: Session, key: str, value: str, actor: User) -> AppSetting:
    s = db.get(AppSetting, key)
    if s:
        s.value = value
    else:
        s = AppSetting(key=key, value=value)
        db.add(s)
    db.commit()
    return s
# ===== Import / Export =====
def preview_import(db: Session, file_bytes: bytes, filename: str, actor: User) -> dict:
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = file_bytes.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        raise HTTPException(status_code=422, detail={"file": "Не удалось прочитать файл (кодировка)"})
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail={"file": "Пустой файл или нет заголовков"})
    fields_lower = {f.lower().strip(): f for f in reader.fieldnames}
    name_key = fields_lower.get("name") or fields_lower.get("название")
    country_key = fields_lower.get("country") or fields_lower.get("страна")
    city_key = fields_lower.get("city") or fields_lower.get("город")
    site_key = fields_lower.get("website_url") or fields_lower.get("сайт") or fields_lower.get("website")
    if not name_key or not country_key:
        raise HTTPException(status_code=422, detail={"file": "Нужны колонки name и country"})
    countries = {c.name.lower(): c.id for c in db.scalars(select(Country)).all()}
    existing_names = {(c.name.lower(), c.country_id) for c in db.scalars(select(Company)).all()}
    existing_domains = {c.normalized_domain for c in db.scalars(select(Company)).all() if c.normalized_domain}
    seen_in_file = set()
    rows = []
    for i, row in enumerate(reader, start=2):
        name = (row.get(name_key) or "").strip()
        country = (row.get(country_key) or "").strip()
        city = (row.get(city_key) or "").strip() if city_key else ""
        site = (row.get(site_key) or "").strip() if site_key else ""
        r = {"row_number": i, "name": name, "country": country, "city": city,
             "website_url": site, "status": "ok", "reason": None}
        if not name:
            r["status"] = "error"
            r["reason"] = "Пустое название"
        elif not country or country.lower() not in countries:
            r["status"] = "error"
            r["reason"] = f"Страна не найдена: {country}"
        else:
            dom = normalize_domain(site) if site else None
            key = (name.lower(), countries[country.lower()])
            if dom and dom in existing_domains:
                r["status"] = "dup"
                r["reason"] = f"Домен уже есть: {dom}"
            elif key in existing_names or key in seen_in_file:
                r["status"] = "dup"
                r["reason"] = "Компания уже существует"
            else:
                seen_in_file.add(key)
        rows.append(r)
    return {"filename": filename, "rows": rows}
def preview_import_xlsx(db: Session, file_bytes: bytes, filename: str, actor: User) -> dict:
    import pandas as pd
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as e:
        raise HTTPException(status_code=422, detail={"file": f"Не удалось прочитать XLSX: {e}"})
    cols = {str(c).lower().strip(): c for c in df.columns}
    name_c = cols.get("name") or cols.get("название")
    country_c = cols.get("country") or cols.get("страна")
    if not name_c or not country_c:
        raise HTTPException(status_code=422, detail={"file": "Нужны колонки name и country"})
    city_c = cols.get("city") or cols.get("город")
    site_c = cols.get("website_url") or cols.get("сайт") or cols.get("website")
    countries = {c.name.lower(): c.id for c in db.scalars(select(Country)).all()}
    existing_names = {(c.name.lower(), c.country_id) for c in db.scalars(select(Company)).all()}
    existing_domains = {c.normalized_domain for c in db.scalars(select(Company)).all() if c.normalized_domain}
    seen = set()
    rows = []
    for i, row in df.iterrows():
        rn = int(i) + 2
        name = str(row[name_c]).strip() if pd.notna(row[name_c]) else ""
        country = str(row[country_c]).strip() if pd.notna(row[country_c]) else ""
        city = str(row[city_c]).strip() if city_c and pd.notna(row.get(city_c)) else ""
        site = str(row[site_c]).strip() if site_c and pd.notna(row.get(site_c)) else ""
        r = {"row_number": rn, "name": name, "country": country, "city": city,
             "website_url": site, "status": "ok", "reason": None}
        if not name:
            r["status"] = "error"; r["reason"] = "Пустое название"
        elif not country or country.lower() not in countries:
            r["status"] = "error"; r["reason"] = f"Страна не найдена: {country}"
        else:
            dom = normalize_domain(site) if site else None
            key = (name.lower(), countries[country.lower()])
            if dom and dom in existing_domains:
                r["status"] = "dup"; r["reason"] = f"Домен уже есть: {dom}"
            elif key in existing_names or key in seen:
                r["status"] = "dup"; r["reason"] = "Компания уже существует"
            else:
                seen.add(key)
        rows.append(r)
    return {"filename": filename, "rows": rows}
def commit_import(db: Session, rows: list, actor: User, owner_id: Optional[int] = None) -> dict:
    countries = {c.name.lower(): c for c in db.scalars(select(Country)).all()}
    owner = owner_id or actor.id
    ok = 0
    skipped = 0
    failed = 0
    for r in rows:
        try:
            if r.get("status") != "ok":
                if r.get("status") == "dup":
                    skipped += 1
                else:
                    failed += 1
                continue
            country = countries.get((r.get("country") or "").lower())
            if not country:
                failed += 1
                continue
            db.add(Company(
                name=r["name"].strip(),
                country_id=country.id,
                website_url=r.get("website_url"),
                normalized_domain=normalize_domain(r.get("website_url")),
                owner_id=owner,
            ))
            ok += 1
        except Exception:
            failed += 1
    db.add(Journal(
        kind=ImportKind.IMPORT, entity="companies", actor_id=actor.id,
        rows_total=len(rows), rows_ok=ok, rows_skipped=skipped, rows_failed=failed,
    ))
    db.add(Activity(
        company_id=None, actor_id=actor.id, activity_type=ActivityType.IMPORT,
        notes=f"Импорт: принято {ok}, пропущено {skipped}, ошибок {failed}",
    ))
    db.commit()
    return {"ok": ok, "skipped": skipped, "failed": failed}
def export_companies_csv(db: Session, actor: User, q=None, country_id=None, city_id=None,
                         niche_id=None, owner_id=None) -> str:
    rows, _ = list_companies(db, actor, q=q, country_id=country_id, city_id=city_id,
                             niche_id=niche_id, owner_id=owner_id, page=1, page_size=10000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "name", "country_id", "city_id", "niche_id", "website_url",
                "normalized_domain", "owner_id", "do_not_contact", "created_at"])
    for c in rows:
        w.writerow([c.id, c.name, c.country_id, c.city_id, c.niche_id, c.website_url or "",
                    c.normalized_domain or "", c.owner_id, c.do_not_contact, c.created_at.isoformat()])
    db.add(Journal(kind=ImportKind.EXPORT, entity="companies", actor_id=actor.id,
                   rows_total=len(rows), rows_ok=len(rows)))
    db.add(Activity(company_id=None, actor_id=actor.id, activity_type=ActivityType.EXPORT,
                    notes=f"Экспорт компаний: {len(rows)} строк"))
    db.commit()
    return out.getvalue()
def export_deals_csv(db: Session, actor: User, country_id=None, niche_id=None,
                     owner_id=None, stage=None) -> str:
    deals = list_deals(db, actor, country_id=country_id, niche_id=niche_id, owner_id=owner_id, stage=stage)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "company_id", "owner_id", "title", "service_id", "amount", "currency",
                "stage", "created_at", "confirmed_at"])
    for d in deals:
        w.writerow([d.id, d.company_id, d.owner_id, d.title, d.service_id, d.amount or "",
                    d.currency or "", d.stage, d.created_at.isoformat() if d.created_at else "",
                    d.confirmed_at.isoformat() if d.confirmed_at else ""])
    db.add(Journal(kind=ImportKind.EXPORT, entity="deals", actor_id=actor.id,
                   rows_total=len(deals), rows_ok=len(deals)))
    db.add(Activity(company_id=None, actor_id=actor.id, activity_type=ActivityType.EXPORT,
                    notes=f"Экспорт сделок: {len(deals)} строк"))
    db.commit()
    return out.getvalue()
# ===== Report =====
def build_report(db: Session, actor: User, date_from=None, date_to=None, owner_id=None,
                 country_id=None, niche_id=None, service_id=None) -> dict:
    now = datetime.now(timezone.utc)
    stmt = select(Deal)
    if actor.role != Role.SUPERVISOR:
        stmt = stmt.where(Deal.owner_id == actor.id)
    elif owner_id:
        stmt = stmt.where(Deal.owner_id == owner_id)
    if country_id or niche_id:
        stmt = stmt.join(Company, Company.id == Deal.company_id)
        if country_id:
            stmt = stmt.where(Company.country_id == country_id)
        if niche_id:
            stmt = stmt.where(Company.niche_id == niche_id)
    if service_id:
        stmt = stmt.where(Deal.service_id == service_id)
    deals = db.scalars(stmt).all()
    funnel = {s.value: 0 for s in DealStage}
    for d in deals:
        funnel[d.stage] = funnel.get(d.stage, 0) + 1
    open_today = overdue = no_next = 0
    for d in deals:
        if d.stage in (DealStage.LOST, DealStage.SALE_CONFIRMED):
            continue
        ts = db.scalars(select(Task).where(Task.deal_id == d.id, Task.state == TaskState.OPEN)).all()
        if not ts:
            no_next += 1
        for t in ts:
            due = t.due_at
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due.date() < now.date():
                overdue += 1
            elif due.date() == now.date():
                open_today += 1
    confirmed_deals = [d for d in deals if d.confirmed_at is not None]
    if date_from:
        confirmed_deals = [d for d in confirmed_deals if d.confirmed_at >= date_from]
    if date_to:
        confirmed_deals = [d for d in confirmed_deals if d.confirmed_at <= date_to]
    amounts = {}
    for d in confirmed_deals:
        if d.amount and d.currency:
            amounts[d.currency] = amounts.get(d.currency, 0) + float(d.amount)
    handoffs = [d for d in deals if d.handed_over_at is not None]
    if date_from:
        handoffs = [d for d in handoffs if d.handed_over_at >= date_from]
    if date_to:
        handoffs = [d for d in handoffs if d.handed_over_at <= date_to]
    proposals_q = select(Proposal).join(Deal, Deal.id == Proposal.deal_id)
    if actor.role != Role.SUPERVISOR:
        proposals_q = proposals_q.where(Deal.owner_id == actor.id)
    proposals = db.scalars(proposals_q).all()
    sent_props = [p for p in proposals if p.sent_at is not None]
    if date_from:
        sent_props = [p for p in sent_props if p.sent_at >= date_from]
    if date_to:
        sent_props = [p for p in sent_props if p.sent_at <= date_to]
    unique_deals_with_proposal = len({p.deal_id for p in sent_props})
    loss_deals = [d for d in deals if d.stage == DealStage.LOST and d.loss_reason]
    return {
        "funnel": funnel,
        "workload": {"open_today": open_today, "overdue": overdue, "no_next": no_next},
        "period": {
            "proposals_sent": len(sent_props),
            "proposals_unique_deals": unique_deals_with_proposal,
            "handoffs": len(handoffs),
            "sales_confirmed": len(confirmed_deals),
            "amounts": amounts,
            "losses": len(loss_deals),
            "loss_reasons": [d.loss_reason for d in loss_deals],
        },
    }
def build_report_full(db: Session, actor: User, date_from=None, date_to=None, owner_id=None,
                      country_id=None, niche_id=None, service_id=None) -> dict:
    base = build_report(db, actor, date_from=date_from, date_to=date_to, owner_id=owner_id,
                        country_id=country_id, niche_id=niche_id, service_id=service_id)
    base["period"]["verified_companies"] = 0
    base["period"]["dm_found_deals"] = 0
    try:
        q = select(Activity).where(Activity.activity_type == ActivityType.STAGE_CHANGE)
        if date_from:
            q = q.where(Activity.occurred_at >= date_from)
        if date_to:
            q = q.where(Activity.occurred_at <= date_to)
        acts = db.scalars(q).all()
        verified_ids = set()
        dm_ids = set()
        for a in acts:
            if not a.notes:
                continue
            if "-> verified" in a.notes and a.company_id:
                verified_ids.add(a.company_id)
            if "-> dm_found" in a.notes and a.deal_id:
                dm_ids.add(a.deal_id)
        base["period"]["verified_companies"] = len(verified_ids)
        base["period"]["dm_found_deals"] = len(dm_ids)
    except Exception:
        pass
    return base