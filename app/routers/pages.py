from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import COOKIE_NAME, get_current_user
from app.enums import DealStage, Role, TaskState
from app.models import City, Activity, Company, Country, Deal, Niche, Proposal, Service, Contact, Task, User
from app.security import decode_token
from app.services import companies as svc
router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return RedirectResponse("/login", status_code=302)
    try:
        email = decode_token(token).get("sub")
    except Exception:
        return RedirectResponse("/login", status_code=302)
    user = db.scalar(select(User).where(User.email == email)) if email else None
    if not user or not user.is_active:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/tasks" if user.role == Role.MANAGER else "/companies", status_code=302)
@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    tasks = db.scalars(select(Task).where(Task.assignee_id == user.id, Task.state == TaskState.OPEN)
                       .order_by(Task.due_at)).all()
    today = []
    overdue = []
    upcoming = []
    for t in tasks:
        due = t.due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due.date() < now.date():
            overdue.append(t)
        elif due.date() == now.date():
            today.append(t)
        else:
            upcoming.append(t)
    deals_without_next = db.scalars(
        select(Deal).where(Deal.owner_id == user.id,
                           Deal.stage.notin_([DealStage.LOST, DealStage.SALE_CONFIRMED]),
                           ~Deal.id.in_(select(Task.deal_id).where(Task.state == TaskState.OPEN)))
    ).all() if user.role == Role.MANAGER else []
    deal_map = {d.id: d for d in db.scalars(select(Deal).where(Deal.id.in_([t.deal_id for t in tasks]))).all()} if tasks else {}
    return templates.TemplateResponse("tasks.html", {
        "request": request, "user": user, "today": today, "overdue": overdue,
        "upcoming": upcoming, "no_next": deals_without_next, "deal_map": deal_map,
    })
