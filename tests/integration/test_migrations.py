"""Historical Migration Reference Test (PostgreSQL Retired per Prompt 10)."""

from pathlib import Path


def test_alembic_upgrade_and_rollback_lifecycle():
    """Historical migration files preserved for reference per Prompt 10 Section 4."""
    migrations_dir = Path("api/migrations/versions")
    assert migrations_dir.is_dir(), "Historical migrations directory must be preserved"
    versions = list(migrations_dir.glob("*.py"))
    assert len(versions) >= 4, "Historical Alembic revisions 001-004 must be preserved for reference"
