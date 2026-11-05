"""Initial schema with partitioned events, RLS, and tenant seeding (COND-01, COND-02, COND-05).

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-11-01 16:05:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    # 2. Enums
    op.execute("CREATE TYPE environment_type AS ENUM ('test', 'live');")
    op.execute("CREATE TYPE app_status_type AS ENUM ('ACTIVE', 'SUSPENDED', 'ARCHIVED');")
    op.execute("CREATE TYPE key_status_type AS ENUM ('ACTIVE', 'REVOKED', 'EXPIRED');")
    op.execute("CREATE TYPE user_role_type AS ENUM ('SuperAdmin', 'AppAdmin', 'AppViewer');")
    op.execute("CREATE TYPE event_category_type AS ENUM ('pageview', 'custom', 'click', 'timing');")

    # 3. Applications Table
    op.execute("""
    CREATE TABLE applications (
        app_id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        status app_status_type NOT NULL DEFAULT 'ACTIVE',
        allowed_origins TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 4. API Keys Table
    op.execute("""
    CREATE TABLE api_keys (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        key_hash VARCHAR(64) NOT NULL UNIQUE,
        prefix VARCHAR(32) NOT NULL,
        name VARCHAR(255) NOT NULL,
        status key_status_type NOT NULL DEFAULT 'ACTIVE',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NULL,
        revoked_at TIMESTAMPTZ NULL
    );
    """)
    op.execute("CREATE INDEX idx_api_keys_lookup ON api_keys(key_hash) WHERE status = 'ACTIVE';")
    op.execute("CREATE INDEX idx_api_keys_app ON api_keys(app_id, environment);")

    # 5. Partitioned Events Table (COND-01: event_id composite PK)
    op.execute("""
    CREATE TABLE events (
        event_id UUID NOT NULL DEFAULT gen_random_uuid(),
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        event_type event_category_type NOT NULL DEFAULT 'pageview',
        event_name VARCHAR(128) NOT NULL,
        visitor_id VARCHAR(128) NULL,
        session_id VARCHAR(128) NULL,
        page_path TEXT NOT NULL,
        referrer_domain VARCHAR(255) NULL,
        device_family VARCHAR(32) NULL,
        os_family VARCHAR(32) NULL,
        browser_family VARCHAR(32) NULL,
        country_code VARCHAR(2) NULL,
        region_code VARCHAR(8) NULL,
        city_name VARCHAR(128) NULL,
        ip_masked VARCHAR(45) NULL,
        duration_ms INTEGER NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        timestamp TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (event_id, timestamp)
    ) PARTITION BY RANGE (timestamp);
    """)

    # Pre-create initial monthly partitions
    op.execute("""
    CREATE TABLE events_y2026m11 PARTITION OF events
        FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
    """)
    op.execute("""
    CREATE TABLE events_y2026m12 PARTITION OF events
        FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
    """)
    op.execute("""
    CREATE TABLE events_y2027m01 PARTITION OF events
        FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2027-02-01 00:00:00+00');
    """)

    # Partition Indexes
    op.execute("CREATE INDEX idx_events_app_env_time ON events (app_id, environment, timestamp DESC);")
    op.execute("CREATE INDEX idx_events_visitor ON events (app_id, environment, visitor_id, timestamp DESC) WHERE visitor_id IS NOT NULL;")
    op.execute("CREATE INDEX idx_events_session ON events (session_id, timestamp ASC) WHERE session_id IS NOT NULL;")
    op.execute("CREATE INDEX idx_events_event_name ON events (app_id, environment, event_name, timestamp DESC);")
    op.execute("CREATE INDEX idx_events_metadata_gin ON events USING GIN (metadata);")

    # 6. Sessions Table (COND-05)
    op.execute("""
    CREATE TABLE sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id VARCHAR(128) NOT NULL UNIQUE,
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        visitor_id VARCHAR(128) NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at TIMESTAMPTZ NULL,
        duration_seconds INTEGER NOT NULL DEFAULT 0,
        pageviews_count INTEGER NOT NULL DEFAULT 1,
        entry_page TEXT NOT NULL,
        exit_page TEXT NULL,
        is_bounce BOOLEAN NOT NULL DEFAULT TRUE,
        referrer_domain VARCHAR(255) NULL,
        country_code VARCHAR(2) NULL,
        device_family VARCHAR(32) NULL
    );
    """)
    op.execute("CREATE INDEX idx_sessions_app_env ON sessions (app_id, environment, started_at DESC);")
    op.execute("CREATE INDEX idx_sessions_started_at ON sessions (started_at DESC);")

    # 7. Rollup Metrics Tables
    op.execute("""
    CREATE TABLE daily_app_metrics (
        metric_date DATE NOT NULL,
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        total_pageviews INTEGER NOT NULL DEFAULT 0,
        total_events INTEGER NOT NULL DEFAULT 0,
        unique_sessions INTEGER NOT NULL DEFAULT 0,
        unique_visitors INTEGER NOT NULL DEFAULT 0,
        bounce_count INTEGER NOT NULL DEFAULT 0,
        avg_session_duration_sec INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (metric_date, app_id, environment)
    );
    """)
    op.execute("""
    CREATE TABLE daily_page_metrics (
        metric_date DATE NOT NULL,
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        page_path TEXT NOT NULL,
        views_count INTEGER NOT NULL DEFAULT 0,
        unique_visitors INTEGER NOT NULL DEFAULT 0,
        entry_count INTEGER NOT NULL DEFAULT 0,
        exit_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (metric_date, app_id, environment, page_path)
    );
    """)
    op.execute("""
    CREATE TABLE daily_geo_metrics (
        metric_date DATE NOT NULL,
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        environment environment_type NOT NULL,
        country_code VARCHAR(2) NOT NULL,
        region_code VARCHAR(8) NOT NULL DEFAULT '',
        visitor_count INTEGER NOT NULL DEFAULT 0,
        pageview_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (metric_date, app_id, environment, country_code, region_code)
    );
    """)

    # 8. Users, Permissions & Audit Logs
    op.execute("""
    CREATE TABLE users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email VARCHAR(255) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role user_role_type NOT NULL DEFAULT 'AppViewer',
        status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_login_at TIMESTAMPTZ NULL
    );
    """)
    op.execute("""
    CREATE TABLE user_app_permissions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        app_id VARCHAR(64) NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
        granted_role user_role_type NOT NULL DEFAULT 'AppViewer',
        granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, app_id)
    );
    """)
    op.execute("""
    CREATE TABLE audit_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        action VARCHAR(64) NOT NULL,
        app_id VARCHAR(64) NULL,
        environment environment_type NULL,
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        ip_address VARCHAR(45) NULL,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_audit_logs_user ON audit_logs (user_id, timestamp DESC);")
    op.execute("CREATE INDEX idx_audit_logs_app ON audit_logs (app_id, timestamp DESC);")

    # 9. Row-Level Security Policies (COND-02)
    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE events FORCE ROW LEVEL SECURITY;")

    op.execute("""
    CREATE POLICY events_tenant_select_policy ON events
        FOR SELECT
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

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

    op.execute("""
    CREATE POLICY events_admin_update_policy ON events
        FOR UPDATE
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        )
        WITH CHECK (visitor_id = 'DELETED_ANONYMIZED');
    """)

    op.execute("ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE sessions FORCE ROW LEVEL SECURITY;")

    op.execute("""
    CREATE POLICY sessions_tenant_isolation_policy ON sessions
        FOR ALL
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        )
        WITH CHECK (
            app_id = current_setting('app.current_app_id', true)
            AND environment::text = current_setting('app.current_environment', true)
        );
    """)

    op.execute("ALTER TABLE daily_app_metrics ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE daily_app_metrics FORCE ROW LEVEL SECURITY;")

    op.execute("""
    CREATE POLICY app_metrics_isolation_policy ON daily_app_metrics
        FOR ALL
        USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR (
                app_id = current_setting('app.current_app_id', true)
                AND environment::text = current_setting('app.current_environment', true)
            )
        );
    """)

    # 10. Seed Initial Applications
    op.execute("""
    INSERT INTO applications (app_id, name, status, allowed_origins) VALUES
    ('askanna', 'AskAnna AI Intelligence', 'ACTIVE', 'https://askanna.ai,https://test.askanna.ai'),
    ('groundworks', 'GroundWorks Real Estate & GCNav', 'ACTIVE', 'https://gcnav2.com,https://groundworks.com'),
    ('roomlyst', 'Roomlyst Interior Design', 'ACTIVE', 'https://roomlyst.com,https://app.roomlyst.com'),
    ('nutrilens', 'NutriLens Nutrition AI', 'ACTIVE', 'https://nutrilens.app')
    ON CONFLICT (app_id) DO NOTHING;
    """)

    # 11. Role Grants for Least Privilege Access (COND-03)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_dashboard') THEN
            GRANT USAGE ON SCHEMA public TO analytics_dashboard;
            GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_dashboard;
            GRANT UPDATE ON events TO analytics_dashboard;
            GRANT INSERT, UPDATE, DELETE ON sessions TO analytics_dashboard;
            GRANT INSERT, UPDATE ON api_keys, users, user_app_permissions, audit_logs TO analytics_dashboard;
        END IF;

        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_ingest') THEN
            GRANT USAGE ON SCHEMA public TO analytics_ingest;
            GRANT SELECT ON applications, api_keys TO analytics_ingest;
            GRANT INSERT ON events TO analytics_ingest;
            GRANT SELECT, INSERT, UPDATE ON sessions TO analytics_ingest;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    # 1. Drop RLS Policies
    op.execute("DROP POLICY IF EXISTS app_metrics_isolation_policy ON daily_app_metrics;")
    op.execute("DROP POLICY IF EXISTS sessions_tenant_isolation_policy ON sessions;")
    op.execute("DROP POLICY IF EXISTS events_admin_update_policy ON events;")
    op.execute("DROP POLICY IF EXISTS events_ingest_insert_policy ON events;")
    op.execute("DROP POLICY IF EXISTS events_tenant_select_policy ON events;")

    # 2. Drop Tables
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_app_permissions CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")
    op.execute("DROP TABLE IF EXISTS daily_geo_metrics CASCADE;")
    op.execute("DROP TABLE IF EXISTS daily_page_metrics CASCADE;")
    op.execute("DROP TABLE IF EXISTS daily_app_metrics CASCADE;")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS events_y2027m01 CASCADE;")
    op.execute("DROP TABLE IF EXISTS events_y2026m12 CASCADE;")
    op.execute("DROP TABLE IF EXISTS events_y2026m11 CASCADE;")
    op.execute("DROP TABLE IF EXISTS events CASCADE;")
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE;")
    op.execute("DROP TABLE IF EXISTS applications CASCADE;")

    # 3. Drop Enums
    op.execute("DROP TYPE IF EXISTS event_category_type;")
    op.execute("DROP TYPE IF EXISTS user_role_type;")
    op.execute("DROP TYPE IF EXISTS key_status_type;")
    op.execute("DROP TYPE IF EXISTS app_status_type;")
    op.execute("DROP TYPE IF EXISTS environment_type;")
