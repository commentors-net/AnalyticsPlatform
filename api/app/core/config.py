"""Application Configuration Settings."""

import os
from typing import Optional, Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "infra/.env.example"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    BEHIND_PROXY: bool = Field(default=False, description="Whether deployed behind trusted reverse proxy (e.g. Cloud Run)")

    # Google Cloud & Firestore Settings
    GCP_PROJECT_ID: str = Field(default="leave-tracker-2025", description="Google Cloud Project ID")
    FIRESTORE_DATABASE: str = Field(default="(default)", description="Firestore database name")
    FIRESTORE_COLLECTION_PREFIX: str = Field(default="analytics_", description="Dedicated collection namespace prefix")
    USE_MOCK_FIRESTORE: bool = Field(default=False, description="Use in-memory mock Firestore for testing/offline")

    # PostgreSQL Connection Settings
    DATABASE_URL: Optional[str] = Field(default=None, description="Direct database connection URL (e.g., Neon serverless PostgreSQL)")
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=5433, description="PostgreSQL port (5433 locally to isolate from gcnav)")
    POSTGRES_DB: str = Field(default="analytics_db", description="Database name")
    POSTGRES_USER: str = Field(default="postgres", description="Database user")
    POSTGRES_PASSWORD: str = Field(default="analytics_dev_password", description="Database password")

    # Database Connection Pool Bounds (COND-04)
    # Bounded pool per worker container to ensure Cloud Run autoscaling never exhausts DB connections
    DB_POOL_MIN_SIZE: int = Field(default=2, description="Minimum connections in pool per worker")
    DB_POOL_MAX_SIZE: int = Field(default=5, description="Maximum connections in pool per worker")
    DB_POOL_TIMEOUT_SECONDS: float = Field(default=10.0, description="Acquisition timeout in seconds")

    # Administrative Authentication & JWT
    ANALYTICS_JWT_SECRET: str = Field(
        default="dev-only-insecure-jwt-secret-do-not-use-in-production-min-32-chars",
        description="JWT HMAC signing secret key (loaded from Secret Manager in production)",
    )
    ANALYTICS_JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    ANALYTICS_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, description="Access token lifespan in minutes")
    ANALYTICS_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token lifespan in days")

    # Google Sign-In OpenID Connect Authentication
    GOOGLE_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Google OAuth 2.0 Web Client ID for audience verification",
    )
    GOOGLE_INITIAL_ADMIN_EMAIL: str = Field(
        default="pranesh.sharma@gmail.com",
        description="Initial approved Google account email provisioned as SuperAdmin",
    )
    COOKIE_SECURE: bool = Field(default=True, description="Require HTTPS for session cookies")
    COOKIE_SAMESITE: str = Field(default="lax", description="SameSite attribute for session cookies")
    USE_MOCK_GOOGLE_AUTH: bool = Field(default=False, description="Enable mock Google ID token verification for tests")

    # Ingestion Bounds & Rate Limiting
    MAX_PAYLOAD_SIZE_BYTES: int = Field(default=65536, description="Max single event payload size (64 KB)")
    MAX_BATCH_SIZE_BYTES: int = Field(default=524288, description="Max batch request payload size (512 KB)")
    MAX_BATCH_EVENTS_COUNT: int = Field(default=50, description="Max events per batch request")
    RATE_LIMIT_PER_IP_MINUTE: int = Field(default=120, description="Rate limit per source IP per minute")
    RATE_LIMIT_PER_KEY_MINUTE: int = Field(default=2000, description="Rate limit per write key per minute")
    TRUSTED_PROXIES: str = Field(default="127.0.0.1,::1", description="Comma-separated trusted proxy IPs or CIDR subnets")

    # Prohibited Data Fields in Event Metadata (M2-07 recursive validation)
    PROHIBITED_METADATA_FIELDS: Set[str] = {
        "vin", "ssn", "password", "token", "chat_message", "credit_card", "secret", "secret_key", "auth",
        "email", "contact_email", "phone", "gps", "latitude", "longitude", "id_token", "magic_link", "credential",
        "api_key", "access_token", "refresh_token", "message", "msg", "user_message"
    }

    @property
    def async_database_url(self) -> str:
        """Construct the asyncpg connection string with Unix domain socket support (M2-15)."""
        if self.DATABASE_URL:
            from sqlalchemy.engine.url import make_url

            url = make_url(self.DATABASE_URL.strip())
            query = dict(url.query)
            if "sslmode" in query:
                mode = query.pop("sslmode")
                if mode in ("require", "verify-ca", "verify-full"):
                    query["ssl"] = "require"
            query.pop("channel_binding", None)
            async_url = url.set(drivername="postgresql+asyncpg", query=query)
            return async_url.render_as_string(hide_password=False)

        if self.POSTGRES_HOST.startswith("/"):
            return (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@/{self.POSTGRES_DB}?host={self.POSTGRES_HOST}"
            )
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        """Construct the psycopg2 / sync connection string with Unix domain socket support (M2-15)."""
        if self.DATABASE_URL:
            from sqlalchemy.engine.url import make_url

            url = make_url(self.DATABASE_URL.strip())
            sync_url = url.set(drivername="postgresql")
            return sync_url.render_as_string(hide_password=False)

        if self.POSTGRES_HOST.startswith("/"):
            return (
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@/{self.POSTGRES_DB}?host={self.POSTGRES_HOST}"
            )
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @field_validator("ANALYTICS_JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and ("insecure" in v.lower() or len(v) < 32):
            raise ValueError("In production, ANALYTICS_JWT_SECRET must be a secure key with at least 32 characters.")
        return v


settings = Settings()
