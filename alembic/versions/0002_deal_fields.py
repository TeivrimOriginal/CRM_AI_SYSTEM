"""add missing deal fields
Revision ID: 0002_deal_fields
Revises: 0001_initial
Create Date: 2026-11-15
"""
from alembic import op
import sqlalchemy as sa
revision = "0002_deal_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.add_column("deals", sa.Column("dm_found_at", sa.DateTime(), nullable=True))
    op.add_column("deals", sa.Column("negotiated_at", sa.DateTime(), nullable=True))
    op.add_column("deals", sa.Column("lost_at", sa.DateTime(), nullable=True))
    op.add_column("deals", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("deals", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_deals_dm_found_at", "deals", ["dm_found_at"])
    op.create_index("ix_deals_negotiated_at", "deals", ["negotiated_at"])
    op.create_index("ix_deals_lost_at", "deals", ["lost_at"])
    op.create_index("ix_deals_handed_over_at", "deals", ["handed_over_at"])
    op.create_index("ix_deals_confirmed_at", "deals", ["confirmed_at"])
    op.add_column("companies", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("proposals", sa.Column("sent_at", sa.DateTime(), nullable=True))
    op.create_index("ix_proposals_sent_at", "proposals", ["sent_at"])
def downgrade() -> None:
    op.drop_index("ix_proposals_sent_at", "proposals")
    op.drop_column("proposals", "sent_at")
    op.drop_column("companies", "version")
    op.drop_index("ix_deals_confirmed_at", "deals")
    op.drop_index("ix_deals_handed_over_at", "deals")
    op.drop_index("ix_deals_lost_at", "deals")
    op.drop_index("ix_deals_negotiated_at", "deals")
    op.drop_index("ix_deals_dm_found_at", "deals")
    op.drop_column("deals", "version")
    op.drop_column("deals", "archived_at")
    op.drop_column("deals", "lost_at")
    op.drop_column("deals", "negotiated_at")
    op.drop_column("deals", "dm_found_at")