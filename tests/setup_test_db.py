"""Initialize isolated disposable test database."""
import asyncio
import os
import asyncpg
from alembic import command
from alembic.config import Config

async def ensure_test_database():
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", 5433))
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "analytics_dev_password")
    test_db = "analytics_test_db"

    conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database="postgres")
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", test_db)
    if not exists:
        print(f"Creating isolated test database: {test_db}")
        await conn.execute(f'CREATE DATABASE "{test_db}" OWNER "{user}";')
    await conn.close()

    # Apply extensions and roles to test database
    test_conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database=test_db)
    await test_conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    await test_conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    await test_conn.close()
    print("Test database verified.")

if __name__ == "__main__":
    asyncio.run(ensure_test_database())
