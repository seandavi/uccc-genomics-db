"""Saved cohorts in Postgres: revisions, history, revert, snapshots (docs/specs/36-*.md).

Persistence only; app.py validates definitions and runs counts. Every query is scoped to the
owner, and someone else's cohort is indistinguishable from a missing one (NotFound).
Postgres holds definitions, operations and suppressed snapshot results: no patient data.
`owner` is `authen.User.sub` (the caller passes it): `cohort.owner`, `snapshot.created_by` and
`cohort_version.created_by` hold the sub under `--auth authentik`, whatever the old backend returned
(email, `APP_USER`) before. The columns keep their names; README has the one-off UPDATE for old rows.
"""
import datetime
import os
import uuid

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

import uccc_genomics.config  # noqa: F401  loads the repo .env (DATABASE_URL)
from uccc_genomics_mcp.cohort import CountResult, Definition
from uccc_genomics_mcp.cohort import cohort_id as selecting_id

MAX_COHORTS = 100     # saved cohorts per owner
MAX_REVISIONS = 500   # revisions per cohort
MAX_SNAPSHOTS = 500   # snapshots per user

metadata = sa.MetaData()


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


# content-addressed, immutable, never deleted; the selecting part of a definition only
cohort_version = sa.Table(
    "cohort_version", metadata,
    sa.Column("cohort_id", sa.Text, primary_key=True),
    sa.Column("definition", JSONB, nullable=False),
    sa.Column("created_by", sa.Text, nullable=False),
    _created_at())

