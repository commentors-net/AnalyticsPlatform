"""Secure partition RLS, scoped ingest policies, atomic idempotency registry, and session constraints.

Revision ID: 003_secure_rls_and_roles
Revises: 002_event_dedup_index
Create Date: 2026-11-02 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "003_secure_rls_and_roles"
down_revision: Union[str, None] = "002_event_dedup_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. RLS on Child Partition Tables (M2-02)
    partitions = ["events_y2026m11", "events_y2026m12", "events_y2027m01"]
    for part in partitions:
        op.execute(f"ALTER TABLE {part} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {part} FORCE ROW LEVEL SECURITY;")
        op.execute(f"""
        CREATE POLICY {part}_tenant_isolation_policy ON {part}
            FOR ALL
            USING (
                current_setting('app.is_superadmin', true) = 'true'
                OR (
                    app_id = current_setting('app.current_app_id', true)
                    AND environment::text = current_setting('app.current_environment', true)
                )
            )
            WITH CHECK (
                current_setting('app.is_superadmin', true) = 'true'
                OR (
                    app_id = current_setting('app.current_app_id', true)
                    AND environment::text = current_setting('app.current_environment', true)
                )
            );
        """)

    # 2. RLS on Metric Rollup Tables (M2-02)
    op.execute("ALTER TABLE daily_page_metrics ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE daily_page_metrics FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY page_metrics_isolation_policy ON daily_page_metrics
        FOR ALL
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

    op.execute("ALTER TABLE daily_geo_metrics ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE daily_geo_metrics FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY geo_metrics_isolation_policy ON daily_geo_metrics
        FOR ALL
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

    # 3. Refine Ingest Insert Policy on Parent events (M2-02)
    # Remove unconditional current_user = 'analytics_ingest' bypass
    op.execute("DROP POLICY IF EXISTS events_ingest_insert_policy ON events;")
    op.execute("""
    CREATE POLICY events_ingest_insert_policy ON events
        FOR INSERT
        WITH CHECK (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

    # 4. Ingestion Idempotency Registry Table (M2-04)
    op.execute("""
    CREATE TABLE ingestion_idempotency (
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        event_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (app_id, environment, event_id)
    );
    """)
    op.execute("CREATE INDEX idx_idempotency_created_at ON ingestion_idempotency(created_at);")
    op.execute("ALTER TABLE ingestion_idempotency ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ingestion_idempotency FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY idempotency_isolation_policy ON ingestion_idempotency
        FOR ALL
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        )
        WITH CHECK (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

    # 5. Fix Sessions Unique Constraint (M2-14)
    op.execute("ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_session_id_key;")
    op.execute("ALTER TABLE sessions ADD CONSTRAINT sessions_tenant_session_unique UNIQUE (app_id, environment, session_id);")

    # 6. Explicit Role Grants (M2-02, M2-03)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_ingest') THEN
            GRANT USAGE ON SCHEMA public TO analytics_ingest;
            GRANT SELECT, INSERT ON ingestion_idempotency TO analytics_ingest;
            GRANT INSERT ON events TO analytics_ingest;
            GRANT INSERT ON events_y2026m11, events_y2026m12, events_y2027m01 TO analytics_ingest;
            GRANT SELECT, INSERT, UPDATE ON sessions TO analytics_ingest;
            GRANT SELECT ON api_keys TO analytics_ingest;
            GRANT SELECT ON applications TO analytics_ingest;
        END IF;

        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_dashboard') THEN
            GRANT SELECT ON daily_page_metrics, daily_geo_metrics, ingestion_idempotency TO analytics_dashboard;
            GRANT SELECT ON events_y2026m11, events_y2026m12, events_y2027m01 TO analytics_dashboard;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    # 1. Revert Sessions Constraint
    op.execute("ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_tenant_session_unique;")
    op.execute("""
        DELETE FROM sessions a USING sessions b 
        WHERE a.ctid < b.ctid AND a.session_id = b.session_id;
    """)
    op.execute("ALTER TABLE sessions ADD CONSTRAINT sessions_session_id_key UNIQUE (session_id);")

    # 2. Drop Idempotency Table
    op.execute("DROP TABLE IF EXISTS ingestion_idempotency CASCADE;")

    # 3. Revert Ingest Insert Policy
    op.execute("DROP POLICY IF EXISTS events_ingest_insert_policy ON events;")
    op.execute("""
    CREATE POLICY events_ingest_insert_policy ON events
        FOR INSERT
        WITH CHECK (
            current_user = 'analytics_ingest'
            OR current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

    # 4. Drop Metric RLS
    op.execute("DROP POLICY IF EXISTS page_metrics_isolation_policy ON daily_page_metrics;")
    op.execute("ALTER TABLE daily_page_metrics DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS geo_metrics_isolation_policy ON daily_geo_metrics;")
    op.execute("ALTER TABLE daily_geo_metrics DISABLE ROW LEVEL SECURITY;")

    # 5. Drop Partition Policies
    partitions = ["events_y2026m11", "events_y2026m12", "events_y2027m01"]
    for part in partitions:
        op.execute(f"DROP POLICY IF EXISTS {part}_tenant_isolation_policy ON {part};")
        op.execute(f"ALTER TABLE {part} DISABLE ROW LEVEL SECURITY;")
