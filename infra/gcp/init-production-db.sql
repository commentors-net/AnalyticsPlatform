-- Analytics Platform - Production Database Role Provisioning Script
-- Target: Google Cloud SQL for PostgreSQL 16 (Release Gate G1 / Planning Only)
-- Safety: NO hardcoded passwords, NO SUPERUSER, NO BYPASSRLS.
-- Passwords must be generated cryptographically and injected via psql variables or Secret Manager.

-- 1. Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Validate input variables
-- Usage: psql -v ON_ERROR_STOP=1 \
--             -v admin_pass="'$ADMIN_DB_PASSWORD'" \
--             -v ingest_pass="'$INGEST_DB_PASSWORD'" \
--             -v dashboard_pass="'$DASHBOARD_DB_PASSWORD'" \
--             -v app_pass="'$APP_DB_PASSWORD'" \
--             -f init-production-db.sql

\if :{?admin_pass}
\else
  \echo 'ERROR: admin_pass variable is required'
  \quit
\endif

\if :{?ingest_pass}
\else
  \echo 'ERROR: ingest_pass variable is required'
  \quit
\endif

\if :{?dashboard_pass}
\else
  \echo 'ERROR: dashboard_pass variable is required'
  \quit
\endif

\if :{?app_pass}
\else
  \echo 'ERROR: app_pass variable is required'
  \quit
\endif

-- 3. Provision Least-Privilege Roles using psql \gexec (avoids DO $$ quoting limitation)
-- Migration Administrator Role (DDL execution; NOSUPERUSER, NOBYPASSRLS)
SELECT CASE 
    WHEN NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_admin') THEN
        format('CREATE ROLE analytics_admin WITH LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS PASSWORD %s;', :admin_pass)
    ELSE
        format('ALTER ROLE analytics_admin WITH PASSWORD %s NOSUPERUSER NOBYPASSRLS;', :admin_pass)
END \gexec

-- Ingestion Collector Service Role (Row-Level Security Enforced)
SELECT CASE 
    WHEN NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_ingest') THEN
        format('CREATE ROLE analytics_ingest WITH LOGIN NOSUPERUSER NOCREATEDB NOBYPASSRLS PASSWORD %s;', :ingest_pass)
    ELSE
        format('ALTER ROLE analytics_ingest WITH PASSWORD %s NOSUPERUSER NOBYPASSRLS;', :ingest_pass)
END \gexec

-- Dashboard / Analytics Query Service Role (Row-Level Security Enforced)
SELECT CASE 
    WHEN NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_dashboard') THEN
        format('CREATE ROLE analytics_dashboard WITH LOGIN NOSUPERUSER NOCREATEDB NOBYPASSRLS PASSWORD %s;', :dashboard_pass)
    ELSE
        format('ALTER ROLE analytics_dashboard WITH PASSWORD %s NOSUPERUSER NOBYPASSRLS;', :dashboard_pass)
END \gexec

-- General Application Role
SELECT CASE 
    WHEN NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_app') THEN
        format('CREATE ROLE analytics_app WITH LOGIN NOSUPERUSER NOCREATEDB NOBYPASSRLS PASSWORD %s;', :app_pass)
    ELSE
        format('ALTER ROLE analytics_app WITH PASSWORD %s NOSUPERUSER NOBYPASSRLS;', :app_pass)
END \gexec

-- 4. Schema privilege configuration
GRANT CONNECT ON DATABASE analytics_db TO analytics_admin, analytics_ingest, analytics_dashboard, analytics_app;
GRANT USAGE, CREATE ON SCHEMA public TO analytics_admin;
GRANT USAGE ON SCHEMA public TO analytics_ingest, analytics_dashboard, analytics_app;

-- Ensure future tables created by migrations have explicit permissions
ALTER DEFAULT PRIVILEGES FOR ROLE analytics_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO analytics_app;
ALTER DEFAULT PRIVILEGES FOR ROLE analytics_admin IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO analytics_app;
