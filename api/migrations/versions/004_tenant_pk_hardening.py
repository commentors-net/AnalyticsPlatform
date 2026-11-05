"""Harden RLS bypass, composite tenant primary key on events, and partition coverage.

Revision ID: 004_tenant_pk_hardening
Revises: 003_secure_rls_and_roles
Create Date: 2026-11-02 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "004_tenant_pk_hardening"
down_revision: Union[str, None] = "003_secure_rls_and_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update events primary key to composite (app_id, environment, event_id, timestamp)
    # Allows identical event_id / timestamp across different apps or test/live environments (M2-04)
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_pkey;")
    op.execute("""
        ALTER TABLE events ADD PRIMARY KEY (app_id, environment, event_id, timestamp);
    """)

    # 2. Add October 2026 and future partitions (M2-12)
    new_partitions = [
        ("events_y2026m10", "2026-10-01 00:00:00+00", "2026-11-01 00:00:00+00"),
        ("events_y2027m02", "2027-02-01 00:00:00+00", "2027-03-01 00:00:00+00"),
        ("events_y2027m03", "2027-03-01 00:00:00+00", "2027-04-01 00:00:00+00"),
    ]
    for part_name, start_ts, end_ts in new_partitions:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF events
            FOR VALUES FROM ('{start_ts}') TO ('{end_ts}');
        """)

    all_partitions = [
        "events_y2026m10",
        "events_y2026m11",
        "events_y2026m12",
        "events_y2027m01",
        "events_y2027m02",
        "events_y2027m03",
    ]

    # 3. Harden RLS policies across all tables and partitions (M2-02)
    # Require current_user IN ('analytics_admin', 'postgres') to bypass via app.is_superadmin
    hardened_condition = """
        (
            current_user IN ('analytics_admin', 'postgres')
            AND current_setting('app.is_superadmin', true) = 'true'
        )
        OR (
            app_id = current_setting('app.current_app_id', true)
            AND environment::text = current_setting('app.current_environment', true)
        )
    """

    # Events parent table policy
    op.execute("DROP POLICY IF EXISTS events_tenant_isolation_policy ON events;")
    op.execute(f"""
        CREATE POLICY events_tenant_isolation_policy ON events
            FOR ALL
            USING ({hardened_condition})
            WITH CHECK ({hardened_condition});
    """)

    op.execute("DROP POLICY IF EXISTS events_ingest_insert_policy ON events;")
    op.execute(f"""
        CREATE POLICY events_ingest_insert_policy ON events
            FOR INSERT
            WITH CHECK ({hardened_condition});
    """)

    # Partitions policies
    for part in all_partitions:
        op.execute(f"ALTER TABLE {part} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {part} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {part}_tenant_isolation_policy ON {part};")
        op.execute(f"""
            CREATE POLICY {part}_tenant_isolation_policy ON {part}
                FOR ALL
                USING ({hardened_condition})
                WITH CHECK ({hardened_condition});
        """)

    # Rollup tables policies
    for rollup in ["daily_page_metrics", "daily_geo_metrics"]:
        policy_name = f"{rollup}_isolation_policy"
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {rollup};")
        op.execute(f"""
            CREATE POLICY {policy_name} ON {rollup}
                FOR ALL
                USING ({hardened_condition})
                WITH CHECK ({hardened_condition});
        """)

    # Sessions policy
    op.execute("DROP POLICY IF EXISTS sessions_tenant_isolation_policy ON sessions;")
    op.execute(f"""
        CREATE POLICY sessions_tenant_isolation_policy ON sessions
            FOR ALL
            USING ({hardened_condition})
            WITH CHECK ({hardened_condition});
    """)

    # Idempotency policy
    op.execute("DROP POLICY IF EXISTS idempotency_isolation_policy ON ingestion_idempotency;")
    op.execute(f"""
        CREATE POLICY idempotency_isolation_policy ON ingestion_idempotency
            FOR ALL
            USING ({hardened_condition})
            WITH CHECK ({hardened_condition});
    """)

    # 4. Narrow analytics_dashboard permissions to prevent reading admin tables (M2-02)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_dashboard') THEN
            REVOKE ALL ON api_keys FROM analytics_dashboard;
            REVOKE ALL ON users FROM analytics_dashboard;
            REVOKE ALL ON user_app_permissions FROM analytics_dashboard;
            GRANT SELECT ON applications TO analytics_dashboard;
            GRANT SELECT ON events TO analytics_dashboard;
            GRANT SELECT ON sessions TO analytics_dashboard;
            GRANT SELECT ON daily_page_metrics TO analytics_dashboard;
            GRANT SELECT ON daily_geo_metrics TO analytics_dashboard;
        END IF;
    END $$;
    """)

    for part in all_partitions:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_dashboard') THEN
                GRANT SELECT ON {part} TO analytics_dashboard;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_ingest') THEN
                GRANT INSERT ON {part} TO analytics_ingest;
            END IF;
        END $$;
        """)

    # 5. Grant explicit permissions to analytics_app (create if missing and allowed)
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_app') THEN
            BEGIN
                CREATE ROLE analytics_app WITH LOGIN NOBYPASSRLS PASSWORD 'analytics_app_local_dev';
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            WHEN insufficient_privilege THEN
                NULL;
            END;
        END IF;

        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_app') THEN
            GRANT USAGE ON SCHEMA public TO analytics_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO analytics_app;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO analytics_app;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_pkey;")
    op.execute("""
        DELETE FROM events a USING events b
        WHERE a.ctid < b.ctid AND a.event_id = b.event_id AND a.timestamp = b.timestamp;
    """)
    op.execute("ALTER TABLE events ADD PRIMARY KEY (event_id, timestamp);")
