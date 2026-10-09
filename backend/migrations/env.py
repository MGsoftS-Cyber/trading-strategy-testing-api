"""Versioned migrations use the same environment-selected database as the API."""

from alembic import context
from app.database import engine, Base
from app import models  # noqa: F401 — register the table metadata

if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
