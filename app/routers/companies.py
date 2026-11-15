from app.schemas_companies import HandoffRequest, ConfirmationRequest
from fastapi.responses import PlainTextResponse
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor
from app.models import Activity, User
from app.schemas_companies import CompanyCreate, CompanyOut, CompanyUpdate, ContactCreate, ContactOut
from app.services import companies as svc
router = APIRouter(prefix="/api/companies", tags=["companies"])
@router.get("", response_model=list[CompanyOut])
def list_companies(q: Optional[str] = None, country_id: Optional[int] = None, city_id: Optional[int] = None,
                   niche_id: Optional[int] = None, owner_id: Optional[int] = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows, _ = svc.list_companies(db, user, q=q, country_id=country_id, city_id=city_id,
                                 niche_id=niche_id, owner_id=owner_id, page=page, page_size=page_size)
    return rows
@router.post("", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.create_company(db, payload, user)
@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_company_or_404(db, company_id, user)
@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, payload: CompanyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    company = svc.get_company_or_404(db, company_id, user)
    return svc.update_company(db, company, payload, user)
@router.delete("/{company_id}", status_code=204)
def archive_company(company_id: int, db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    from datetime import datetime, timezone
    company = svc.get_company_or_404(db, company_id, user)
    company.archived_at = datetime.now(timezone.utc)
    db.commit()
    return None
@router.post("/{company_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(company_id: int, payload: ContactCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    company = svc.get_company_or_404(db, company_id, user)
    return svc.add_contact(db, company, payload, user)
@router.get("/{company_id}/contacts", response_model=list[ContactOut])
def list_contacts(company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    company = svc.get_company_or_404(db, company_id, user)
    return svc.list_contacts(db, company)
@router.get("/{company_id}/history")
def company_history(company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    company = svc.get_company_or_404(db, company_id, user)
    rows = db.scalars(select(Activity).where(Activity.company_id == company.id).order_by(Activity.occurred_at.desc())).all()
    return [{"id": a.id, "activity_type": a.activity_type, "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None, "notes": a.notes, "deal_id": a.deal_id} for a in rows]
# ===== Deals / Proposals / Tasks sub-routers =====
from fastapi import APIRouter as _APIRouter, HTTPException as _HTTPExc
from datetime import datetime as _dt
from app.schemas_companies import (DealCreate, DealOut, TransitionRequest, ProposalCreate,
                                    ProposalOut, ProposalSentRequest, TaskCreate, TaskOut)
from app.models import Deal, Proposal, Task
router_deals = _APIRouter(prefix="/api/deals", tags=["deals"])
router_proposals = _APIRouter(prefix="/api/proposals", tags=["proposals"])
router_tasks = _APIRouter(prefix="/api/tasks", tags=["tasks"])
@router_deals.get("", response_model=list[DealOut])
def list_deals(country_id: Optional[int] = None, niche_id: Optional[int] = None,
               owner_id: Optional[int] = None, stage: Optional[str] = None,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_deals(db, user, country_id=country_id, niche_id=niche_id, owner_id=owner_id, stage=stage)
@router_deals.post("", response_model=DealOut, status_code=201)
def create_deal(payload: DealCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.create_deal(db, payload, user)
@router_deals.get("/{deal_id}", response_model=DealOut)
def get_deal(deal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_deal_or_404(db, deal_id, user)
@router_deals.post("/{deal_id}/transition", response_model=DealOut)
def transition_deal(deal_id: int, payload: TransitionRequest,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deal = svc.get_deal_or_404(db, deal_id, user)
    return svc.transition_deal(db, deal, payload, user)
@router_deals.post("/{deal_id}/proposals", response_model=ProposalOut, status_code=201)
def create_proposal(deal_id: int, payload: ProposalCreate,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deal = svc.get_deal_or_404(db, deal_id, user)
    return svc.create_proposal(db, deal, payload, user)
@router_proposals.post("/{proposal_id}/sent", response_model=ProposalOut)
def send_proposal(proposal_id: int, payload: ProposalSentRequest,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Proposal, proposal_id)
    if not p: raise _HTTPExc(status_code=404, detail="КП не найдено")
    svc.get_deal_or_404(db, p.deal_id, user)
    return svc.send_proposal(db, p, payload, user)
@router_tasks.get("", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_tasks_for_user(db, user)
@router_tasks.post("", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.create_task(db, payload, user)
@router_tasks.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(Task, task_id)
    if not t: raise _HTTPExc(status_code=404, detail="Задача не найдена")
    if user.role != "supervisor" and t.assignee_id != user.id:
        raise _HTTPExc(status_code=403, detail="Нет доступа")
    return svc.complete_task(db, t, user)
@router_tasks.post("/{task_id}/reschedule", response_model=TaskOut)
def reschedule_task(task_id: int, due_at: _dt,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(Task, task_id)
    if not t: raise _HTTPExc(status_code=404, detail="Задача не найдена")
    return svc.reschedule_task(db, t, due_at, user)
@router_deals.post("/{deal_id}/handoff")
def create_handoff(deal_id: int, payload: HandoffRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deal = svc.get_deal_or_404(db, deal_id, user)
    h = svc.create_handoff(db, deal, payload, user)
    return {"id": h.id, "deal_id": h.deal_id}

@router_deals.post("/{deal_id}/confirmation", response_model=DealOut)
def confirm_sale(deal_id: int, payload: ConfirmationRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deal = svc.get_deal_or_404(db, deal_id, user)
    return svc.confirm_sale(db, deal, payload, user)

router_reports = APIRouter(prefix="/api/reports", tags=["reports"])
@router_reports.get("")
def get_report(date_from: Optional[str] = None, date_to: Optional[str] = None,
               owner_id: Optional[int] = None, country_id: Optional[int] = None,
               niche_id: Optional[int] = None, service_id: Optional[int] = None,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from datetime import datetime as _dt
    df = _dt.fromisoformat(date_from) if date_from else None
    dt = _dt.fromisoformat(date_to) if date_to else None
    return svc.build_report(db, user, date_from=df, date_to=dt, owner_id=owner_id,
                            country_id=country_id, niche_id=niche_id, service_id=service_id)

from fastapi import File as _File, UploadFile as _UploadFile
from app.schemas_companies import ImportPreviewRow, ImportCommitRequest, SettingUpdate
router_imports = APIRouter(prefix="/api/imports", tags=["imports"])
router_settings = APIRouter(prefix="/api/settings", tags=["settings"])
@router_imports.post("/preview")
async def imports_preview(file: _UploadFile = _File(...),
                          db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    content = await file.read()
    return svc.preview_import(db, content, file.filename, user)
@router_imports.post("/commit")
def imports_commit(payload: ImportCommitRequest,
                   db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    return svc.commit_import(db, [r for r in payload.rows], user, owner_id=payload.owner_id)
@router_settings.get("")
def get_settings(db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    from app.models import AppSetting
    keys = ["SALE_CONFIRMATION_CRITERION", "BELARUS_CHECK_REQUIRED_BEFORE", "BELARUS_CHECKER_ROLE"]
    return {k: svc.get_setting(db, k, "") for k in keys}
@router_settings.post("")
def update_setting(payload: SettingUpdate,
                   db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    svc.set_setting(db, payload.key, payload.value, user)
    return {"ok": True}
from fastapi.responses import PlainTextResponse as _PlainText
@router.get("/export.csv", response_class=_PlainText)
def export_companies_csv(q: Optional[str] = None, country_id: Optional[int] = None,
                         city_id: Optional[int] = None, niche_id: Optional[int] = None,
                         owner_id: Optional[int] = None,
                         db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    csv_text = svc.export_companies_csv(db, user, q=q, country_id=country_id, city_id=city_id,
                                        niche_id=niche_id, owner_id=owner_id)
    return _PlainText(content=csv_text, media_type="text/csv",
                      headers={"Content-Disposition": "attachment; filename=companies.csv"})
@router.post("/{company_id}/restore")
def restore_company(company_id: int, db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    svc.restore_company(db, company_id, user)
    return {"ok": True}
@router.post("/{company_id}/reassign")
def reassign_company(company_id: int, new_owner_id: int, reassign_open_deals: bool = False,
                     db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    svc.reassign_company(db, company_id, new_owner_id, reassign_open_deals, user)
    return {"ok": True}
@router_deals.get("/export.csv", response_class=PlainTextResponse)
def export_deals_csv(country_id: Optional[int] = None, niche_id: Optional[int] = None,
                     owner_id: Optional[int] = None, stage: Optional[str] = None,
                     db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    csv_text = svc.export_deals_csv(db, user, country_id=country_id, niche_id=niche_id, owner_id=owner_id, stage=stage)
    return PlainTextResponse(content=csv_text, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=deals.csv"})
@router_deals.post("/{deal_id}/check-belarus")
def check_belarus(deal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deal = svc.get_deal_or_404(db, deal_id, user)
    return svc.check_belarus(db, deal, user)
@router_deals.post("/{deal_id}/rollback")
def rollback_stage(deal_id: int, target_stage: str, reason: str,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    deal = svc.get_deal_or_404(db, deal_id, user)
    return svc.rollback_stage(db, deal, target_stage, reason, user)
@router_imports.post("/preview-xlsx")
async def imports_preview_xlsx(file: _UploadFile = _File(...),
                               db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    content = await file.read()
    return svc.preview_import_xlsx(db, content, file.filename, user)
@router_reports.get("/full")
def get_report_full(date_from: Optional[str] = None, date_to: Optional[str] = None,
                    owner_id: Optional[int] = None, country_id: Optional[int] = None,
                    niche_id: Optional[int] = None, service_id: Optional[int] = None,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from datetime import datetime as _dt
    df = _dt.fromisoformat(date_from) if date_from else None
    dt = _dt.fromisoformat(date_to) if date_to else None
    return svc.build_report_full(db, user, date_from=df, date_to=dt, owner_id=owner_id,
                                 country_id=country_id, niche_id=niche_id, service_id=service_id)
