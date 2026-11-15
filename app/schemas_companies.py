from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VersionedMixin(BaseModel):
    """Ожидаемая версия записи (оптимистическая блокировка)."""
    version: Optional[int] = None


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country_id: int
    city_id: Optional[int] = None
    niche_id: Optional[int] = None
    website_url: Optional[str] = Field(default=None, max_length=500)
    source_url: Optional[str] = Field(default=None, max_length=500)
    observed_need: Optional[str] = None
    owner_id: Optional[int] = None


class CompanyUpdate(VersionedMixin):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    country_id: Optional[int] = None
    city_id: Optional[int] = None
    niche_id: Optional[int] = None
    website_url: Optional[str] = Field(default=None, max_length=500)
    source_url: Optional[str] = Field(default=None, max_length=500)
    observed_need: Optional[str] = None
    do_not_contact: Optional[bool] = None
    owner_id: Optional[int] = None  # только руководитель


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    country_id: int
    city_id: Optional[int] = None
    niche_id: Optional[int] = None
    website_url: Optional[str] = None
    normalized_domain: Optional[str] = None
    source_url: Optional[str] = None
    owner_id: int
    observed_need: Optional[str] = None
    verified_at: Optional[datetime] = None
    do_not_contact: bool
    archived_at: Optional[datetime] = None
    version: int = 1
    created_at: datetime
    updated_at: datetime


class ContactCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    position: Optional[str] = Field(default=None, max_length=255)
    is_decision_maker: bool = False
    work_email: Optional[str] = Field(default=None, max_length=255)
    work_phone: Optional[str] = Field(default=None, max_length=64)
    messenger: Optional[str] = Field(default=None, max_length=120)
    preferred_channel: Optional[str] = Field(default=None, max_length=20)
    contact_basis: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    position: Optional[str] = Field(default=None, max_length=255)
    is_decision_maker: Optional[bool] = None
    work_email: Optional[str] = Field(default=None, max_length=255)
    work_phone: Optional[str] = Field(default=None, max_length=64)
    messenger: Optional[str] = Field(default=None, max_length=120)
    preferred_channel: Optional[str] = Field(default=None, max_length=20)
    contact_basis: Optional[str] = Field(default=None, max_length=255)
    do_not_contact: Optional[bool] = None
    notes: Optional[str] = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int
    name: Optional[str] = None
    position: Optional[str] = None
    is_decision_maker: bool
    work_email: Optional[str] = None
    work_phone: Optional[str] = None
    messenger: Optional[str] = None
    preferred_channel: Optional[str] = None
    contact_basis: Optional[str] = None
    do_not_contact: bool
    notes: Optional[str] = None


class ReassignRequest(BaseModel):
    new_owner_id: int
    reassign_open_deals: bool = False


class DealCreate(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=255)
    service_id: int
    customer_need: Optional[str] = None
    amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    owner_id: Optional[int] = None  # только руководитель


class DealUpdate(VersionedMixin):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    contact_id: Optional[int] = None
    service_id: Optional[int] = None
    customer_need: Optional[str] = None
    amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int
    contact_id: Optional[int] = None
    owner_id: int
    title: str
    service_id: int
    customer_need: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    stage: str
    previous_working_stage: Optional[str] = None
    agreed_scope: Optional[str] = None
    agreed_deadline_or_note: Optional[str] = None
    agreement_reference: Optional[str] = None
    market_check_status: Optional[str] = None
    market_check_by: Optional[int] = None
    market_check_at: Optional[datetime] = None
    market_check_note: Optional[str] = None
    loss_reason: Optional[str] = None
    defer_until: Optional[datetime] = None
    dm_found_at: Optional[datetime] = None
    negotiated_at: Optional[datetime] = None
    handed_over_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    lost_at: Optional[datetime] = None
    confirmation_reference: Optional[str] = None
    archived_at: Optional[datetime] = None
    version: int = 1
    created_at: datetime
    updated_at: datetime


class TransitionRequest(VersionedMixin):
    stage: str
    notes: Optional[str] = None
    source_url: Optional[str] = Field(default=None, max_length=500)
    verification_result: Optional[str] = None
    contact_id: Optional[int] = None
    agreed_scope: Optional[str] = None
    agreed_deadline_or_note: Optional[str] = Field(default=None, max_length=500)
    agreement_reference: Optional[str] = Field(default=None, max_length=255)
    loss_reason: Optional[str] = None
    defer_until: Optional[datetime] = None
    amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)

    @field_validator("stage")
    @classmethod
    def _stage_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Укажите стадию")
        return value.strip()


class ProposalCreate(BaseModel):
    link: Optional[str] = Field(default=None, max_length=1000)
    ready: bool = False


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    deal_id: int
    version: int
    link: Optional[str] = None
    state: str
    sent_at: Optional[datetime] = None
    sent_by: Optional[int] = None
    sent_contact_id: Optional[int] = None
    sent_channel: Optional[str] = None


class ProposalSentRequest(VersionedMixin):
    link: str = Field(min_length=1, max_length=1000)
    sent_contact_id: int
    sent_channel: str = Field(min_length=1, max_length=60)


class TaskCreate(BaseModel):
    deal_id: int
    action_type: str = "other"
    summary: str = Field(min_length=1, max_length=500)
    due_at: datetime
    assignee_id: Optional[int] = None  # только руководитель


class TaskReschedule(BaseModel):
    due_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    deal_id: int
    assignee_id: int
    action_type: str
    summary: str
    due_at: datetime
    state: str
    completed_at: Optional[datetime] = None


class NoteCreate(BaseModel):
    activity_type: str = "note"
    notes: str = Field(min_length=1)
    contact_id: Optional[int] = None


class HandoffRequest(VersionedMixin):
    recipient_id: int
    proposal_id: int
    agreed_scope: Optional[str] = None
    agreed_price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    agreed_deadline_or_note: Optional[str] = Field(default=None, max_length=500)
    materials_link: Optional[str] = Field(default=None, max_length=1000)
    notes: Optional[str] = None


class ConfirmationRequest(VersionedMixin):
    confirmation_reference: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None


class RollbackRequest(BaseModel):
    target_stage: str
    reason: str = Field(min_length=1)


class SettingUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    value: str = ""


class ImportRow(BaseModel):
    row_number: int
    name: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    website_url: Optional[str] = None
    niche: Optional[str] = None
    observed_need: Optional[str] = None
    status: str  # ok | dup | error
    reason: Optional[str] = None
    matched_company_id: Optional[int] = None
    warnings: list[str] = []


class ImportPreviewOut(BaseModel):
    preview_id: str
    filename: Optional[str] = None
    source_kind: str = "csv"
    headers: list[str] = []
    mapping: dict = {}
    owner_id: int
    rows: list[ImportRow] = []
    counts: dict = {}
    created_at: datetime
    expires_at: Optional[datetime] = None


class ImportCommitRequest(BaseModel):
    rows: list[dict] = []
    owner_id: Optional[int] = None


class DirectoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    country_id: Optional[int] = None
    market_check_required: bool = False


class DirectoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    country_id: Optional[int] = None
    market_check_required: Optional[bool] = None
class TaskRescheduleRequest(BaseModel):
    due_at: datetime
ImportPreviewRow = ImportPreviewOut
