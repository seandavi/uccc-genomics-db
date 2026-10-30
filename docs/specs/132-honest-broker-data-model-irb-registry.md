# #132 Honest broker: data model, IRB registry and snapshot ids

Design record: `docs/HONEST_BROKER.md` (Sean's decisions at the top). Part of #16. Follow-on issues
build on this: #133 requester flow, #134 review queue, #135 fulfillment, #136 expiry and closeout.

## Goal

1. Every de-id build gets an id (`meta.build.build_id` in `genomics.duckdb`) that the app reads as
   `snapshot_id`.
2. Every saved-cohort revision records the `snapshot_id` it was saved against, and a revision that a
   request references can't be deleted.
3. Postgres gets the honest-broker tables from the design's data model (`irb_authorization`,
   `irb_document`, `irb_personnel`, `request`, `review`, `release`, `release_patient`) in an
   Alembic migration (`0002`) with a working downgrade.
4. Read-only REST + MCP endpoints: a requester reads their own requests, and a member of the Authentik
   group `uccc-genomics-broker` reads all requests and the IRB registry. Membership comes from the
   `groups` claim, never from an email address.

Identified data never enters Postgres. The tables hold study ids (`research_id`) only, never
MRNs, names or dates of birth.

## Non-goals

- Write endpoints of any kind: creating or editing requests and the intake (#133), recording a review
  (#134), recording a release and its `release_patient` rows (#135), closeout (#136). In this issue
  rows come only from tests (and later from those issues).
- The requester-facing IRB lookup/autocomplete (#133). Here the IRB registry is readable by brokers only.
- Any endpoint that returns `release_patient` rows (disclosure-accounting search is #136).
- Any UI in Discover. `web/` changes only by regenerating `openapi.json`/`api.gen.ts`.
- Expiry flags and computed `expired` fields (#136). The terms gate (#131).
- Grant id and trial id from the #16 comment. They aren't in the design's data model, so #133 can add
  them with the intake if Sean wants them.
- A content hash of the build. `build_id` is unique per build, not per data content (see Risks).
- Touching the PHI file, `deid`'s hashing, date shifting or the leak check's patterns.

## Design

### 1. Build id in the de-id file (`src/uccc_genomics/deid.py`)

```python
import datetime, secrets

def new_build_id() -> str:
    """UTC build time plus 8 random hex digits, e.g. '20261030T061502Z-3fa9c2d1': unique per build."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
```

In `build(path)`, after `mart.sql` and **before** the leak check:

```python
build_id = new_build_id()
con.execute("CREATE SCHEMA meta")
con.execute("CREATE TABLE meta.build AS SELECT ?::VARCHAR AS build_id", [build_id])
print("meta.build", build_id)
```

- One row, one column: `meta.build(build_id VARCHAR)`. There is no `built_at` column because the id
  already carries the UTC time. A `TIMESTAMPTZ` column would also need `pytz` to fetch from the duckdb
  Python client, and `pytz` isn't installed (checked).
- Pass `[*present, "mart", "meta"]` to `find_leaks`. The id can't match `ID_PATTERN`, and including
  `meta` keeps the rule simple: every schema that `deid` writes gets checked.
- Update the module docstring with one line: `deid` also writes `meta.build` (the build id the app
  reads as `snapshot_id`).
- **research_id / report_id stability:** unaffected. `xw`, the hash inputs and `.deid_key` are
  untouched. A test pins this (below).
- The tailnet MCP server (`server.py`) will also list `meta.build`. That's harmless: it holds no
  patient data.

### 2. App reads it (`mcp/src/uccc_genomics_mcp/cohort/queries.py`)

```python
def snapshot_id() -> str | None:
    """The de-id build's id (meta.build, written by deid), or None for a file built before #132."""
    con = get_db()
    try:
        row = con.execute("SELECT build_id FROM meta.build").fetchone()
    except duckdb.CatalogException:
        return None
    finally:
        con.close()
    return row[0] if row else None
```

Add `import duckdb`, and export `snapshot_id` from `cohort/__init__.py` (both the import and
`__all__`). It isn't cached: a save or edit opens one connection, the same as `vocabulary()`'s miss
path. Saves are rare.

### 3. Saved-cohort revisions carry the snapshot id (`saved.py`)

- `cohort_revision` gets `sa.Column("snapshot_id", sa.Text, nullable=True)`. Rows written before
  #132 stay `NULL`.
- `Revision` (response model) gets `snapshot_id: str | None`. `_revision(row)` passes
  `row.snapshot_id`. `_with_head` selects `cohort_revision.c.snapshot_id`.
- These signatures change (the new argument is keyword-only and required, so no caller forgets it):
  - `create(owner: str, d: Definition, *, snapshot_id: str | None) -> SavedCohort`
  - `append(owner, id, d, op, after: int, *, snapshot_id: str | None) -> SavedCohort`
  - `revert(owner, id, to: int, *, snapshot_id: str | None) -> SavedCohort`
  - `_append(conn, owner, id, head, d, op, *, snapshot_id)` writes it on the inserted revision.
- **Immutable once attached.** Revisions are already append-only (nothing updates them). The only
  way to remove one is `delete()`, which cascades from `cohort`. Change `delete()` so that, inside its
  transaction and before the DELETE, it raises
  `Conflict("saved cohort {id} is attached to a request for identified data; it can't be deleted")`
  when `request` has any row with `request.cohort == id`. Behind that check, the database refuses too:
  `request`'s foreign key to `cohort_revision` is `ON DELETE RESTRICT`, so the cascade fails even if
  the code check were bypassed.
- The grant `snapshot` table is not changed.

`app.py`: `snapshot_id()` reads DuckDB, so it runs in the threadpool:

```python
async def run_save(u, d):          # existing; add the id
    await run_in_threadpool(lambda: cohort.vocabulary().check(d))
    sid = await run_in_threadpool(cohort.snapshot_id)
    return await saved.create(u.sub, d, snapshot_id=sid)

async def run_saved_apply(u, id, op):   # existing; pass snapshot_id=await run_in_threadpool(cohort.snapshot_id)

async def run_revert(u: authen.User, id: uuid.UUID, to: int) -> SavedCohort:   # new
    return await saved.revert(u.sub, id, to, snapshot_id=await run_in_threadpool(cohort.snapshot_id))
```

`POST /api/saved/{id}/revert` and the `revert_saved_cohort` tool both call `run_revert`.

Mapping to the design's `saved_query` (no new table):

| design `saved_query` | here |
|---|---|
| query_id | `cohort.id` (= `cohort_revision.cohort`) |
| version | `cohort_revision.seq` |
| canonical_sql | `cohort_revision.definition`, the canonical definition JSON; `cohort.compile` turns it into SQL deterministically |
| sha256 | `cohort_revision.cohort_id`, the content hash of the selecting part |
| snapshot_id | `cohort_revision.snapshot_id` (new) |
| author | `cohort.owner` (the `sub`) |
| description | `definition.name` |

### 4. Broker group on the user (`authen.py`)

- `User` gains a third field: `broker: bool = False` (frozen dataclass; existing positional
  `User(sub, email)` calls keep working).
- Constant `BROKER_GROUP = "uccc-genomics-broker"`.
- `authentik`:
  - Bearer: `User(claims["sub"], _display(claims), _is_broker(claims))`.
  - Callback: the session cookie gains `"broker": _is_broker(claims)`.
  - Cookie read: `User(s["sub"], s["email"], s.get("broker") is True)`. Old cookies have no key, so
    `broker` is False.
  - `def _is_broker(claims: dict) -> bool: return BROKER_GROUP in claims.get("groups", [])`. This is
    called only after `_require_group`, which has already checked that `groups` is a list.
- `none` and `password` (local development only): `configure()` sets
  `AUTH["broker"] = os.environ.get("APP_BROKER") == "1"`, and `user()` returns
  `User(..., ..., AUTH["broker"])`. Add `"broker": False` to the `AUTH` defaults.
- `access`: always `broker=False`. Access JWTs carry no groups. Tier 2 is served under `authentik`.
- As with the dashboard group, removing someone from the broker group takes effect at their next
  sign-in (up to `SESSION_HOURS`). Bearer tokens are checked on every call.

### 5. Honest-broker tables (`mcp/src/uccc_genomics_mcp/broker.py`, new)

The tables are defined on `saved.metadata`, so foreign keys to `cohort_revision` resolve and the
Alembic `check` sees them. `migrations/env.py` adds `from uccc_genomics_mcp import broker  # noqa: F401`
(it registers the tables on `saved.metadata`). Column types are the SQLAlchemy core types already
used in `saved.py` (`sa.Text`, `sa.Integer`, `sa.Date`, `sa.Uuid`, `sa.DateTime(timezone=True)`,
`JSONB`). `created_at`/`decided_at`/`released_at` default to `now()` on the server, like `_created_at()`.

`irb_authorization`: one row per approval version. Amendments add rows.

| column | type | null | notes |
|---|---|---|---|
| irb_number | Text | no | PK part, e.g. `TEST-0001` |
| version | Integer | no | PK part; `CHECK (version >= 1)` |
| pi | Text | no | PI's name as on the approval |
| approval_date | Date | no | |
| expiration_date | Date | yes | NULL = no expiration (exempt determinations) |
| hipaa_pathway | Text | no | free text, e.g. `waiver`, `authorization`; accepted set is an open question for the privacy office |
| approved_population | Text | no | |
| status | Text | no | `CHECK (status IN ('active','suspended','closed'))`; "expired" is derived from `expiration_date`, never stored |
| created_by | Text | no | `sub` |
| created_at | timestamptz | no | default now() |

`irb_document`: references a file and stores no content.

| column | type | null | notes |
|---|---|---|---|
| id | Uuid | no | PK |
| irb_number, version | Text, Integer | no | FK → `irb_authorization (irb_number, version)` |
| doc_type | Text | no | `CHECK (doc_type IN ('approval_letter','personnel_list','protocol_excerpt','consent_form'))` |
| file_ref | Text | no | SharePoint path (rclone remote path) |
| sha256 | Text | no | `CHECK (sha256 ~ '^[0-9a-f]{64}$')` |
| section_cited | Text | yes | |
| protocol_version | Text | yes | |
| created_by | Text | no | `sub` |
| created_at | timestamptz | no | |

`irb_personnel`: PK `(irb_number, version, person_id)`, FK `(irb_number, version)` →
`irb_authorization`.

| column | type | null | notes |
|---|---|---|---|
| irb_number, version | Text, Integer | no | |
| person_id | Text | no | campus email as on the approved list, lower-cased. For the broker's checklist only, **never used to authorize** |
| name | Text | no | |
| role | Text | no | free text as on the list (e.g. `PI`, `coordinator`) |

`request`

| column | type | null | notes |
|---|---|---|---|
| id | Uuid | no | PK |
| requester | Text | no | `sub`; `index=True` → `ix_request_requester` |
| cohort, seq | Uuid, Integer | no | FK → `cohort_revision (cohort, seq)` `ON DELETE RESTRICT`: the frozen query version |
| irb_number, irb_version | Text, Integer | yes | FK → `irb_authorization (irb_number, version)` |
| purpose | Text | no | |
| fields | JSONB | no | list of field names |
| identifiers | JSONB | no | list of `{"identifier": str, "reason": str}` |
| recipients | JSONB | no | list of `{"name": str, "email": str}` |
| storage_location | Text | no | |
| retention_end | Date | yes | |
| status | Text | no | `CHECK (status IN ('draft','submitted','returned','approved','denied','fulfilled','closed'))` |
| created_at, updated_at | timestamptz | no | |

Plus `CHECK (status = 'draft' OR (irb_number IS NOT NULL AND irb_version IS NOT NULL AND retention_end IS NOT NULL))`:
only a draft may lack an IRB or a retention date. `denied` is added to the design's status list
because `review.decision` can be `deny`.

`review`: one or more rows per request.

| column | type | null | notes |
|---|---|---|---|
| id | Uuid | no | PK |
| request_id | Uuid | no | FK → `request.id`; `index=True` → `ix_review_request_id` |
| reviewer | Text | no | broker's `sub` |
| checklist | JSONB | no | `{item: bool}` |
| decision | Text | no | `CHECK (decision IN ('approve','return','deny'))` |
| notes | Text | no | |
| decided_at | timestamptz | no | default now() |

`release`

| column | type | null | notes |
|---|---|---|---|
| id | Uuid | no | PK |
| request_id | Uuid | no | FK → `request.id`; `index=True` → `ix_release_request_id` |
| file_name | Text | no | |
| sha256 | Text | no | `CHECK (sha256 ~ '^[0-9a-f]{64}$')` |
| row_count | Integer | no | `CHECK (row_count >= 0)` |
| fields_released | JSONB | no | list of field names |
| recipients | JSONB | no | list of `{"name", "email"}` |
| sharepoint_link | Text | no | |
| released_at | timestamptz | no | default now() |
| removed_at | timestamptz | yes | |
| closeout_attested_at | timestamptz | yes | |

`release_patient`: PK `(release_id, research_id)`. FK `release_id` → `release.id`. `research_id`
gets `index=True` → `ix_release_patient_research_id`, plus
`CHECK (research_id ~ '^[0-9a-f]{16}$')`: the shape `deid` produces (`substr(sha256(...), 1, 16)`),
so an MRN, name or date can't be stored here by mistake. The design's `study_id` is `research_id`.

No foreign key cascades on the broker tables (default `NO ACTION`): audit rows are never deleted by
deleting a parent.

**Migration** `mcp/src/uccc_genomics_mcp/migrations/versions/0002_honest_broker.py`
(`revision = "0002"`, `down_revision = "0001"`). `upgrade()` runs
`op.add_column("cohort_revision", sa.Column("snapshot_id", sa.Text(), nullable=True))` and then creates
the seven tables with the constraints and indexes above. Constraints use the same explicit
`sa.PrimaryKeyConstraint`/`sa.ForeignKeyConstraint`/`sa.CheckConstraint` style as `0001`, and
`op.create_index` uses the `ix_<table>_<column>` names. `downgrade()` drops them in reverse order
(`release_patient`, `release`, `review`, `request`, `irb_personnel`, `irb_document`,
`irb_authorization`, indexes first) and then `op.drop_column("cohort_revision", "snapshot_id")`. The
metadata and the migration must agree: `command.check(cfg)` in `tests/test_saved.py::pg_url` already
fails otherwise.

**Response models** (in `broker.py`, Pydantic v2; every optional field has an explicit `= None`):

```python
RequestStatus = Literal["draft", "submitted", "returned", "approved", "denied", "fulfilled", "closed"]

class Recipient(BaseModel):        name: str; email: str
class IdentifierReason(BaseModel): identifier: str; reason: str

class IrbAuthorization(BaseModel):
    irb_number: str; version: int; pi: str; approval_date: datetime.date
    expiration_date: datetime.date | None = None; hipaa_pathway: str; approved_population: str
    status: Literal["active", "suspended", "closed"]; created_at: datetime.datetime

class IrbDocument(BaseModel):
    id: uuid.UUID; doc_type: Literal["approval_letter", "personnel_list", "protocol_excerpt", "consent_form"]
    file_ref: str; sha256: str; section_cited: str | None = None; protocol_version: str | None = None
    created_at: datetime.datetime

class IrbPerson(BaseModel):        person_id: str; name: str; role: str

class IrbVersion(IrbAuthorization):
    documents: list[IrbDocument]   # created_at ascending
    personnel: list[IrbPerson]     # person_id ascending

class Irb(BaseModel):              irb_number: str; versions: list[IrbVersion]       # version ascending
class IrbList(BaseModel):          authorizations: list[IrbAuthorization]   # latest version per irb_number, irb_number ascending

class Review(BaseModel):
    id: uuid.UUID; reviewer: str; checklist: dict[str, bool]
    decision: Literal["approve", "return", "deny"]; notes: str; decided_at: datetime.datetime

class Release(BaseModel):          # no patient list: release_patient is never returned here
    id: uuid.UUID; file_name: str; sha256: str; row_count: int; fields_released: list[str]
    recipients: list[Recipient]; sharepoint_link: str; released_at: datetime.datetime
    removed_at: datetime.datetime | None = None; closeout_attested_at: datetime.datetime | None = None

class Request(BaseModel):
    id: uuid.UUID; requester: str
    cohort: uuid.UUID; seq: int; cohort_id: str; definition: Definition; snapshot_id: str | None = None  # the frozen revision
    irb_number: str | None = None; irb_version: int | None = None
    purpose: str; fields: list[str]; identifiers: list[IdentifierReason]; recipients: list[Recipient]
    storage_location: str; retention_end: datetime.date | None = None; status: RequestStatus
    created_at: datetime.datetime; updated_at: datetime.datetime

class RequestDetail(Request):
    irb: IrbVersion | None = None  # the version the request names
    reviews: list[Review]          # decided_at ascending
    releases: list[Release]        # released_at ascending

class Requests(BaseModel):         requests: list[Request]   # created_at descending, then id
```

`definition`, `cohort_id` and `snapshot_id` come from a join of `request` to `cohort_revision` on
`(cohort, seq)`. The definition is parsed with `Definition.model_validate`, as in `saved.py`.

**Functions** (all async, all through `saved._begin()`, so a missing `DATABASE_URL` gives
`saved.Unavailable` → 503; not-found is `saved.NotFound` → 404; every value is a bound parameter):

```python
async def list_my_requests(requester: str) -> Requests
async def get_my_request(requester: str, id: uuid.UUID) -> RequestDetail   # NotFound(f"no request {id}") if missing or not the requester's
async def list_requests(status: RequestStatus | None = None) -> Requests   # broker: all, optionally one status
async def get_request(id: uuid.UUID) -> RequestDetail                      # broker: any
async def list_irb() -> IrbList                                            # broker
async def get_irb(irb_number: str) -> Irb                                  # broker; NotFound(f"no IRB authorization {irb_number}")
```

Someone else's request is indistinguishable from a missing one: same 404, same message (the same
rule as saved cohorts).

### 6. Endpoints (`app.py`)

Gate:

```python
def broker_user(u: authen.User = Depends(user)) -> authen.User:
    if not u.broker:
        raise HTTPException(403, "honest broker only")
    return u

def _mcp_broker(ctx: Context) -> authen.User:   # ToolError("honest broker only") unless _mcp_user(ctx).broker
```

| REST | MCP tool | who |
|---|---|---|
| `GET /api/requests` → `Requests` | `list_my_requests()` | any signed-in user, own rows (`requester == u.sub`) |
| `GET /api/requests/{id}` → `RequestDetail` | `get_my_request(id)` | same |
| `GET /api/broker/requests?status=` → `Requests` | `broker_list_requests(status=None)` | broker |
| `GET /api/broker/requests/{id}` → `RequestDetail` | `broker_get_request(id)` | broker |
| `GET /api/broker/irb` → `IrbList` | `broker_list_irb()` | broker |
| `GET /api/broker/irb/{irb_number}` → `Irb` | `broker_get_irb(irb_number)` | broker |

- `status` is typed `RequestStatus | None`, so FastAPI answers 422 for any other value and the MCP
  tool's input schema enum rejects it. `irb_number` is `Annotated[str, Path(max_length=64)]` for REST and
  `Annotated[str, Field(max_length=64)]` for MCP.
- MCP tools follow the existing pattern: `try: ... except TOOL_ERRORS as e: raise ToolError(str(e))`.
  A non-broker gets `ToolError("honest broker only")`.
- Add one sentence to `INSTRUCTIONS`: "Requests for identified data are read-only here:
  list_my_requests and get_my_request show the caller's own; the broker_* tools are for the honest
  broker group only."
- Then run `cd web && bun run gen`, so `web/openapi.json` and `web/src/api.gen.ts` are regenerated and
  committed (`test_openapi_snapshot` and `bun run typecheck` require it).

**What leaves, and the small-cell rule.** None of these endpoints run a query against the de-id file
or return a cohort count. They return request metadata, IRB records and release metadata. The only
number is `release.row_count`, the size of an identified release. It goes only to that request's
requester (who received the file, and whose cover note states the count) and to brokers. Both are
authorized for the identified data itself, so flooring doesn't apply and would be wrong for
accounting. `release_patient` (study ids) is never returned by any endpoint in this issue. The free
`query` tool stays on the tailnet MCP server, which reads only the de-id file, never Postgres. MCP
results go to the caller's own client, the same as the REST JSON.

### 7. Docs (same PR)

- `README.md`, "Saved cohorts": revisions record `snapshot_id` (the de-id build id); deleting a saved
  cohort that a request references answers 409. A new short paragraph, "Honest broker records (#132)",
  lists the seven tables, the six endpoint/tool pairs, the broker group (`uccc-genomics-broker`, from
  the `groups` claim) and `APP_BROKER=1` for `--auth none|password` development.
- `docs/ARCHITECTURE.md` decision 7: add the broker tables to the table list in one sentence that points
  to `docs/HONEST_BROKER.md`.
- `docs/HONEST_BROKER.md` "Data model": note under the table that `saved_query` maps onto
  `cohort_revision` (the table from §3 above, condensed), `release_patient.study_id` is `research_id`,
  `request.status` adds `denied`, `irb_authorization.status` is `active|suspended|closed` with expiry
  derived from `expiration_date`, and the build id is `meta.build.build_id`. This changes the design
  doc's table (it names a `saved_query` table and a `study_id` column); the issue asks for this
  mapping, and the update is in this PR.
- `.env.example`: `# APP_BROKER=1   # --auth none|password only: the local user is an honest broker`.
- `AGENTS.md` layout: one line under `mcp/src/uccc_genomics_mcp/`:
  `broker.py     honest-broker records in Postgres (IRB registry, requests, reviews, releases): read-only here`.

## Acceptance criteria

- [ ] `genomics deid` on synthetic input writes `meta.build` with exactly one row whose `build_id` matches
      `^\d{8}T\d{6}Z-[0-9a-f]{8}$`. Two consecutive builds give different ids and identical
      `(vendor, research_id)` and `report_id` sets.
- [ ] `cohort.snapshot_id()` returns the build id, or `None` for a file without `meta.build`.
- [ ] Saving, applying an operation to and reverting a saved cohort (REST and MCP) each store the
      current `snapshot_id` on the new revision, and `Revision.snapshot_id` returns it. REST and MCP
      still give identical JSON.
- [ ] `alembic upgrade head` → `downgrade 0001` → `upgrade head` works on the throwaway Postgres.
      After the downgrade, the seven tables and `cohort_revision.snapshot_id` are gone. `command.check`
      passes at head.
- [ ] Deleting a saved cohort whose revision a `request` references answers 409 (REST) or a ToolError
      (MCP), and the cohort and its revisions are still there. A raw `DELETE FROM cohort` for it fails
      with an IntegrityError (FK RESTRICT).
- [ ] `GET /api/requests` and `list_my_requests` return only the caller's requests. Another user's id
      gives 404 from `GET /api/requests/{id}` and a NotFound ToolError from `get_my_request`, with the
      same message as a missing id.
- [ ] Each `/api/broker/*` route and `broker_*` tool: a non-broker gets 403 or `ToolError("honest broker
      only")`, and a broker gets the data. `status=bogus` is 422.
- [ ] Under `--auth authentik`, a token or session whose `groups` contain `uccc-genomics-broker` gives
      `User.broker is True`, and otherwise False. A session cookie without a `broker` key gives False.
      An `email` claim never affects `broker`.
- [ ] No response from any new endpoint contains `research_id` or any `release_patient` value.
- [ ] No broker table has a column named in `deid.DROP` (e.g. `mrn`, `dob`, `first_name`), and
      inserting a non-hex `research_id` into `release_patient` fails the CHECK.
- [ ] The CHECKs on `request.status`, `review.decision`, `irb_document.doc_type` and `sha256` reject bad
      values, and a non-draft `request` without `irb_number` is rejected.
- [ ] The new GET routes are in `GATED` (401 without login). The new tools are in `test_tools_list`.
      `web/openapi.json` and `api.gen.ts` are regenerated.
- [ ] `uv run pytest -q` passes (with `TEST_DATABASE_URL` for the Postgres tests), as does
      `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`. The dashboard check is n/a.

## Test plan

All synthetic. `DATA` is a temp dir, and Postgres is the throwaway `TEST_DATABASE_URL`. Nothing reads
`$DATA/raw`, the PHI file or the real de-id file.

- `tests/test_pipeline.py`:
  - `test_deid_writes_build_id`: `pipeline(data, {...FMI...})`, then read `meta.build` from the
    attached de-id file and check the format. Run `genomics(data, "deid")` again; the id is different,
    and `SELECT vendor, research_id, report_id FROM unified.report ORDER BY ALL` is equal before and after.
  - `test_find_leaks_matches_embedded_and_lower_case_ids` stays as it is. `deid` now passes `"meta"`,
    which the existing deid test exercises.
- `tests/test_cohort.py::write_mart`: add
  `CREATE SCHEMA meta; CREATE TABLE meta.build AS SELECT 'synthetic-build-1' AS build_id`. A new
  `test_snapshot_id` checks that `cohort.snapshot_id() == "synthetic-build-1"`, and also that it is
  `None` on a temp DuckDB file with only `mart.*` (monkeypatch `queries.get_db` to it).
- `tests/test_saved.py`:
  - `clean` truncates every table:
    `TRUNCATE release_patient, release, review, request, irb_personnel, irb_document, irb_authorization, snapshot, cohort_revision, cohort, cohort_version`.
  - `test_revisions` (or a new `test_revision_snapshot_id`) checks that every revision from save,
    apply and revert has `snapshot_id == "synthetic-build-1"`, on both surfaces.
  - `test_stale_append_conflicts` passes `snapshot_id=None` to the direct `saved.append` calls.
  - `test_migration_down_and_up`: `command.downgrade(cfg, "0001")`, then assert from
    `information_schema` that the tables and the column are gone, then `command.upgrade(cfg, "head")`
    and `command.check(cfg)`. It restores head in a `finally`, because the fixture is module-scoped.
- `tests/test_broker.py` (new). It reuses `pg_url`, `clean`, `sql` and `ids`/`mart_file` from
  `test_saved`/`test_app`. The fake `authen.user` reads `x-test-user` and `x-test-broker: 1`. Seed rows
  are inserted with `sql("INSERT ...")` and use synthetic values only: IRB `TEST-0001` v1/v2, PI
  `Dr Example`, person `a@example.edu`, request purposes like `synthetic purpose`, sha256 `"0"*64`,
  research ids like `"0123456789abcdef"`. The request revision is a real saved cohort created through
  `POST /api/saved` by user A. Tests:
  - requester scoping (A sees one, B sees none, B's GET by id is 404 with the same message as a random UUID), REST and MCP;
  - broker gate: 403 / ToolError for A without the header; a broker sees all, filters by status and gets
    `IrbList` (latest version per IRB) and `Irb` (both versions, docs and personnel ordered);
  - `RequestDetail` includes the frozen definition, `cohort_id` and `snapshot_id` of the referenced
    revision, even after A appends newer revisions (head moves, the request still shows its `seq`);
  - delete refusal (409 / ToolError) and raw-SQL FK RESTRICT;
  - CHECK constraints (bad status, bad decision, bad doc_type, bad sha256, non-hex research_id,
    non-draft without IRB) each raise `sqlalchemy.exc.IntegrityError`;
  - `walk()` over every new endpoint's JSON finds no `research_id` key and none of the seeded
    `release_patient` values;
  - no broker table column is in `uccc_genomics.deid.DROP` (an `information_schema.columns` query).
- `tests/test_authen.py`: following the existing authentik token fixtures, add one test each for Bearer
  claims with and without `uccc-genomics-broker`, a session cookie made through the callback with the
  group, a cookie signed without the `broker` key, and `none` with `APP_BROKER=1` and unset.
- `tests/test_app.py`: add the six new tools to `test_tools_list`, and add `("GET", "/api/requests")`
  and `("GET", "/api/broker/irb")` to `GATED`.

## Risks

- **`build_id` changes every daily rebuild** even when the data didn't change. Any revision older than
  a day therefore names an older build. That's correct ("the build it ran against"), but #135's "refuse
  unless the snapshot matches, or `--rerun-on-current`" will almost always need the flag.
  Fingerprinting the content would barely help, because new reports land most days. #135 decides how to
  word that.
- **`snapshot_id` is recorded when a revision is saved, not when it was last counted.** A revision
  saved weeks before a request is attached names that older build. #133 can save a fresh revision when
  the request is created if that matters.
- **Broker membership lasts up to 8 hours after removal** for cookie sessions (`SESSION_HOURS`), the
  same latency as the dashboard group. Bearer tokens are checked on every call.
- **Postgres now holds study ids (`release_patient.research_id`) and staff contact data**
  (`recipients`, `irb_personnel`). They aren't PHI, but they are a new kind of content in that
  database. Nothing in this issue writes or returns `release_patient`, and the CHECK keeps it to keyed
  hashes. Free-text fields (`purpose`, `notes`) could still receive an identifier typed by a person;
  #133/#134 own their validation.
- **`APP_BROKER=1` under `--auth none|password`** makes the local user a broker. Those modes are for
  development only (AGENTS.md), and the tables hold no PHI.
- **`seam` label:** this changes `saved.delete`, the `Revision` model (an API shape the Discover types
  regenerate from), `authen.User`, and the deid build (one new schema, with research_id untouched).
  Every existing saved-cohort, authen and pipeline test has to keep passing unchanged, except for the
  signature updates named above.
