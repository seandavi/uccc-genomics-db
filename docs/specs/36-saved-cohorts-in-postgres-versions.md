# Spec #36: saved cohorts in Postgres (versions, history, snapshots), over REST and MCP

Part of #23. `docs/ARCHITECTURE.md` decisions 2, 7 and 11. Builds on #34 (the cohort module) and
#35 (`genomics-app`, spec `docs/specs/35-genomics-app-fastapi-rest-and-mcp-over.md`). Label:
`review:security`.

All examples are synthetic. No real counts, ids or values appear.

## Goal

A logged-in user can save a cohort definition, edit it with operations (each edit makes a new
immutable revision), list and delete their saved cohorts, read the history, revert, snapshot it
for a grant feasibility statement, and resolve a shared `cohort_id` to its definition. Every one of
these works over REST (`/api/*`) and MCP (`/mcp`) in `genomics-app`, and one test sequence runs
through both surfaces and requires the same results. Storage is Postgres (SQLAlchemy async +
asyncpg, URL from `DATABASE_URL`), with Alembic migrations. Postgres holds definitions, operations
and suppressed snapshot results only: no patient data, no unsuppressed counts.

Done when a user can save, edit (via ops), list, revert and snapshot cohorts through REST and MCP,
with ownership enforced and tests green in CI (CI gets a throwaway Postgres service container).

## Non-goals

