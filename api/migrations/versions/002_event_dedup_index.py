"""Add composite index on (app_id, event_id) for cross-partition event deduplication.

Revision ID: 002_event_dedup_index
Revises: 001_initial_schema
Create Date: 2026-11-01 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "002_event_dedup_index"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_app_event_id ON events (app_id, event_id);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_events_app_event_id;")
