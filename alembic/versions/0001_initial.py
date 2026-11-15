"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="manager"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "countries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), unique=True, nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        sa.Column("market_check_required", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("country_id", sa.Integer, sa.ForeignKey("countries.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("country_id", "name", name="uq_city_country_name"),
    )
    op.create_table(
        "niches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(160), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("archived_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), unique=True, nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), index=True, nullable=False),
        sa.Column("country_id", sa.Integer, sa.ForeignKey("countries.id"), nullable=False),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("niche_id", sa.Integer, sa.ForeignKey("niches.id"), nullable=True),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("normalized_domain", sa.String(255), index=True, nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("observed_need", sa.Text, nullable=True),
        sa.Column("verified_at", sa.DateTime, nullable=True),
        sa.Column("do_not_contact", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("is_decision_maker", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("work_email", sa.String(255), nullable=True),
        sa.Column("work_phone", sa.String(64), nullable=True),
        sa.Column("messenger", sa.String(120), nullable=True),
        sa.Column("preferred_channel", sa.String(20), nullable=True),
        sa.Column("contact_basis", sa.String(255), nullable=True),
        sa.Column("do_not_contact", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), index=True, nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("customer_need", sa.Text, nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("stage", sa.String(30), index=True, nullable=False, server_default="found"),
        sa.Column("previous_working_stage", sa.String(30), nullable=True),
        sa.Column("agreed_scope", sa.Text, nullable=True),
        sa.Column("agreed_deadline_or_note", sa.String(500), nullable=True),
        sa.Column("agreement_reference", sa.String(255), nullable=True),
        sa.Column("market_check_status", sa.String(20), nullable=True),
        sa.Column("market_check_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("market_check_at", sa.DateTime, nullable=True),
        sa.Column("market_check_note", sa.Text, nullable=True),
        sa.Column("loss_reason", sa.Text, nullable=True),
        sa.Column("defer_until", sa.DateTime, nullable=True),
        sa.Column("handed_over_at", sa.DateTime, nullable=True),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
        sa.Column("confirmation_reference", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "proposals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), index=True, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("link", sa.String(1000), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("sent_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("sent_contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("sent_channel", sa.String(60), nullable=True),
        sa.UniqueConstraint("deal_id", "version", name="uq_proposal_deal_version"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), index=True, nullable=False),
        sa.Column("assignee_id", sa.Integer, sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("due_at", sa.DateTime, index=True, nullable=False),
        sa.Column("state", sa.String(20), index=True, nullable=False, server_default="open"),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("activity_type", sa.String(30), index=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime, index=True, nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_activity_company_time", "activities", ["company_id", "occurred_at"])
    op.create_index("ix_activity_deal_time", "activities", ["deal_id", "occurred_at"])

    op.create_table(
        "handoffs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id"), unique=True, nullable=False),
        sa.Column("recipient_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("proposal_id", sa.Integer, sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("agreed_scope", sa.Text, nullable=False),
        sa.Column("agreed_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("agreed_deadline_or_note", sa.String(500), nullable=False),
        sa.Column("materials_link", sa.String(1000), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "journal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("rows_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_ok", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("report_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for t in ("app_settings", "journal", "handoffs", "activities", "tasks",
              "proposals", "deals", "contacts", "companies", "services",
              "niches", "cities", "countries", "users"):
        op.drop_table(t)