- No React app, no `/api/chat`, no MCP App.
- The per-query audit log stays one JSON line on stdout (#35). ARCHITECTURE decision 7 also names
  the audit log for Postgres; moving it is a later issue. The in-process rate limiter is unchanged
  (its `ponytail:` comment still names Postgres or Redis as the upgrade path).
- No sharing between users beyond `cohort_id`: no shared or team cohorts, no transfer of ownership.
  A recipient resolves the `cohort_id` to its definition and saves their own copy.
- No snapshot deletion or editing. Snapshots are append-only grant records.
- No change to `genomics-cohort-api`, `genomics-mcp`, `authen.py`, the cohort module's logic,
  suppression, SQL or the mart. The cohort module gains one function, `data_date()`.
- `GET /api/health` does not check Postgres.
- No provisioning of the production database or role, no systemd unit and no deploy. Creating the
  database on the host's shared cluster, putting `DATABASE_URL` in `.env` and running the
  migration are a `needs:human` step after merge (README text below).
- No data change in the de-id file: no schema, table or column is added there, and
  `research_id` / `report_id` are untouched and never stored in Postgres.

## Design

### Files

| File | Change |
|---|---|
| `mcp/src/uccc_genomics_mcp/saved.py` | **new**: tables (SQLAlchemy Core), response models, errors, engine start/stop, the async persistence functions |
| `mcp/src/uccc_genomics_mcp/migrations/env.py` | **new**: Alembic env, online only, async |
| `mcp/src/uccc_genomics_mcp/migrations/script.py.mako` | **new**: copy of Alembic 1.20's `templates/async/script.py.mako` |
| `mcp/src/uccc_genomics_mcp/migrations/versions/0001_saved_cohorts.py` | **new**: the four tables, hand-written, `revision = "0001"`, `down_revision = None` |
| `mcp/alembic.ini` | **new**: `[alembic]` with `script_location = %(here)s/src/uccc_genomics_mcp/migrations` only. No `sqlalchemy.url` and no logging sections (no credentials in files) |
| `mcp/src/uccc_genomics_mcp/app.py` | saved-cohort models in REST and MCP, shared calls, exception handlers, engine in the lifespan, `INSTRUCTIONS` sentence |
| `mcp/src/uccc_genomics_mcp/cohort/queries.py`, `cohort/__init__.py` | add and re-export `data_date()` |
| `mcp/pyproject.toml`, `uv.lock` | two dependencies (below); `uv lock` |
| `.github/workflows/ci.yml` | Postgres service container and `TEST_DATABASE_URL` for the `pytest` job |
| `tests/test_saved.py` | **new**: the tests below |
| `tests/test_app.py` | tool list, gated routes, `DATABASE_URL` removed in the `client` fixture, 503 test |
| `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `dashboard/COHORT_DISCOVERY.md`, `mcp/README.md`, `.env.example` | as listed under "Docs" |

### Dependencies

`mcp/pyproject.toml` `dependencies` gains `"sqlalchemy[postgresql-asyncpg]>=2.1"` and
`"alembic>=1.20"`. The issue and ARCHITECTURE decision 7 name SQLAlchemy async, asyncpg and Alembic,
which settles "ask before adding". Checked on PyPI on 2026-10-25: SQLAlchemy 2.1.6 (requires
`typing-extensions`; the `postgresql-asyncpg` extra pulls `asyncpg` and `greenlet`, which 2.1 no
longer installs by default), asyncpg 0.32.0 (cp312 wheels), alembic 1.20.1 (requires `SQLAlchemy>=2.0`,
`Mako`, `typing-extensions`). No test-only dependency: tests use a Postgres given by URL, not
testcontainers.

Verified with throwaway probes (outside the repo, against a `postgres:17` container that was then
removed) on these versions plus the locked `mcp` 2.1.1 / fastapi 0.162.0:

- `create_async_engine(make_url("postgresql://...").set(drivername="postgresql+asyncpg"))` works,
  with `JSONB`, `sa.Uuid`, `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_nothing()`
  (rowcount 1 then 0) and `select(...).with_for_update()`.
- An Alembic `env.py` that runs `asyncio.run(...)` around `connection.run_sync(do_run_migrations)`
  works from `alembic.command.upgrade/downgrade/check(Config(...), ...)` called in sync code.
  `command.check` passes when the hand-written migration matches the metadata.
- `async def` MCP tools and `async def` FastAPI routes both run on the loop that runs the FastAPI
  lifespan, so an engine created in the lifespan serves both. Two `TestClient`s in a row (two
  event loops) work when each lifespan creates and disposes its own engine. A module-level
  engine reused across loops would not, which is why the engine lives in the lifespan.
- An `async def` MCP tool taking `id: uuid.UUID` gets `{"type": "string", "format": "uuid"}` in its
  input schema and an `isError` result for a malformed id. A model with `uuid.UUID`, a tz-aware
  `datetime` and `None` fields gives the same JSON from FastAPI and in MCP `structuredContent`.

### Schema (Postgres, Alembic revision `0001`)

No column comes from a vendor field: everything stored is a cohort definition (#34's model), an
operation, a user's login name or email from `authen`, timestamps, or a suppressed `CountResult`.

```
cohort_version            content-addressed, immutable, never deleted
  cohort_id   text        PK          cohort.cohort_id(d), e.g. "v1-0123456789abcdef"
  definition  jsonb       not null    the selecting part of d: name "", breakdown [], pivot null
  created_by  text        not null    first user to store it; never returned by any endpoint
  created_at  timestamptz not null    default now()

cohort                    one row per saved cohort
  id          uuid        PK          uuid.uuid4() in Python
  owner       text        not null    authen email; index ix_cohort_owner
  head        integer     not null    seq of the current revision
  created_at  timestamptz not null    default now()
  updated_at  timestamptz not null    default now(); set to now() on every new revision

cohort_revision           the version chain; append-only
  cohort      uuid        not null    FK cohort.id ON DELETE CASCADE
  seq         integer     not null    1, 2, 3, ... per cohort;  PK (cohort, seq)
  cohort_id   text        not null    FK cohort_version.cohort_id
  definition  jsonb       not null    the full definition (name, breakdown, pivot included)
  op          jsonb       null        null for seq 1; the Operation applied; {"op": "revert", "to": n}
  created_at  timestamptz not null    default now()

snapshot                  grant feasibility records; append-only
  id          uuid        PK          uuid.uuid4() in Python
  created_by  text        not null    authen email; index ix_snapshot_created_by
  cohort_id   text        not null    FK cohort_version.cohort_id
  definition  jsonb       not null    the full definition counted (its breakdowns shape result)
  data_date   date        not null    cohort.data_date() when the count ran
  result      jsonb       not null    the CountResult exactly as returned to the user (suppressed)
  created_at  timestamptz not null    default now()
```

Column types in SQLAlchemy: `sa.Text`, `JSONB` (`sqlalchemy.dialects.postgresql`), `sa.Uuid`,
`sa.Integer`, `sa.Date`, `sa.DateTime(timezone=True)`; `server_default=sa.func.now()` on every
`created_at`/`updated_at`. Indexes are declared with `index=True` on the column, so their names are
`ix_cohort_owner` and `ix_snapshot_created_by`, and the migration creates them with those names.
There is no FK from `cohort.head` to `cohort_revision` (it would be circular); the head is written
in the same transaction as its revision and only by `saved.py`.

**Deviations from the issue text, and why:**

- `cohort.head` is a revision number, not a `cohort_id`, and the chain lives in its own
  `cohort_revision` table. `cohort_id` (#34) covers only what selects patients, not `name`,
  `breakdown` or `pivot`, so a rename or a new breakdown keeps the same `cohort_id`. Keyed on
  `cohort_id`, history would lose those edits, and A → B → A would loop.
- No `parent` column. Revert appends a copy of the target revision, so history is linear and the
  parent of revision n is always n − 1.
- No `cohort.name` column. The name is the head definition's `name` (one place); rename is the
  `rename` operation, which makes a revision like any other edit.
- `cohort_version.definition` is the selecting part only (`name` "", `breakdown` [], `pivot` null).
  It is what anyone holding the `cohort_id` may read, so it carries neither the first saver's name
  nor their view settings.

### `saved.py`

```python
"""Saved cohorts in Postgres: revisions, history, revert, snapshots (docs/specs/36-*.md).

Persistence only; app.py validates definitions and runs counts. Every query is scoped to the
owner, and someone else's cohort is indistinguishable from a missing one (NotFound).
"""
import uccc_genomics.config  # noqa: F401  loads the repo .env (DATABASE_URL)

MAX_COHORTS = 100     # saved cohorts per owner
MAX_REVISIONS = 500   # revisions per cohort
MAX_SNAPSHOTS = 500   # snapshots per user

metadata = sa.MetaData()
cohort_version: sa.Table; cohort: sa.Table; cohort_revision: sa.Table; snapshot: sa.Table   # as above

class NotFound(Exception): ...      # -> 404
class Conflict(Exception): ...      # -> 409 (head moved, or a MAX_* cap)
class Unavailable(Exception): ...   # -> 503 (no DATABASE_URL)

def database_url() -> sqlalchemy.engine.URL | None
def start(url: sqlalchemy.engine.URL) -> None
async def stop() -> None
```

- `database_url()`: `None` when `DATABASE_URL` is unset or empty, else
  `make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg")`, so a standard
  `postgresql://user:pass@host:5432/db` URI works. Never print or log the URL.
- `start()` sets the module's `_engine = create_async_engine(url, pool_pre_ping=True)`; `stop()`
  disposes it and sets `_engine = None` (a no-op when not started). Every function below raises
  `Unavailable("saved cohorts are not configured on this server (DATABASE_URL)")` when `_engine` is
  `None`, and runs in one `async with _engine.begin() as conn:` transaction.

Response models (Pydantic, in `saved.py`; `Definition` and `CountResult` from `cohort`):

```python
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
```

Lists are wrapped in a model so REST and MCP `structuredContent` are the same object. Definitions
go into JSONB as `d.model_dump(mode="json", by_alias=True)` and come back with
`Definition.model_validate(...)`; results likewise with `CountResult`.

Functions (all `async`, all take the owner's email first where ownership applies):

| Function | Does |
|---|---|
| `create(email, d: Definition) -> SavedCohort` | `Conflict` if the owner has `MAX_COHORTS`. Upserts `cohort_version` (`on_conflict_do_nothing`, selecting part of `d`, `created_by=email`), inserts `cohort` (head 1) and revision 1 (`op` null). |
| `list_cohorts(email) -> SavedList` | the owner's cohorts joined to their head revision, `updated_at` desc |
| `get(email, id: uuid.UUID) -> SavedCohort` | `NotFound(f"no saved cohort {id}")` unless it exists **and** `owner = email` |
| `history(email, id) -> History` | every revision of an owned cohort; `NotFound` as above |
| `append(email, id, d: Definition, op: dict, after: int) -> SavedCohort` | `SELECT head ... WHERE id = :id AND owner = :email FOR UPDATE`; `NotFound`; `Conflict("saved cohort changed since revision {after}; reload it")` if `head != after`; `Conflict` at `MAX_REVISIONS`; upserts `cohort_version`, inserts revision `head + 1`, sets `head` and `updated_at` |
| `revert(email, id, to: int) -> SavedCohort` | locks the cohort row as `append` does; `NotFound(f"no revision {to}")` if absent; appends a copy of revision `to`'s definition with `op = {"op": "revert", "to": to}`. Reverting to the head is allowed (a no-op revision). Undo is `revert` to `head - 1`. |
| `delete(email, id) -> Deleted` | `DELETE ... WHERE id AND owner`; `NotFound` if no row; revisions cascade; `cohort_version` and snapshots stay |
| `add_snapshot(email, d, data_date, result: CountResult) -> Snapshot` | `Conflict` at `MAX_SNAPSHOTS`; upserts `cohort_version`; inserts the row with `cohort_id=result.cohort_id` |
| `list_snapshots(email) -> Snapshots` | `WHERE created_by = email`, newest first |
| `get_version(cohort_id: str) -> CohortVersion` | any logged-in user; `NotFound(f"no cohort version {cohort_id}")`; `created_by` is not returned |

The selecting part is `Definition.model_validate(d.model_dump(mode="json", by_alias=True) |
{"name": "", "breakdown": [], "pivot": None})`; its `cohort_id` equals `cohort_id(d)`. Every value
reaches SQL as a bound parameter through SQLAlchemy Core; no SQL text is built from input.

### `cohort.data_date()`

In `cohort/queries.py`, re-exported from `cohort/__init__.py` (import and `__all__`):

```python
def data_date() -> datetime.date:
    """The local date the daily rebuild last wrote the de-id file (its mtime): a snapshot's data date."""
    return datetime.date.fromtimestamp(os.path.getmtime(DEID_DB))
```

It reads the module-level `DEID_DB`, which `test_cohort.use_mart` already monkeypatches to the
synthetic mart.

### `app.py`

Lifespan becomes:

```python
async def lifespan(_):
    url = saved.database_url()
    if url is not None:
        saved.start(url)
    try:
        async with manager.run():
            yield
    finally:
        await saved.stop()
```

Without `DATABASE_URL` the app still serves everything from #35; the saved-cohort routes and tools
answer 503 / `isError` with the `Unavailable` message.

Request bodies:

```python
class SavedApplyRequest(BaseModel):
    op: Operation

class RevertRequest(BaseModel):
    to: int = Field(ge=1)
```

Shared calls (async; REST routes and MCP tools both call these and add only transport and error
mapping, as in #35):

```python
async def run_save(email: str, d: Definition) -> SavedCohort:
    await run_in_threadpool(lambda: cohort.vocabulary().check(d))      # DefinitionError -> 400
    return await saved.create(email, d)

async def run_saved_apply(email: str, id: uuid.UUID, op: Operation) -> SavedCohort:
    c = await saved.get(email, id)
    new = await run_in_threadpool(cohort.apply, c.head.definition, op, cohort.vocabulary())
    return await saved.append(email, id, new, op.model_dump(mode="json", by_alias=True), after=c.head.seq)

async def run_snapshot(email: str, surface: Surface, id: uuid.UUID) -> Snapshot:
    c = await saved.get(email, id)
    day = cohort.data_date()
    result = await run_in_threadpool(run_count, email, surface, c.head.definition)   # rate-limited + audited
    return await saved.add_snapshot(email, c.head.definition, day, result)
```

`cohort.vocabulary()` must be called inside the threadpool (it may open DuckDB): in
`run_saved_apply` use `run_in_threadpool(lambda: cohort.apply(c.head.definition, op,
cohort.vocabulary()))`. The other operations call `saved.*` directly. No DuckDB work happens inside
a Postgres transaction: `run_saved_apply` reads the head, validates outside any transaction, then
writes with `after=` so a concurrent edit gives `Conflict` instead of a lost update.

REST routes (`async def`, each takes `email: str = Depends(user)`; errors `{"detail": ...}`):

| Route | Body | Response | Errors |
|---|---|---|---|
| `POST /api/saved` | `Definition` | `SavedCohort` | 400 `DefinitionError`, 409 cap, 422, 503 |
| `GET /api/saved` | none | `SavedList` | 503 |
| `GET /api/saved/{id}` | none | `SavedCohort` | 404, 422 (bad uuid), 503 |
| `POST /api/saved/{id}/apply` | `SavedApplyRequest` | `SavedCohort` | 400, 404, 409, 422, 503 |
| `GET /api/saved/{id}/history` | none | `History` | 404, 422, 503 |
| `POST /api/saved/{id}/revert` | `RevertRequest` | `SavedCohort` | 404, 409, 422, 503 |
| `POST /api/saved/{id}/snapshot` | none | `Snapshot` | 400, 404, 409, 429 with `Retry-After`, 503 |
| `DELETE /api/saved/{id}` | none | `Deleted` (200) | 404, 422, 503 |
| `GET /api/snapshots` | none | `Snapshots` | 503 |
| `GET /api/versions/{cohort_id}` | none | `CohortVersion` | 404, 503 |

`{id}` is typed `uuid.UUID`. New exception handlers: `saved.NotFound` → 404, `saved.Conflict` →
409, `saved.Unavailable` → 503, each `{"detail": str(e)}`. `RequireUser` already gates every new
path (fail closed).

MCP tools (`async def`, `@mcp_app.tool()`, each calls `_mcp_user(ctx)` first, and maps
`DefinitionError`, `RateLimited`, `saved.NotFound`, `saved.Conflict` and `saved.Unavailable` to
`ToolError(str(e))`; define the tuple once as `TOOL_ERRORS` and reuse it in `count` and `pivot`):

| Tool | Signature | Returns | Same as |
|---|---|---|---|
| `save_cohort` | `(definition: Definition, ctx)` | `SavedCohort` | `POST /api/saved` |
| `list_saved_cohorts` | `(ctx)` | `SavedList` | `GET /api/saved` |
| `get_saved_cohort` | `(id: uuid.UUID, ctx)` | `SavedCohort` | `GET /api/saved/{id}` |
| `apply_saved_op` | `(id: uuid.UUID, op: Operation, ctx)` | `SavedCohort` | `POST /api/saved/{id}/apply` |
| `saved_cohort_history` | `(id: uuid.UUID, ctx)` | `History` | `GET /api/saved/{id}/history` |
| `revert_saved_cohort` | `(id: uuid.UUID, to: Annotated[int, Field(ge=1)], ctx)` | `SavedCohort` | `POST /api/saved/{id}/revert` |
| `snapshot_saved_cohort` | `(id: uuid.UUID, ctx)` | `Snapshot` | `POST /api/saved/{id}/snapshot` |
| `delete_saved_cohort` | `(id: uuid.UUID, ctx)` | `Deleted` | `DELETE /api/saved/{id}` |
| `list_snapshots` | `(ctx)` | `Snapshots` | `GET /api/snapshots` |
| `get_cohort_version` | `(cohort_id: str, ctx)` | `CohortVersion` | `GET /api/versions/{cohort_id}` |

Docstrings say in a sentence or two what each answers. `INSTRUCTIONS` gains: "Saved cohorts belong
to the logged-in user: save_cohort, then edit with apply_saved_op (each edit is a new revision;
revert_saved_cohort undoes). Saved cohorts hold no counts; count the head definition. Snapshots
store the suppressed count with its data date for grant text."

### Migrations

`migrations/env.py` (online only; no offline branch):

```python
import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
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
```

Operator command (host, after a person has created the database): `uv run alembic -c
mcp/alembic.ini upgrade head`. The app never migrates on start; it expects the schema at head.

### CI

In `.github/workflows/ci.yml`, job `pytest` gains:

```yaml
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
```

This is a throwaway container that lives for one job; its password is not a credential for
anything else.

### What leaves the host, and the small-cell rule

- Postgres stores no patient data and no unsuppressed number. Definitions hold only vocabulary
  values (checked against the floored vocabulary on save and on every apply), fixed cut points and
  the user's own name text. `op` holds the same. `snapshot.result` is the `CountResult` returned by
  `run_count`, which is `cohort.count` behind `suppress.py` (floor 5, secondary suppression, floored
  funnel deltas, the whole-cohort rule, `loosen[]` clearance). It is stored as returned and never
  recomputed or post-processed. No `research_id`, `report_id` or row-level value is ever written.
- Ordinary saved cohorts store no counts. Counting a saved cohort is a normal `count`/`pivot` call
  on its head definition, so it is rate-limited, audited and recomputed against today's data
  (decision 7).
- A snapshot runs `run_count`, so it is rate-limited (it shares the 60-a-minute budget) and audited
  like any count. It returns nothing a `count` call would not.
- Responses carry definitions, revision metadata, timestamps, ids and suppressed snapshot results.
  `GET /api/versions/{cohort_id}` returns the selecting part of a definition and nothing about who
  stored it.
- Ownership: every read and write of `cohort`, `cohort_revision` and `snapshot` is filtered by the
  email `RequireUser` stored. Someone else's id gives the same 404 as a missing one, so ids cannot be
  probed for existence. Ids are random UUIDs.
- Differencing (decision 11): saved cohorts make repeated queries convenient but add no new
  count path. Every count still goes through the rate limit and the audit log. The caps
  (`MAX_*`) bound storage per user.

`research_id` and `report_id` stability is not affected: nothing here touches `deid.py` or reads
either id.

### Docs

- `README.md`, under "Cohort app (genomics-app)", a "Saved cohorts" paragraph: the tables, that
  `DATABASE_URL` (in `.env`, a standard `postgresql://` URI) turns them on, the routes and tools in
  one line each, and:

  ```
  # once, by a person, on the host's shared cluster: create a database and role for the app, then
  uv run alembic -c mcp/alembic.ini upgrade head
  # tests: a throwaway Postgres (CI uses a service container)
  docker run --rm -d --name genomics-test-pg -e POSTGRES_PASSWORD=test -p 127.0.0.1:55432:5432 postgres:17
  TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/postgres uv run pytest -q
  docker rm -f genomics-test-pg
  ```
  and that without `TEST_DATABASE_URL` the Postgres tests skip with a message.
- `AGENTS.md`: Layout lines `saved.py  saved cohorts in Postgres (SQLAlchemy async): revisions,
  snapshots; migrations/ is Alembic (mcp/alembic.ini)`; in Commands, the `TEST_DATABASE_URL` test
  line; in the CI sentence, that CI runs a Postgres service container. Rules: "`TEST_DATABASE_URL`
  must point at a throwaway Postgres: the tests drop and recreate the schema."
- `docs/ARCHITECTURE.md` decision 7: name the tables, Alembic, `DATABASE_URL`, #36, and that the
  query audit log stays on stdout for now.
- `dashboard/COHORT_DISCOVERY.md` §3.3 "Versions": versions are server-side saved-cohort revisions
  (#36), not local storage; a share link carries the `cohort_id`, which the recipient resolves and
  counts under their own login.
- `mcp/README.md`: the saved-cohort tools are served by `genomics-app`.
- `.env.example`: a commented placeholder line
  `# DATABASE_URL=postgresql://<role>:<password>@<host>:5432/<database>   # secret: real value only in .env`.

## Acceptance criteria

- [ ] `mcp/pyproject.toml` lists `sqlalchemy[postgresql-asyncpg]>=2.1` and `alembic>=1.20`;
      `uv lock` has been run and `uv sync --locked` passes.
- [ ] `uv run alembic -c mcp/alembic.ini upgrade head` against an empty Postgres creates exactly
      `cohort_version`, `cohort`, `cohort_revision`, `snapshot` (plus `alembic_version`) with the
      columns above; `downgrade base` removes them; `alembic check` reports no difference between
      the migration and `saved.metadata`.
- [ ] The ten REST routes and ten MCP tools exist with the bodies, responses and status codes
      above. `tools/list` returns the five #35 tools plus these ten, and still no `query`.
- [ ] Parity: the same script of saves, applies, reverts, history, list, snapshot and delete gives
      the same JSON on both surfaces once UUIDs and timestamps are masked. Reads of one cohort
      (get, history, list, snapshots, version) give identical JSON on both surfaces unmasked.
- [ ] Revisions: create gives seq 1 with `op` null; each apply adds seq + 1 with the operation as
      `op`; rename keeps `cohort_id` and changes `head.definition.name`; adding a criterion changes
      `cohort_id`; revert to n adds a revision whose definition equals revision n's and whose `op`
      is `{"op": "revert", "to": n}`. History is never rewritten.
- [ ] Ownership: user B gets 404 / `isError` "no saved cohort" for get, apply, history, revert,
      snapshot and delete of user A's cohort, on both surfaces; B's list and snapshot list do not
      show A's; A's cohort is unchanged afterwards. B can read A's `cohort_id` through
      `GET /api/versions/{cohort_id}` and save their own copy.
- [ ] `cohort_version.definition` has `name` "", `breakdown` [] and `pivot` null, and the version
      response has no `created_by`. Two users saving the same selecting definition under different
      names make one `cohort_version` row.
- [ ] Snapshot: `result` equals what `POST /api/cohort` returns for the head definition; `data_date`
      equals `cohort.data_date()`; the snapshot writes one audit line; it is refused with 429 /
      "rate limit" when the budget is spent, and then no row is stored.
- [ ] No count from 1 to 4 under `patients`, `denominator` or `reports` in any response, and no
      synthetic `research_id` or `report_id` in any response or in any Postgres row. `cohort`,
      `cohort_revision` and `cohort_version` rows contain no `patients`, `denominator` or `reports`
      key.
- [ ] Caps: with `MAX_COHORTS`, `MAX_REVISIONS` and `MAX_SNAPSHOTS` set to 1–2 in a test, the next
      write is 409. A stale `after` in `saved.append` raises `Conflict`.
- [ ] Without `DATABASE_URL`, `genomics-app` starts and serves the #35 surface; the saved routes
      answer 503 and the saved tools `isError`, both with the "not configured" message. Without
      credentials the new routes are 401.
- [ ] Without `TEST_DATABASE_URL`, `uv run pytest -q` passes with the Postgres tests skipped and a
      message naming `TEST_DATABASE_URL`; with it (CI, or a local container), they run and pass.
      Dashboard check: n/a (only `COHORT_DISCOVERY.md` changes under `dashboard/`).
- [ ] README, AGENTS.md, ARCHITECTURE.md, COHORT_DISCOVERY.md, mcp/README.md and `.env.example`
      are updated as listed under "Docs".

## Test plan

`tests/test_saved.py`. Synthetic only: the #34 mart in a temp dir (via the same fixtures pattern as
`tests/test_app.py`) and a throwaway Postgres given by `TEST_DATABASE_URL`. No network beyond
that Postgres, never `$DATA/raw`, the PHI file, the real de-id file or the real `DATABASE_URL`.

Fixtures:

- `pg_url` (module scope): `url = os.environ.get("TEST_DATABASE_URL")`; if unset,
  `pytest.skip("saved cohorts: set TEST_DATABASE_URL to a throwaway Postgres to run these (README)")`.
  If it equals `os.environ.get("DATABASE_URL")`, `pytest.fail` (the tests drop the schema). With
  `pytest.MonkeyPatch.context()` setting `DATABASE_URL=url`, run
  `command.downgrade(cfg, "base")`, `command.upgrade(cfg, "head")` and `command.check(cfg)`, where
  `cfg = alembic.config.Config(str(REPO / "mcp" / "alembic.ini"))`.
- `ids`: import from `test_app` (mart, `use_mart`, `app.get_db`, fresh `_calls`), as `test_app`
  does for its own tests.
- `sclient` (function scope): `monkeypatch.setenv("DATABASE_URL", pg_url)`; truncate all four tables
  with `asyncio.run(...)` on a short-lived `create_async_engine(saved.database_url())` (`TRUNCATE
  snapshot, cohort_revision, cohort, cohort_version`); `monkeypatch.setattr(authen, "user", fake)`
  where `fake(request)` returns `request.headers["x-test-user"]` or raises `PermissionError`; then
  `with TestClient(app.app()) as c: yield c`.
- Helpers `rest(c, method, path, body=None, user="a@x.edu")` and `tool(c, name, args,
  user="a@x.edu")` (the `tools/call` POST with `x-test-user`), and `mask(x)`, which replaces every
  string matching a UUID or an ISO-8601 timestamp with `"*"`, recursively.

Tests:

1. `test_saved_parity`: one script, run once through REST and once through MCP (each surface
   creates its own cohort from `{"name": "x", "population": {"oncotree": ["NSCLC"]}}`): save; apply
   `add_criterion` KRAS G12C; apply `rename`; apply `set_breakdown ["sex"]`; revert to 1; history;
   get; snapshot; list snapshots; delete; list. `mask(rest_response) == mask(mcp_response)` at
   every step.
2. `test_saved_reads_are_identical`: create through REST, then get, history, list, list snapshots
   (after one snapshot) and version on both surfaces; exact equality.
3. `test_revisions`: the seq, `op`, `cohort_id` and name rules in the acceptance list.
4. `test_ownership`: the B-against-A matrix on both surfaces, A unchanged after; B resolves A's
   `cohort_id` and saves a copy, which gets its own id.
5. `test_cohort_version_is_content_addressed`: two users, same selecting definition, different
   names and breakdowns: one row, selecting part only, no `created_by` in the response; unknown
   `cohort_id` 404 / `isError`.
6. `test_snapshot`: result equals `POST /api/cohort` for the head; `data_date ==
   cohort.data_date()`; one audit line (`capsys`); a cohort under the floor still stores only
   suppressed values; with `app.RATE_LIMIT` at 1 and the budget spent, 429 / `isError` and the
   snapshot list is unchanged.
7. `test_nothing_small_or_identifying_stored`: after tests 1–6's kind of script, read every row of
   all four tables with a raw engine; no `research_id`/`report_id` string from `ids`, no
   `patients`/`denominator`/`reports` keys outside `snapshot.result`, and no 1–4 under those keys
   anywhere.
8. `test_errors_agree`: unknown id (404, "no saved cohort"), malformed id (422 / `isError`),
   gene not in the vocabulary on save and on apply (400, "gene"), unknown op (422, "op"), revert to
   99 (404, "no revision"). REST status and MCP `isError` text both name the problem.
9. `test_caps_and_conflict`: monkeypatch `saved.MAX_COHORTS`, `MAX_REVISIONS`, `MAX_SNAPSHOTS` to
   small values; next write 409 / `isError`. Then, inside one `asyncio.run`, `saved.start(url)`,
   `create`, `append(..., after=1)` succeeds, `append(..., after=1)` again raises `Conflict`,
   `await saved.stop()`.
10. `test_delete`: get, history and apply 404 afterwards; earlier snapshots and the
    `cohort_version` row remain.
11. `test_database_url` (no Postgres needed, not using `pg_url`): unset → `None`;
    `postgresql://u:p@h:5432/d` → drivername `postgresql+asyncpg`, same host, port, database.

`tests/test_app.py` changes (run everywhere, no Postgres):

- `client` fixture: `monkeypatch.delenv("DATABASE_URL", raising=False)` before building the app, so
  a `DATABASE_URL` in the host `.env` is never touched by these tests.
- `test_tools_list`: the expected set is the five #35 tools plus the ten above.
- `GATED` adds `("POST", "/api/saved")`, `("GET", "/api/saved")`, `("GET", "/api/snapshots")`,
  `("GET", "/api/versions/v1-0000000000000000")`.
- New `test_saved_unconfigured`: `POST /api/saved` with `{}` is 503 with "not configured", and
  `list_saved_cohorts` over MCP is `isError` with the same text.

Run: `uv run pytest -q` (Postgres tests skip), and with a local throwaway container as in the README
text (they run). The implementer runs both and reports both; the container is removed afterwards.
Dashboard check: n/a.

## Risks

- **Ownership is the security boundary.** A query that forgets `owner = :email` leaks another
  user's definitions. Mitigation: ownership checks sit in `saved.py` only (one place), and
  `test_ownership` runs every id-taking operation as the wrong user on both surfaces.
- **Free text in names.** A user could type something identifying into a cohort name. Postgres
  would then hold it, readable only by that user (version rows store `name` ""). Out of scope; the
  same is true of the stdout audit log today.
- **Snapshot data date.** `data_date()` is read just before the count. If the daily rebuild
  replaces the file in between, the date can be one day early. The rebuild runs once a day at a
  fixed time, so this is rare and only off by a day.
- **Schema drift.** The app expects the schema at head and does not migrate on start. A deploy
  that skips `alembic upgrade head` fails on the first saved-cohort call (500), not silently.
  `alembic check` in the tests keeps the migration and the models in step.
- **Definition versioning.** Stored definitions are `version: 1`. A future `version: 2` model must
  read or migrate old rows; `parse` would otherwise reject them. Out of scope until a v2 exists.
- **Destructive test fixture.** The Postgres tests drop and recreate the schema in
  `TEST_DATABASE_URL`. The fixture refuses a URL equal to `DATABASE_URL`, and the README and
  AGENTS.md say to use a throwaway container. A wrong URL that differs from `DATABASE_URL` would
  still be wiped.
- **New dependencies** (SQLAlchemy, asyncpg, greenlet, Alembic, Mako), decided by the issue and
  ARCHITECTURE decision 7.
