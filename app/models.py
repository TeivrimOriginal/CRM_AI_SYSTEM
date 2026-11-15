from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import (
    ActivityType, DealStage, ImportKind, MarketCheckStatus, PreferredChannel,
    ProposalState, Role, TaskActionType, TaskState,
)
from app.timeutils import utcnow as _utcnow


# ===== Users =====
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # уникальный логин
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(String(20), default=Role.MANAGER)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ===== Directories =====
class Country(Base):
    __tablename__ = "countries"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Для Беларуси: рынок требует отдельной проверки перед сделкой
    market_check_required: Mapped[bool] = mapped_column(Boolean, default=False)

    cities: Mapped[list["City"]] = relationship(back_populates="country")


class City(Base):
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(primary_key=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"))
    name: Mapped[str] = mapped_column(String(120))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    country: Mapped["Country"] = relationship(back_populates="cities")
    __table_args__ = (UniqueConstraint("country_id", "name", name="uq_city_country_name"),)


class Niche(Base):
    __tablename__ = "niches"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ===== Company =====
class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"))
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), nullable=True)
    niche_id: Mapped[Optional[int]] = mapped_column(ForeignKey("niches.id"), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    normalized_domain: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    observed_need: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Оптимистическая блокировка: клиент присылает ожидаемую версию
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")
    deals: Mapped[list["Deal"]] = relationship(back_populates="company")


# ===== Contact =====
class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_decision_maker: Mapped[bool] = mapped_column(Boolean, default=False)
    work_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    work_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    messenger: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    preferred_channel: Mapped[Optional[PreferredChannel]] = mapped_column(String(20), nullable=True)
    contact_basis: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="contacts")


# ===== Deal =====
class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    customer_need: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    stage: Mapped[DealStage] = mapped_column(String(30), default=DealStage.FOUND, index=True)
    previous_working_stage: Mapped[Optional[DealStage]] = mapped_column(String(30), nullable=True)
    agreed_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agreed_deadline_or_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    agreement_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    market_check_status: Mapped[Optional[MarketCheckStatus]] = mapped_column(String(20), nullable=True)
    market_check_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    market_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    market_check_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    loss_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    defer_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Даты фактических событий — по ним строится отчёт за период
    dm_found_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    negotiated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    handed_over_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    lost_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    confirmation_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    company: Mapped["Company"] = relationship(back_populates="deals")
    proposals: Mapped[list["Proposal"]] = relationship(back_populates="deal")
    tasks: Mapped[list["Task"]] = relationship(back_populates="deal")
    activities: Mapped[list["Activity"]] = relationship(back_populates="deal")


# ===== Proposal =====
class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    link: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    state: Mapped[ProposalState] = mapped_column(String(20), default=ProposalState.DRAFT)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    sent_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    sent_channel: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    deal: Mapped["Deal"] = relationship(back_populates="proposals")
    __table_args__ = (UniqueConstraint("deal_id", "version", name="uq_proposal_deal_version"),)


# ===== Task =====
class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action_type: Mapped[TaskActionType] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    state: Mapped[TaskState] = mapped_column(String(20), default=TaskState.OPEN, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    deal: Mapped["Deal"] = relationship(back_populates="tasks")


# ===== Activity =====
class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True)
    deal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deals.id"), nullable=True)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    activity_type: Mapped[ActivityType] = mapped_column(String(30), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deal: Mapped[Optional["Deal"]] = relationship(back_populates="activities")
    __table_args__ = (
        Index("ix_activity_company_time", "company_id", "occurred_at"),
        Index("ix_activity_deal_time", "deal_id", "occurred_at"),
    )


# ===== Handoff =====
class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), unique=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"))
    agreed_scope: Mapped[str] = mapped_column(Text)
    agreed_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    agreed_deadline_or_note: Mapped[str] = mapped_column(String(500))
    materials_link: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ===== Journals & settings =====
class Journal(Base):
    __tablename__ = "journal"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[ImportKind] = mapped_column(String(10))
    entity: Mapped[str] = mapped_column(String(50))
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ImportPreview(Base):
    """Серверный предпросмотр импорта.

    Коммит идёт по preview_id, поэтому клиент не может подменить строки, а
    повторный коммит возвращает тот же результат (защита от двойного клика).
    """
    __tablename__ = "import_previews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(10), default="csv")
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    headers_json: Mapped[str] = mapped_column(Text, default="[]")
    mapping_json: Mapped[str] = mapped_column(Text, default="{}")
    rows_json: Mapped[str] = mapped_column(Text, default="[]")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_dup: Mapped[int] = mapped_column(Integer, default=0)
    rows_error: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    committed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
