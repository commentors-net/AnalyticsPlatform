# Infrastructure & Deployment Specifications

Planned for **Milestone M1** (Local Docker Compose) and **Milestone M5** (Cloud Hardening & IaC).

## Role
- Local development orchestration via `docker-compose.yml` (PostgreSQL 16, pgAdmin/Adminer, API, mock services).
- Infrastructure-as-Code (Terraform / Cloud Run service manifests) for production deployments.
- Database migration definitions (Alembic).
- Cloud Build build trigger and container packaging specifications.

*Note: Cloud provisioning and deployment are strictly unauthorized without explicit user approval. All IaC templates are for review and local validation only during planning milestones.*
