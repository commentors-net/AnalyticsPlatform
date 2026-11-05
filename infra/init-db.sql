-- Analytics Platform - Local PostgreSQL Initialization Script
-- Prepares extensions and least-privilege roles (COND-03)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Least Privilege Database Roles (COND-03)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_admin') THEN
        CREATE ROLE analytics_admin WITH LOGIN CREATEDB NOBYPASSRLS PASSWORD 'analytics_admin_local_dev';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_ingest') THEN
        CREATE ROLE analytics_ingest WITH LOGIN NOBYPASSRLS PASSWORD 'analytics_ingest_local_dev';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_dashboard') THEN
        CREATE ROLE analytics_dashboard WITH LOGIN NOBYPASSRLS PASSWORD 'analytics_dashboard_local_dev';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_app') THEN
        CREATE ROLE analytics_app WITH LOGIN NOBYPASSRLS PASSWORD 'analytics_app_local_dev';
    END IF;
END $$;
