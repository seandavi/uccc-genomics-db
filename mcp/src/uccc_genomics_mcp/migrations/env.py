"""Alembic environment: online only, async. The URL comes from DATABASE_URL (docs/specs/36-*.md)."""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from uccc_genomics_mcp import broker, terms  # noqa: F401  registers the broker and terms tables on saved.metadata
from uccc_genomics_mcp import saved


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=saved.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run():
    url = saved.database_url()
    if url is None:
        raise SystemExit("set DATABASE_URL (in .env) to run migrations")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


asyncio.run(run())