cohort = sa.Table(
    "cohort", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("owner", sa.Text, nullable=False, index=True),
    sa.Column("head", sa.Integer, nullable=False),
    _created_at(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

# the version chain; append-only
cohort_revision = sa.Table(
    "cohort_revision", metadata,
    sa.Column("cohort", sa.Uuid, sa.ForeignKey("cohort.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("seq", sa.Integer, primary_key=True),
    sa.Column("cohort_id", sa.Text, sa.ForeignKey("cohort_version.cohort_id"), nullable=False),
    sa.Column("definition", JSONB, nullable=False),
    sa.Column("op", JSONB, nullable=True),
    _created_at())

# grant feasibility records; append-only
snapshot = sa.Table(
    "snapshot", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("created_by", sa.Text, nullable=False, index=True),
    sa.Column("cohort_id", sa.Text, sa.ForeignKey("cohort_version.cohort_id"), nullable=False),
    sa.Column("definition", JSONB, nullable=False),
    sa.Column("data_date", sa.Date, nullable=False),
    sa.Column("result", JSONB, nullable=False),
    _created_at())


class NotFound(Exception): ...      # -> 404
class Conflict(Exception): ...      # -> 409 (head moved, or a MAX_* cap)
class Unavailable(Exception): ...   # -> 503 (no DATABASE_URL)


# --- response models -----------------------------------------------------------------------------

class Revision(BaseModel):
    seq: int
    cohort_id: str
    definition: Definition
    op: dict | None
    created_at: datetime.datetime


class SavedCohort(BaseModel):
    id: uuid.UUID
    head: Revision
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SavedList(BaseModel):
    cohorts: list[SavedCohort]          # most recently updated first


class History(BaseModel):
    revisions: list[Revision]           # seq ascending


class Snapshot(BaseModel):
    id: uuid.UUID
    cohort_id: str
    definition: Definition
    data_date: datetime.date
    result: CountResult
    created_at: datetime.datetime


class Snapshots(BaseModel):
    snapshots: list[Snapshot]           # newest first


class CohortVersion(BaseModel):
    cohort_id: str
    definition: Definition              # the selecting part only


class Deleted(BaseModel):
    id: uuid.UUID


# --- engine --------------------------------------------------------------------------------------

_engine: AsyncEngine | None = None


def database_url() -> URL | None:
    """DATABASE_URL as an asyncpg URL, or None when unset. Never print or log it."""
    raw = os.environ.get("DATABASE_URL")
    return make_url(raw).set(drivername="postgresql+asyncpg") if raw else None


def start(url: URL) -> None:
    global _engine
    _engine = create_async_engine(url, pool_pre_ping=True)


async def stop() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _begin():
    if _engine is None:
        raise Unavailable("saved cohorts are not configured on this server (DATABASE_URL)")
    return _engine.begin()


# --- helpers -------------------------------------------------------------------------------------

def _dump(d: Definition) -> dict:
    return d.model_dump(mode="json", by_alias=True)


def _selecting(d: Definition) -> Definition:
    """The part of d that selects patients; its cohort_id equals the cohort_id of d."""
    return Definition.model_validate(_dump(d) | {"name": "", "breakdown": [], "pivot": None})


async def _upsert_version(conn: AsyncConnection, d: Definition, cohort_id: str, owner: str) -> None:
    await conn.execute(insert(cohort_version).values(
        cohort_id=cohort_id, definition=_dump(_selecting(d)), created_by=owner).on_conflict_do_nothing())


def _revision(row) -> Revision:
    return Revision(seq=row.seq, cohort_id=row.cohort_id, definition=Definition.model_validate(row.definition),
                    op=row.op, created_at=row.created_at)


def _saved(row) -> SavedCohort:
    return SavedCohort(id=row.id, head=_revision(row), created_at=row.cohort_created_at, updated_at=row.updated_at)


def _with_head(owner: str):
    """SELECT of the owner's cohorts joined to their head revision."""
    return (sa.select(cohort.c.id, cohort.c.created_at.label("cohort_created_at"), cohort.c.updated_at,
                      cohort_revision.c.seq, cohort_revision.c.cohort_id, cohort_revision.c.definition,
                      cohort_revision.c.op, cohort_revision.c.created_at)
            .join_from(cohort, cohort_revision, sa.and_(cohort_revision.c.cohort == cohort.c.id,
                                                        cohort_revision.c.seq == cohort.c.head))
            .where(cohort.c.owner == owner))


async def _get(conn: AsyncConnection, owner: str, id: uuid.UUID) -> SavedCohort:
    row = (await conn.execute(_with_head(owner).where(cohort.c.id == id))).first()
    if row is None:
        raise NotFound(f"no saved cohort {id}")
    return _saved(row)


async def _lock_head(conn: AsyncConnection, owner: str, id: uuid.UUID) -> int:
    head = (await conn.execute(sa.select(cohort.c.head).where(cohort.c.id == id, cohort.c.owner == owner)
                               .with_for_update())).scalar()
    if head is None:
        raise NotFound(f"no saved cohort {id}")
    return head


async def _append(conn: AsyncConnection, owner: str, id: uuid.UUID, head: int, d: Definition,
                  op: dict) -> SavedCohort:
    """Add revision head + 1 to a cohort whose row this transaction has locked."""
    if head >= MAX_REVISIONS:
        raise Conflict(f"a saved cohort holds at most {MAX_REVISIONS} revisions")
    cid = selecting_id(d)
    await _upsert_version(conn, d, cid, owner)
    await conn.execute(sa.insert(cohort_revision).values(cohort=id, seq=head + 1, cohort_id=cid,
                                                         definition=_dump(d), op=op))
    await conn.execute(sa.update(cohort).where(cohort.c.id == id).values(head=head + 1, updated_at=sa.func.now()))
    return await _get(conn, owner, id)


# --- persistence ---------------------------------------------------------------------------------

async def create(owner: str, d: Definition) -> SavedCohort:
    async with _begin() as conn:
        n = await conn.scalar(sa.select(sa.func.count()).select_from(cohort).where(cohort.c.owner == owner))
        if n >= MAX_COHORTS:
            raise Conflict(f"at most {MAX_COHORTS} saved cohorts per user")
        cid = selecting_id(d)
        await _upsert_version(conn, d, cid, owner)
        id = uuid.uuid4()
        await conn.execute(sa.insert(cohort).values(id=id, owner=owner, head=1))
        await conn.execute(sa.insert(cohort_revision).values(cohort=id, seq=1, cohort_id=cid,
                                                             definition=_dump(d), op=None))
        return await _get(conn, owner, id)


async def list_cohorts(owner: str) -> SavedList:
    async with _begin() as conn:
        rows = (await conn.execute(_with_head(owner).order_by(cohort.c.updated_at.desc(), cohort.c.id))).all()
        return SavedList(cohorts=[_saved(r) for r in rows])


async def get(owner: str, id: uuid.UUID) -> SavedCohort:
    async with _begin() as conn:
        return await _get(conn, owner, id)


async def history(owner: str, id: uuid.UUID) -> History:
    async with _begin() as conn:
        await _get(conn, owner, id)   # ownership
        rows = (await conn.execute(sa.select(cohort_revision).where(cohort_revision.c.cohort == id)
                                   .order_by(cohort_revision.c.seq))).all()
        return History(revisions=[_revision(r) for r in rows])


async def append(owner: str, id: uuid.UUID, d: Definition, op: dict, after: int) -> SavedCohort:
    async with _begin() as conn:
        head = await _lock_head(conn, owner, id)
        if head != after:
            raise Conflict(f"saved cohort changed since revision {after}; reload it")
        return await _append(conn, owner, id, head, d, op)


async def revert(owner: str, id: uuid.UUID, to: int) -> SavedCohort:
    async with _begin() as conn:
        head = await _lock_head(conn, owner, id)
        target = (await conn.execute(sa.select(cohort_revision.c.definition).where(
            cohort_revision.c.cohort == id, cohort_revision.c.seq == to))).scalar()
        if target is None:
            raise NotFound(f"no revision {to}")
        return await _append(conn, owner, id, head, Definition.model_validate(target), {"op": "revert", "to": to})


async def delete(owner: str, id: uuid.UUID) -> Deleted:
    async with _begin() as conn:
        gone = (await conn.execute(sa.delete(cohort).where(cohort.c.id == id, cohort.c.owner == owner)
                                   .returning(cohort.c.id))).first()
        if gone is None:
            raise NotFound(f"no saved cohort {id}")
        return Deleted(id=id)


def _snapshot(row) -> Snapshot:
    return Snapshot(id=row.id, cohort_id=row.cohort_id, definition=Definition.model_validate(row.definition),
                    data_date=row.data_date, result=CountResult.model_validate(row.result), created_at=row.created_at)


async def add_snapshot(owner: str, d: Definition, data_date: datetime.date, result: CountResult) -> Snapshot:
    async with _begin() as conn:
        n = await conn.scalar(sa.select(sa.func.count()).select_from(snapshot).where(snapshot.c.created_by == owner))
        if n >= MAX_SNAPSHOTS:
            raise Conflict(f"at most {MAX_SNAPSHOTS} snapshots per user")
        await _upsert_version(conn, d, result.cohort_id, owner)
        row = (await conn.execute(sa.insert(snapshot).values(
            id=uuid.uuid4(), created_by=owner, cohort_id=result.cohort_id, definition=_dump(d), data_date=data_date,
            result=result.model_dump(mode="json")).returning(*snapshot.c))).one()
        return _snapshot(row)


async def list_snapshots(owner: str) -> Snapshots:
    async with _begin() as conn:
        rows = (await conn.execute(sa.select(snapshot).where(snapshot.c.created_by == owner)
                                   .order_by(snapshot.c.created_at.desc(), snapshot.c.id))).all()
        return Snapshots(snapshots=[_snapshot(r) for r in rows])


async def get_version(cohort_id: str) -> CohortVersion:
    async with _begin() as conn:
        d = (await conn.execute(sa.select(cohort_version.c.definition)
                                .where(cohort_version.c.cohort_id == cohort_id))).scalar()
        if d is None:
            raise NotFound(f"no cohort version {cohort_id}")
        return CohortVersion(cohort_id=cohort_id, definition=Definition.model_validate(d))