@router.get("/pipeline", response_class=HTMLResponse)
def pipeline_page(request: Request, country_id: int = 0, niche_id: int = 0, owner_id: int = 0,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deals = svc.list_deals(db, user, country_id=country_id or None, niche_id=niche_id or None, owner_id=owner_id or None)
    by_stage = {s.value: [] for s in DealStage}
    for d in deals:
        by_stage.setdefault(d.stage, []).append(d)
    companies = db.scalars(select(Company).where(Company.archived_at.is_(None))).all()
    if user.role != Role.SUPERVISOR:
        companies = [c for c in companies if c.owner_id == user.id]
    services = db.scalars(select(Service).where(Service.archived_at.is_(None)).order_by(Service.name)).all()
    countries = db.scalars(select(Country).where(Country.archived_at.is_(None)).order_by(Country.name)).all()
    niches = db.scalars(select(Niche).where(Niche.archived_at.is_(None)).order_by(Niche.name)).all()
    managers = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
    companies_by_id = {c.id: c for c in companies}
    return templates.TemplateResponse("pipeline.html", {
        "request": request, "user": user, "by_stage": by_stage, "stages": [s.value for s in DealStage],
        "companies": companies, "services": services, "countries": countries, "niches": niches,
        "managers": managers, "companies_by_id": companies_by_id,
        "filters": {"country_id": country_id, "niche_id": niche_id, "owner_id": owner_id},
    })
@router.get("/deals/{deal_id}", response_class=HTMLResponse)
def deal_card(deal_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        deal = svc.get_deal_or_404(db, deal_id, user)
    except Exception:
        return RedirectResponse("/pipeline", status_code=302)
    company = db.get(Company, deal.company_id)
    proposals = db.scalars(select(Proposal).where(Proposal.deal_id == deal.id).order_by(Proposal.version.desc())).all()
    tasks = db.scalars(select(Task).where(Task.deal_id == deal.id).order_by(Task.due_at.desc())).all()
    activities = db.scalars(select(Activity).where(Activity.deal_id == deal.id).order_by(Activity.occurred_at.desc()).limit(50)).all()
    contacts = db.scalars(select(Contact).where(Contact.company_id == deal.company_id)).all()
    services = db.scalars(select(Service).where(Service.archived_at.is_(None))).all()
    return templates.TemplateResponse("deal_card.html", {
        "request": request, "user": user, "deal": deal, "company": company,
        "proposals": proposals, "tasks": tasks, "activities": activities,
        "contacts": contacts, "services": services, "stages": [s.value for s in DealStage],
    })
@router.get("/companies", response_class=HTMLResponse)
def companies_page(request: Request, q: str = "", country_id: int = 0, city_id: int = 0,
                   niche_id: int = 0, owner_id: int = 0,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from sqlalchemy import exists
    stmt = select(Company).where(Company.archived_at.is_(None))
    if user.role != Role.SUPERVISOR:
        has_own_deal = exists().where(Deal.company_id == Company.id, Deal.owner_id == user.id)
        stmt = stmt.where(or_(Company.owner_id == user.id, has_own_deal))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.normalized_domain.ilike(like)))
    if country_id:
        stmt = stmt.where(Company.country_id == country_id)
    if city_id:
        stmt = stmt.where(Company.city_id == city_id)
    if niche_id:
        stmt = stmt.where(Company.niche_id == niche_id)
    if owner_id and user.role == Role.SUPERVISOR:
        stmt = stmt.where(Company.owner_id == owner_id)
    companies = db.scalars(stmt.order_by(Company.created_at.desc()).limit(300)).all()
    active_deals = dict(db.execute(select(Deal.company_id, func.count(Deal.id))
                                   .where(Deal.stage.notin_([DealStage.LOST, DealStage.SALE_CONFIRMED]))
                                   .group_by(Deal.company_id)).all())
    countries = db.scalars(select(Country).where(Country.archived_at.is_(None)).order_by(Country.name)).all()
    cities = db.scalars(select(City).where(City.archived_at.is_(None)).order_by(City.name)).all()
    niches = db.scalars(select(Niche).where(Niche.archived_at.is_(None)).order_by(Niche.name)).all()
    managers = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
    return templates.TemplateResponse("companies.html", {
        "request": request, "user": user, "companies": companies, "active_deals": active_deals,
        "countries": countries, "cities": cities, "niches": niches, "managers": managers,
        "filters": {"q": q, "country_id": country_id, "city_id": city_id,
                    "niche_id": niche_id, "owner_id": owner_id},
    })

@router.get("/companies/{company_id}", response_class=HTMLResponse)
def company_card(company_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        company = svc.get_company_or_404(db, company_id, user)
    except Exception:
        return RedirectResponse("/companies", status_code=302)
    contacts = svc.list_contacts(db, company)
    history = db.scalars(select(Activity).where(Activity.company_id == company.id).order_by(Activity.occurred_at.desc()).limit(50)).all()
    deals = db.scalars(select(Deal).where(Deal.company_id == company.id).order_by(Deal.created_at.desc())).all()
    services = db.scalars(select(Service).where(Service.archived_at.is_(None)).order_by(Service.name)).all()
    return templates.TemplateResponse("company_card.html", {
        "request": request, "user": user, "company": company, "contacts": contacts,
        "history": history, "deals": deals, "services": services,
    })
@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, date_from: str = "", date_to: str = "", owner_id: int = 0, country_id: int = 0, niche_id: int = 0, service_id: int = 0, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != Role.SUPERVISOR:
        return RedirectResponse("/pipeline", status_code=302)
    from datetime import datetime as _dt
    df = _dt.fromisoformat(date_from) if date_from else None
    dt = _dt.fromisoformat(date_to) if date_to else None
    report = svc.build_report_full(db, user, date_from=df, date_to=dt, owner_id=owner_id or None, country_id=country_id or None, niche_id=niche_id or None, service_id=service_id or None)
    from app.models import User as _U, Country as _C, Niche as _N, Service as _S
    managers = db.scalars(select(_U).where(_U.is_active.is_(True))).all()
    countries = db.scalars(select(_C)).all()
    niches = db.scalars(select(_N)).all()
    services = db.scalars(select(_S)).all()
    return templates.TemplateResponse("reports.html", {"request": request, "user": user, "report": report, "filters": {"date_from": date_from, "date_to": date_to, "owner_id": owner_id, "country_id": country_id, "niche_id": niche_id, "service_id": service_id}, "managers": managers, "countries": countries, "niches": niches, "services": services})
@router.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request, user: User = Depends(get_current_user)):
    if user.role != Role.SUPERVISOR:
        return RedirectResponse("/companies", status_code=302)
    return templates.TemplateResponse("imports.html", {"request": request, "user": user})
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != Role.SUPERVISOR:
        return RedirectResponse("/companies", status_code=302)
    from app.models import City, User as _U, Country as _C, Niche as _N, Service as _S
    managers = db.scalars(select(_U).where(_U.is_active.is_(True))).all()
    countries = db.scalars(select(_C)).all()
    niches = db.scalars(select(_N)).all()
    services = db.scalars(select(_S)).all()
    settings_vals = {
        "SALE_CONFIRMATION_CRITERION": svc.get_setting(db, "SALE_CONFIRMATION_CRITERION", ""),
        "BELARUS_CHECK_REQUIRED_BEFORE": svc.get_setting(db, "BELARUS_CHECK_REQUIRED_BEFORE", "proposal_sent"),
        "BELARUS_CHECKER_ROLE": svc.get_setting(db, "BELARUS_CHECKER_ROLE", "manager"),
    }
    return templates.TemplateResponse("settings.html", {"request": request, "user": user,
        "managers": managers, "countries": countries, "niches": niches, "services": services,
        "settings_vals": settings_vals})
@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})
@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != Role.SUPERVISOR:
        return RedirectResponse("/companies", status_code=302)
    users = db.scalars(select(User).order_by(User.id)).all()
    stats = []
    for u in users:
        companies_count = db.scalar(select(func.count()).select_from(Company).where(Company.owner_id == u.id)) or 0
        deals_count = db.scalar(select(func.count()).select_from(Deal).where(Deal.owner_id == u.id)) or 0
        sales_count = db.scalar(select(func.count()).select_from(Deal).where(Deal.owner_id == u.id, Deal.stage == DealStage.SALE_CONFIRMED)) or 0
        open_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.assignee_id == u.id, Task.state == TaskState.OPEN)) or 0
        now = datetime.now(timezone.utc)
        overdue = 0
        for t in db.scalars(select(Task).where(Task.assignee_id == u.id, Task.state == TaskState.OPEN)).all():
            due = t.due_at
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due < now:
                overdue += 1
        stats.append({
            "user": u, "companies": companies_count, "deals": deals_count,
            "sales": sales_count, "open_tasks": open_tasks, "overdue": overdue,
        })
    return templates.TemplateResponse("admin.html", {"request": request, "user": user, "stats": stats})
