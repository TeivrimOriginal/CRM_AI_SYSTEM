"""Отчёт руководителя: воронка, нагрузка и показатели за период."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ACTIVE_STAGES, DealStage, ProposalState, TaskState
from app.models import Company, Country, Deal, Proposal, Task, User
from app.services.common import is_supervisor, stage_value
from app.timeutils import end_of_day, parse_date, start_of_day, to_naive_utc, today_for, utcnow


def _resolve_range(date_from, date_to, tz_name: str) -> tuple[Optional[datetime], Optional[datetime]]:
    df = date_from if isinstance(date_from, date) or date_from is None else parse_date(str(date_from))
    dt = date_to if isinstance(date_to, date) or date_to is None else parse_date(str(date_to))
    start = start_of_day(df, tz_name) if df else None
    end = end_of_day(dt, tz_name) if dt else None
    if start and end and start > end:
        start, end = end, start
    return start, end


def _in_range(value: Optional[datetime], start: Optional[datetime], end: Optional[datetime]) -> bool:
    if value is None:
        return False
    value = to_naive_utc(value)
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def build_report(
    db: Session,
    actor: User,
    date_from=None,
    date_to=None,
    owner_id: Optional[int] = None,
    country_id: Optional[int] = None,
    niche_id: Optional[int] = None,
    service_id: Optional[int] = None,
    tz_name: Optional[str] = None,
) -> dict:
    tz_name = tz_name or getattr(actor, "timezone", None) or "Europe/Moscow"
    start, end = _resolve_range(date_from, date_to, tz_name)
    today = today_for(tz_name)
    now = utcnow()

    deals_stmt = select(Deal).where(Deal.archived_at.is_(None))
    if not is_supervisor(actor):
        deals_stmt = deals_stmt.where(Deal.owner_id == actor.id)
    elif owner_id:
        deals_stmt = deals_stmt.where(Deal.owner_id == owner_id)
    if service_id:
        deals_stmt = deals_stmt.where(Deal.service_id == service_id)
    if country_id or niche_id:
        deals_stmt = deals_stmt.join(Company, Company.id == Deal.company_id)
        if country_id:
            deals_stmt = deals_stmt.where(Company.country_id == country_id)
        if niche_id:
            deals_stmt = deals_stmt.where(Company.niche_id == niche_id)
    deals = list(db.scalars(deals_stmt).all())
    deal_ids = [d.id for d in deals]
    deals_by_id = {d.id: d for d in deals}

    funnel = {s.value: 0 for s in DealStage}
    for deal in deals:
        funnel[stage_value(deal.stage)] = funnel.get(stage_value(deal.stage), 0) + 1
    active_deals = [d for d in deals if stage_value(d.stage) in {s.value for s in ACTIVE_STAGES}]

    # Нагрузка: задачи по доступным сделкам (и по фильтру ответственного)
    task_stmt = select(Task).where(Task.deal_id.in_(deal_ids)) if deal_ids else select(Task).where(Task.id == -1)
    tasks = list(db.scalars(task_stmt).all())
    open_tasks = [t for t in tasks if t.state == TaskState.OPEN]
    open_today = 0
    overdue = 0
    for task in open_tasks:
        due = to_naive_utc(task.due_at)
        if due is None:
            continue
        if due < now:
            overdue += 1
        elif due <= end_of_day(today, tz_name):
            open_today += 1
    deals_with_open_task = {t.deal_id for t in open_tasks}
    no_next = [d for d in active_deals if d.id not in deals_with_open_task]

    # Показатели за период — по фактическим датам событий
    verified_companies = 0
    if start or end:
        company_stmt = select(Company).where(Company.verified_at.isnot(None), Company.archived_at.is_(None))
        if not is_supervisor(actor):
            company_stmt = company_stmt.where(Company.owner_id == actor.id)
        elif owner_id:
            company_stmt = company_stmt.where(Company.owner_id == owner_id)
        if country_id:
            company_stmt = company_stmt.where(Company.country_id == country_id)
        if niche_id:
            company_stmt = company_stmt.where(Company.niche_id == niche_id)
        for company in db.scalars(company_stmt).all():
            if _in_range(company.verified_at, start, end):
                verified_companies += 1

    dm_found = [d for d in deals if _in_range(d.dm_found_at, start, end)]
    negotiations = [d for d in deals if _in_range(d.negotiated_at, start, end)]
    handoffs = [d for d in deals if _in_range(d.handed_over_at, start, end)]
    confirmed = [d for d in deals if _in_range(d.confirmed_at, start, end)]
    losses = [d for d in deals if _in_range(d.lost_at, start, end)]

    proposals_stmt = select(Proposal).where(Proposal.deal_id.in_(deal_ids)) if deal_ids else select(Proposal).where(Proposal.id == -1)
    proposals = list(db.scalars(proposals_stmt).all())
    sent = [p for p in proposals if p.state == ProposalState.SENT and _in_range(p.sent_at, start, end)]

    amounts: dict[str, float] = {}
    for deal in confirmed:
        if deal.amount is not None and deal.currency:
            amounts[deal.currency] = round(amounts.get(deal.currency, 0.0) + float(deal.amount), 2)

    handoffs_without_confirmation = [d for d in handoffs if d.confirmed_at is None]

    return {
        "funnel": funnel,
        "totals": {
            "deals": len(deals),
            "active_deals": len(active_deals),
            "won": sum(1 for d in deals if stage_value(d.stage) == DealStage.SALE_CONFIRMED.value),
            "lost": sum(1 for d in deals if stage_value(d.stage) == DealStage.LOST.value),
        },
        "workload": {
            "open_today": open_today,
            "overdue": overdue,
            "no_next": len(no_next),
            "no_next_deal_ids": [d.id for d in no_next],
            "overdue_task_ids": [t.id for t in open_tasks if to_naive_utc(t.due_at) and to_naive_utc(t.due_at) < now],
        },
        "period": {
            "date_from": start.isoformat() if start else None,
            "date_to": end.isoformat() if end else None,
            "verified_companies": verified_companies,
            "dm_found_deals": len(dm_found),
            "proposals_sent": len(sent),
            "proposals_unique_deals": len({p.deal_id for p in sent}),
            "negotiations": len(negotiations),
            "handoffs": len(handoffs),
            "handoffs_without_confirmation": len(handoffs_without_confirmation),
            "sales_confirmed": len(confirmed),
            "amounts": amounts,
            "losses": len(losses),
            "loss_reasons": [d.loss_reason for d in losses if d.loss_reason],
        },
        "generated_at": utcnow().isoformat(),
        "timezone": tz_name,
    }


def build_report_full(db: Session, actor: User, **kwargs) -> dict:
    """Совместимый псевдоним: полный отчёт = build_report."""
    return build_report(db, actor, **kwargs)
