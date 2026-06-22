"""Alembic environment configuration for CarbonSense.

Reads DATABASE_URL from environment, falling back to alembic.ini.
Supports both online (direct connection) and offline (SQL generation) modes.

For dedicated-schema tenants, set ALEMBIC_SCHEMA to the target schema name
(e.g. "tenant_abc123"). Alembic will SET search_path before running
migrations so the identical DDL lands in the tenant's schema rather than
public. See TRD v2.0 §2.1.
"""

import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_schema = os.environ.get("ALEMBIC_SCHEMA")
if target_schema and not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", target_schema):
    raise ValueError(f"ALEMBIC_SCHEMA contains unsafe characters: {target_schema!r}")


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database.

    When ALEMBIC_SCHEMA is set, migrations run inside that schema
    (for dedicated-schema tenant provisioning).
    """
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if target_schema:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {target_schema}"))
            connection.execute(text(f"SET search_path TO {target_schema}"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema=target_schema,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
