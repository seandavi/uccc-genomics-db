# Spec #35: genomics-app — FastAPI REST and MCP over the cohort module, behind authen

Part of #23. `docs/ARCHITECTURE.md` decisions 4, 5, 8 and 11. Builds on #34 (the cohort module,
`mcp/src/uccc_genomics_mcp/cohort/`, spec `docs/specs/34-cohort-module-definition-operations.md`).
Labels: `review:security`, `review:ux`.

All examples are synthetic. Gene symbols, OncoTree codes and marker names are public vocabulary.
No real counts appear.

## Goal

A new service, `genomics-app`, that exposes the cohort module twice from one process:

- **REST** under `/api/*` (FastAPI, OpenAPI generated from the module's Pydantic models);
- **MCP** (Streamable HTTP) at `/mcp`, with five tools whose input and output schemas are the same
  models.

Every request except `GET /api/health` is authenticated once through `authen.user(request)`.
Count and pivot queries are rate-limited per user and audit-logged (one JSON line on stdout per
query). One parametrised test runs every operation and query through both surfaces and requires
identical JSON.

Done when REST and MCP both answer the module's queries with identical results, behind `authen`,
with tests green.

## Non-goals

- `genomics-cohort-api` (`cohort_api.py`), its systemd unit and the public dashboard are unchanged
  (ARCHITECTURE decision 5).
- `genomics-mcp` (`server.py`) is unchanged. The free-SQL `query`, `list_tables`,
  `describe_tables` and `get_documentation` tools stay on the tailnet server only (decision 4). The
  new MCP server is a separate `MCPServer` instance with only the five cohort tools.
- No React app (a later issue). `--static` only serves a directory that already exists.
- No Postgres, saved cohorts, versions or `/api/chat` (decisions 7 and 9).
- No systemd unit, Traefik route, `tailscale serve` or deploy. The service runs by hand on the
  pipeline host for development (ARCHITECTURE "Development").
- No new authen backend; `access`, `password` and `none` stay as they are.
- No change to the cohort module's logic, suppression, SQL or the mart. The module gains one
  re-export (`Operation`).
- No data change: no schema, table or column is added, and `research_id` / `report_id` are
  untouched (this service only reads `mart.*` through the module).

## Design

### Files

| File | Change |
|---|---|
| `mcp/src/uccc_genomics_mcp/app.py` | **new**: the whole service (models, middleware, limiter, audit, shared calls, REST routes, MCP tools, `app()`, `main()`) |
| `mcp/src/uccc_genomics_mcp/cohort/__init__.py` | re-export `Operation` from `.definition` (add to the import and `__all__`) |
| `mcp/pyproject.toml` | add `"fastapi>=0.162"` to `dependencies`; add `genomics-app = "uccc_genomics_mcp.app:main"` to `[project.scripts]` |
| `uv.lock` | regenerated with `uv lock` (CI runs `uv sync --locked`) |
| `tests/test_app.py` | **new**: the tests below |
| `README.md` | Layout line for `app.py`; a "Cohort app (genomics-app)" section (below) |
| `AGENTS.md` | Layout line `app.py  genomics-app: FastAPI REST (/api/*) + MCP (/mcp) over cohort/, behind authen`; the dev run line in Commands |
| `docs/ARCHITECTURE.md` | "Development": name the service and file (`genomics-app`, `mcp/src/uccc_genomics_mcp/app.py`, #35) |
| `dashboard/COHORT_DISCOVERY.md` | §3.5: a note on where the endpoints live and the deviations below |
| `mcp/README.md` | one line: the cohort tools (no SQL) are served by `genomics-app` at `/mcp`, see README |

### Dependency

`fastapi>=0.162` is the only new dependency. ARCHITECTURE decision 5 and the issue name FastAPI,
which settles "ask before adding". Checked against PyPI on 2026-10-25: fastapi 0.162.0 requires
`starlette>=0.46.0`, `pydantic>=2.9.0`, `typing-extensions`, `typing-inspection`, `annotated-doc`
and `opentelemetry-api>=1.44.0`. All of these except `annotated-doc` are already in `uv.lock`
(starlette 1.6.0, pydantic 2.13.5, opentelemetry-api 1.44.0). `uvicorn` is already installed
through `mcp` and is imported directly, as `cohort_api.py` does. Use
`starlette.testclient.TestClient` in tests, as the existing tests do (it uses the locked `httpx2`).

Verified with a throwaway probe against the locked `mcp` 2.1.1 plus fastapi 0.162.0:
`streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True, ...)`
returns a Starlette app. Its routes can be appended to a FastAPI router, which serves exactly
`/mcp` with no redirect. Mounting at `/mcp` instead 307-redirects `/mcp` to `/mcp/`, so do not
mount it. The app's `mcp.session_manager.run()` must run in the FastAPI lifespan. Each
`streamable_http_app()` call makes a new session manager, and each manager runs once, so `app()`
calls it every time it builds an app. A stateless JSON `tools/call` needs no `initialize`.
Sync tool functions run in a worker thread
(`mcp/server/mcpserver/utilities/func_metadata.py`). `ctx.request_context.request` is the
Starlette `Request` of the current POST, built from the same ASGI scope.

### Auth: one ASGI middleware

```python
class RequireUser:
    """Pure ASGI middleware around the whole app: every HTTP request except GET /api/health is
    authenticated once with authen.user(); the email goes into the request's scope state."""
    def __init__(self, app: ASGIApp) -> None
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None
```

- `scope["type"] == "lifespan"`: pass through.
- `scope["type"] == "http"` and `scope["path"] == "/api/health"`: pass through.
- Any other `http` request:
  `email = await starlette.concurrency.run_in_threadpool(authen.user, Request(scope))`. Run it in
  the threadpool because scrypt and the JWKS fetch block. On `PermissionError as e`, send
  `JSONResponse({"detail": str(e)}, status_code=401, headers=authen.challenge())` and stop. On
  success, set `scope["state"] = {**scope.get("state", {}), "user": email}`. That is a fresh
  dict, so a server that shared one state dict across requests could not leak a user. Then call
  the app.
- Any other scope type (`websocket`): return without calling the app. The app has no websocket
  routes.

Register it as the outermost layer with `app.add_middleware(RequireUser)`. It is a pure ASGI
class, not `BaseHTTPMiddleware`, so MCP responses are not buffered. It covers the REST routes,
`/mcp`, `/api/openapi.json`, `/api/docs`, the static files and unknown paths (fail closed: a
route added later is authenticated without anyone remembering to).

Read side:

```python
def user(request: Request) -> str:
    """FastAPI dependency: the email RequireUser stored; HTTPException(401) if it is missing."""

def _mcp_user(ctx: Context) -> str:
    """The email RequireUser stored for this MCP POST; ToolError if there is no HTTP request or
    no user (an in-process call that bypassed the middleware)."""
```

`user()` returns `request.state.user` and raises `HTTPException(401, "not authenticated",
headers=authen.challenge())` when it is absent. `_mcp_user` reads
`ctx.request_context.request.state.user`. Outside a request, `ctx.request_context` raises
`ValueError`; with no HTTP request, `.request` is `None` (an `AttributeError` on `.state`); with
no user, `.state.user` raises `AttributeError`. Catch exactly those two and raise
`ToolError("not authenticated")`. Each REST route takes `email: str = Depends(user)` where
it needs it, and the read-only routes take `Depends(user)` too.

**Deviation from the issue text.** The issue says every route "calls `authen.user(request)`
(FastAPI dependency); MCP requests too". Here `authen.user` runs once per request in the
middleware, and the FastAPI dependency only reads its result. This is the issue's intent, applied
more strictly: one check for every surface (ARCHITECTURE diagram), including routes FastAPI
generates (docs, OpenAPI) and the static mount, which take no dependencies. Under `password` it
also costs one scrypt per request instead of two for MCP.

### Models (in `app.py`)

```python
class ApplyRequest(BaseModel):
    definition: Definition
    op: Operation

class ApplyResult(BaseModel):
    definition: Definition
    cohort_id: str

class Option(BaseModel):
    field: str            # VocabEntry.field, e.g. "alteration.gene"
    parent: str | None
    value: str

class Options(BaseModel):
    entries: list[Option]
    years: tuple[int, int] | None
    cut_points: dict[str, list[float]]
    min_cell: int

class SchemaInfo(BaseModel):
    version: int                      # cohort.SCHEMA_VERSION
    definition: dict                  # cohort.json_schema()
    operation: dict                   # cohort.operation_json_schema()
    cut_points: dict[str, list[float]]
    min_cell: int
```

`Option` exists because `VocabEntry.patients` is `Field(exclude=True)`. It is left out of the
JSON, but the MCP SDK's generated `outputSchema` still lists it as required (checked in the
probe), so a strict MCP client would reject a `VocabEntry` result. `Option` has only the
serialised fields. `Definition`, `Operation`, `CountResult` and `PivotResult` are used as they
are. The probe confirmed that both FastAPI and the MCP schemas use the `class` alias, not
`class_`.

### Shared calls (the thin layer)

REST routes and MCP tools both call these and add only transport (de)serialisation and error
mapping, so the two surfaces cannot drift apart:

```python
Surface = Literal["rest", "mcp"]

def run_count(email: str, surface: Surface, d: Definition) -> CountResult:
    rate_limit(email); r = cohort.count(d); audit(email, surface, "count", d, r.patients); return r

def run_pivot(email: str, surface: Surface, d: Definition) -> PivotResult:
    rate_limit(email); r = cohort.pivot(d); audit(email, surface, "pivot", d, r.patients); return r

def run_apply(d: Definition, op: Operation) -> ApplyResult:
    new = cohort.apply(d, op, cohort.vocabulary()); return ApplyResult(definition=new, cohort_id=cohort.cohort_id(new))

def run_options(q: str, limit: int = 20) -> Options:
    v = cohort.vocabulary()
    return Options(entries=[Option(field=e.field, parent=e.parent, value=e.value) for e in v.search(q, limit)],
                   years=v.years, cut_points=v.cut_points, min_cell=v.min_cell)

def run_schema() -> SchemaInfo
```

`limit` in `run_options` is the search result limit; the rate limiter is `rate_limit`.
`Vocabulary.search` already returns `[]` for an empty or over-long `q` and clamps `limit` to 1–50.

### Rate limit

```python
RATE_LIMIT = 60        # count + pivot calls per user per RATE_WINDOW, REST and MCP together
RATE_WINDOW = 60.0     # seconds
_calls: dict[str, collections.deque[float]] = {}
_calls_lock = threading.Lock()

class RateLimited(Exception):
    def __init__(self, retry_after: int)   # message: f"rate limit: {RATE_LIMIT} queries per {int(RATE_WINDOW)} s; retry in {retry_after} s"

def rate_limit(email: str) -> None
```

This is a sliding window over `time.monotonic()` under the lock. REST routes are sync `def` and
run in FastAPI's threadpool; MCP tools run in a worker thread. Drop timestamps older than the
window. If `RATE_LIMIT` remain, raise `RateLimited(ceil(RATE_WINDOW - (now - oldest)))`;
otherwise record `now`. Write a `ponytail:` comment on the ceiling: in-process, per user, and
reset on restart, so per-process limits multiply if it ever runs more than one worker. The upgrade
path is Postgres or Redis with the saved-cohorts work. Only `count` and `pivot` are limited:
they run SQL and return counts (the differencing exposure, decision 11). `apply`, `options`
and `schema` return no counts and are not limited.

### Audit

```python
def audit(email: str, surface: Surface, endpoint: Literal["count", "pivot"], d: Definition,
          patients: int | None) -> None:
    print(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "email": email, "surface": surface,
                      "endpoint": endpoint, "cohort_id": cohort.cohort_id(d),
                      "definition": d.model_dump(mode="json"), "patients": patients}), flush=True)
```

One line per successful count or pivot, written to stdout (journald under systemd, as
`cohort_api.audit` does). `patients` is the suppressed value from the result (`null` when
hidden). The module returns only suppressed results, so a raw count never reaches the log or
anywhere else. Refused, invalid and rate-limited requests are not logged as queries.

### REST routes

`FastAPI(title="UCCC genomics cohort app", lifespan=..., openapi_url="/api/openapi.json",
docs_url="/api/docs", redoc_url=None)`. All routes are sync `def`. Errors are
`{"detail": "<message>"}`:

| Route | Body / query | Response | Errors |
|---|---|---|---|
| `POST /api/cohort` | `Definition` (the body is the definition itself) | `CountResult` | 422 body validation; 400 `DefinitionError` (e.g. a value not in the vocabulary); 429 `RateLimited` with `Retry-After` |
| `POST /api/pivot` | `Definition` with `pivot` set | `PivotResult` | as above; 400 when `pivot` is null |
| `POST /api/apply` | `ApplyRequest` | `ApplyResult` | 422; 400 `DefinitionError` (unknown criterion id, value not in vocabulary) |
| `GET /api/options` | `q: str = ""`, `limit: int = 20` | `Options` | 422 |
| `GET /api/schema` | none | `SchemaInfo` | none |
| `GET /api/health` | none, **no auth** | `{"status": "Healthy"}` | 503 `{"status": "unhealthy"}` |

- Exception handlers: `DefinitionError` → 400 `{"detail": str(e)}`; `RateLimited` → 429
  `{"detail": str(e)}` with header `Retry-After: <retry_after>`. Body validation stays FastAPI's
  422 (documented in the OpenAPI). Its `loc` names the bad field (`["body", "criteria", 0,
  "gene"]`).
- Health runs `SELECT count(*) FROM mart.report` through `get_db()` (imported from
  `uccc_genomics_mcp.server`, the hardened read-only connection, opened and closed per call). On
  any exception it prints the error to stderr and returns 503. **Deviation from the COHORT_TOOL.md
  `/health` contract:** the body has no `reports` count and no error text. The route is open, and
  neither a total nor an exception message (which may name a path) needs to leave an
  unauthenticated endpoint. "Healthy" in a 200 body still satisfies the uptime check.
- **Deviation from COHORT_DISCOVERY.md §3.5** ("`POST /api/pivot`: definition plus `rows` and
  `cols`"): #34 put `pivot: {rows, cols}` inside the definition, so the body is just the
  definition. The `GET /api/cohort` phase 1 parameters stay on `genomics-cohort-api`, not here.

### MCP tools

```python
mcp_app = MCPServer(name="uccc-genomics-app", title="UCCC genomics cohort tools",
                    description="Floored patient counts over de-identified UCCC Caris + FMI reports",
                    instructions=INSTRUCTIONS)
```

`INSTRUCTIONS`: Build a cohort definition (its JSON Schema comes from `describe_definition`),
edit it with `apply_op`, map the user's words to vocabulary values with `search_vocabulary`, then
`count` it, or `pivot` it once its `pivot` is set. Counts are distinct patients. `null` means
suppressed (1–4, or recoverable by subtraction), never zero. Quote only numbers a tool returned.
Never claim the data holds stage, treatment, outcomes, race or ethnicity.

| Tool | Signature | Returns | Shared call |
|---|---|---|---|
| `search_vocabulary` | `(q: str, ctx: Context, limit: int = 20)` | `Options` | `run_options` |
| `apply_op` | `(definition: Definition, op: Operation, ctx: Context)` | `ApplyResult` | `run_apply` |
| `count` | `(definition: Definition, ctx: Context)` | `CountResult` | `run_count(_mcp_user(ctx), "mcp", definition)` |
| `pivot` | `(definition: Definition, ctx: Context)` | `PivotResult` | `run_pivot(_mcp_user(ctx), "mcp", definition)` |
| `describe_definition` | `(ctx: Context)` | `SchemaInfo` | `run_schema` |

- All five are sync `def` functions registered with `@mcp_app.tool()`. Each docstring says what it
  answers, in a sentence or two, for the model reading `tools/list`. The `ctx: Context` parameter
  is not part of the input schema (checked in the probe). Every tool calls `_mcp_user(ctx)`, even
  where it doesn't need the email, so an in-process call that bypassed the middleware fails
  closed.
- Errors: catch `DefinitionError` and `RateLimited` and `raise ToolError(str(e)) from None`
  (`mcp.server.mcpserver.exceptions.ToolError`). The client sees `isError: true` with the
  message. Argument validation failures come back from the SDK as `isError: true` naming the
  field. Any other exception comes back as the SDK's generic "Error executing tool <name>", with
  no internals.
- The tools are names over the shared calls. This is not `server.py`'s `mcp` object; nothing from
  `server.py` but `get_db` is imported.

### `app()` and `main()`

```python
def app(static_dir: str | None = None) -> FastAPI
def main(argv: list[str] | None = None) -> None
```

`app()`:

1. `sub = mcp_app.streamable_http_app(streamable_http_path="/mcp", json_response=True,
   stateless_http=True, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))`,
   then `manager = mcp_app.session_manager`. DNS-rebinding protection is off, as in
   `server.py`: every request carries credentials checked by `RequireUser`, and with protection
   on, the SDK would refuse any Host it was not told about (the tailnet address,
   `testserver`). Stateless JSON means no sessions and no SSE: each POST is self-contained, and
   its `Request` carries the authenticated user.
2. The FastAPI lifespan is `async with manager.run(): yield`.
3. Register the REST routes and exception handlers, then
   `application.router.routes.extend(sub.routes)` (exact `/mcp`, no redirect).
4. If `static_dir`: `application.mount("/", StaticFiles(directory=static_dir, html=True))`, last,
   so it has the lowest precedence.
5. `application.add_middleware(RequireUser)`.

`main()`: `argparse` with `--auth` (`choices=authen.MODES`, **required**: no silent default, so
the dev run states `password` and production will state its backend), `--host` (default
`127.0.0.1`), `--port` (default `8092`; 8088–8091 are taken by the tailnet MCP proxy, `genomics-mcp`,
`genomics-cohort-api` and its local-dev port), `--static`. It calls `authen.configure(args.auth)`,
then `uvicorn.run(app(args.static), host=args.host, port=args.port, access_log=False)`. `import
uccc_genomics.config` at the top loads `.env` (`APP_USER`, `APP_PASSWORD_HASH`, `ACCESS_*`), as
`cohort_api.py` does.

### What leaves the de-id file, and the small-cell rule

Every number this service returns comes from `cohort.count` / `cohort.pivot`, so it has been
through `suppress.py`. That means the floor of 5 (`MIN_CELL`), secondary suppression on every line
(both pivot axes, to a fixed point), floored funnel deltas, the whole-cohort rule and the
`loosen[]` clearance rule. `Options` carries vocabulary values that are already floored (values
held by fewer than 5 patients are never present) and no counts. `SchemaInfo` and `ApplyResult`
carry no data from the file. No `research_id`, `report_id` or row-level value is in any response
or in the audit log. The service adds no new suppression logic and must not post-process counts.
Values reach SQL only as bound parameters inside the module. The browser and the model send
definitions and operations, never SQL. Logged-in users get the same suppression (decision 11).
Differencing across queries is accepted under the audit log and the rate limit, as in
`COHORT_TOOL.md` and §3.6.

### README section (text to add, under "Dashboard" after "Cohort API")

```markdown
### Cohort app (genomics-app)

`mcp/src/uccc_genomics_mcp/app.py`: the campus cohort site's backend (docs/ARCHITECTURE.md). One
process serves REST at `/api/*` (OpenAPI at `/api/docs`) and MCP (Streamable HTTP, stateless) at
`/mcp`, both thin layers over `cohort/`. Every request but `/api/health` needs a login through
`authen` (`--auth access|password|none`). `count` and `pivot` are limited to 60 a minute per user
across both surfaces and logged to stdout as one JSON line each (user, cohort_id, definition,
suppressed patients). The MCP tools are `search_vocabulary`, `apply_op`, `count`, `pivot` and
`describe_definition`; there is no SQL tool.

    uv run python -m uccc_genomics_mcp.authen    # once: put APP_USER and the printed APP_PASSWORD_HASH in .env
    uv run genomics-app --auth password --host <tailnet-addr> --port 8092 [--static <dir>]
    # http://<tailnet-addr>:8092/api/docs, MCP clients at http://<tailnet-addr>:8092/mcp

`--static` serves a built front end at `/` (the React app, later). Development only: no systemd
unit or deploy yet.
```

## Acceptance criteria

- [ ] `uv run genomics-app --help` works; `--auth` is required and offers `access`, `password`,
      `none`. `fastapi>=0.162` is in `mcp/pyproject.toml`, and `uv lock` has been run, so
      `uv sync --locked` passes.
- [ ] `POST /api/cohort`, `POST /api/pivot`, `POST /api/apply`, `GET /api/options`,
      `GET /api/schema` and `GET /api/health` exist with the bodies, responses and status codes
      above, and `/api/openapi.json` names `Definition`, `CountResult`, `PivotResult`,
      `ApplyRequest`, `ApplyResult`, `Options` and `SchemaInfo` among its schemas.
- [ ] `tools/list` on `POST /mcp` returns exactly `search_vocabulary`, `apply_op`, `count`,
      `pivot` and `describe_definition`. There is no `query` tool. `count`'s input schema has a
      `definition` property, and no tool's output schema mentions `patients` under the options
      entries.
- [ ] Without credentials, every route except `GET /api/health` returns 401: the five REST
      routes, `/api/openapi.json`, `/api/docs`, `POST /mcp`, `GET /mcp`, `/` and a file under
      `--static`, and an unknown path. Under `password` the 401 carries `WWW-Authenticate: Basic`,
      and wrong credentials are 401. Under `access` a missing or wrong-audience JWT is 401.
      `/api/health` is 200 without credentials.
- [ ] Parity: for every case in the parity list (below), the REST JSON equals the MCP
      `structuredContent` exactly. For every error case, REST returns 4xx and MCP returns
      `isError: true`, and both messages name the offending field or id.
- [ ] No count from 1 to 4 under any `patients`, `denominator` or `reports` key, and no synthetic
      `research_id` or `report_id` string, anywhere in any response from either surface. No
      `options` entry has a `patients` key.
- [ ] One audit line per successful count and pivot on either surface, with `email` (the
      authenticated user, for MCP too), `surface`, `endpoint`, `cohort_id` (equal to the
      response's), `definition` and `patients` (equal to the response's). No audit line for
      options, apply, schema, health, refused or rate-limited requests.
- [ ] With `RATE_LIMIT` set to 3, the fourth count or pivot from the same user within the window
      is refused: REST 429 with `Retry-After`, MCP `isError` with "rate limit". REST and MCP calls
      share one budget. Another user still gets through, and `apply`, `options` and `schema` are
      never limited.
- [ ] `cohort_api.py`, `server.py`, `authen.py` and `cohort/` logic are unchanged (only the
      `Operation` re-export is added). `uv run pytest -q` passes. Dashboard check: n/a (no change
      under `dashboard/` except the `COHORT_DISCOVERY.md` note).
- [ ] README, AGENTS.md, ARCHITECTURE.md, COHORT_DISCOVERY.md §3.5 and mcp/README.md are updated
      as listed under Files.

## Test plan

`tests/test_app.py`, synthetic only: the #34 mart in a temp dir, no network, never `$DATA/raw`,
the PHI file or the real de-id file.

Fixtures:

- `from test_cohort import build_mart, use_mart, write_mart` (import those names only, so pytest
  does not re-collect `test_cohort`'s tests). A module-scoped fixture writes the mart to
  `tmp_path_factory`.
- `client` (function scope): `use_mart(path, m, monkeypatch)` (it patches `queries.get_db`,
  `DEID_DB`, `_vocab` and `suppress.ROUND`). Monkeypatch `app.get_db` to the same read-only,
  hardened connection for health. `monkeypatch.setattr(app, "_calls", {})`. Configure the
  `password` backend as `test_cohort_api.test_password` does: `APP_USER=sean`,
  `APP_PASSWORD_HASH=authen.hash_password("s3cret")`, `monkeypatch.setattr(authen, "AUTH",
  dict(authen.AUTH))`, `authen.configure("password")`. Write a static dir with `index.html`
  under `tmp_path`, then `with TestClient(app.app(static_dir)) as c: yield c`. Use the context
  manager, so the lifespan starts the MCP session manager.
- `mcp_call(c, tool, args, auth=("sean", "s3cret"))` posts
  `{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}`
  to `/mcp` with `accept: application/json, text/event-stream` and returns `r.json()["result"]`.
  `mcp_list(c)` does the same for `tools/list`.

Tests:

1. `test_parity` (parametrised): each case is `(rest_method, rest_path, rest_payload, tool,
   tool_args)` and asserts `rest.status_code == 200`, `not mcp["isError"]` and `rest.json() ==
   mcp["structuredContent"]`. Cases:
   - count: `{}`; NSCLC + KRAS `aa ["G12C"]`; COADREAD + biomarker MSI `call ["high"]` with
     `breakdown ["sex", "vendor"]`; a cohort under the floor that yields `loosen[]` (NSCLC + KRAS
     G12C + ALK fusion); `any_of` (ihc CLDN18 positive or PD-L1 CPS ≥ 10 in STAD).
   - pivot: `{"pivot": {"rows": "oncotree", "cols": "year"}}`; STAD + ihc CLDN18 with pivot
     `c1.val` × `vendor`.
   - apply_op: one case per operation (`add_criterion` without an id, `remove_criterion`,
     `update_criterion`, `set_population`, `set_breakdown`, `set_pivot` with a pivot and with
     `null`, `rename`) on a small starting definition.
   - search_vocabulary: `q` = `"kras"`, `"her2"`, `""`, and `"r"` with `limit` 2.
   - describe_definition / `GET /api/schema`.
2. `test_errors_agree` (parametrised): `{"scope": "report"}` (count), a gene not in the
   vocabulary (count), a definition with no pivot (pivot), `remove_criterion` of `c9` (apply), an
   unknown op name (apply). REST is 400 or 422, MCP is `isError`, and both texts contain the
   field or id (`scope`, `gene`, `pivot`, `c9`, `op`).
3. `test_no_small_numbers_and_no_ids`: walk every successful response from `test_parity`'s cases
   on both surfaces (reuse the case list). Check that no int in 1–4 appears under
   `patients`/`denominator`/`reports`, that no string equals a synthetic `research_id` or
   `report_id` (`use_mart(...)["ids"]`), and that no options entry has `patients`.
4. `test_tools_list`: the five names exactly, no `query`; `count`'s and `pivot`'s
   `inputSchema.properties` has `definition`; `"patients"` does not appear in
   `search_vocabulary`'s `outputSchema`.
5. `test_refused_without_login` (parametrised over the routes in the acceptance list): no
   credentials gives 401 with `www-authenticate` starting `Basic`; `auth=("sean", "wrong")` gives
   401; the right credentials do not give 401. `test_health_is_open`: 200 `{"status": "Healthy"}`
   with no credentials. `test_health_unhealthy`: `app.get_db` raising gives 503
   `{"status": "unhealthy"}`.
6. `test_access_backend`: the fake JWKS from `test_cohort_api.test_access_jwt`. A missing token
   or the wrong `aud` gives 401 on `POST /api/cohort` and `POST /mcp`. A valid header token gives
   200 on both, and the audit email is the JWT's `email` claim.
7. `test_audit`: with `capsys`, run a REST count and an MCP pivot, then options, apply and
   schema. Exactly two JSON lines appear, with the fields and values in the acceptance list
   (`email == "sean"` for both surfaces).
8. `test_rate_limit`: set `app.RATE_LIMIT` to 3. Two REST counts and one MCP pivot succeed. The
   fourth (REST) is 429 with a `retry-after` header, and an MCP count is `isError` containing
   "rate limit". Options, apply and schema still return 200. Then `app.rate_limit("other@x")`
   does not raise, and with `RATE_WINDOW` monkeypatched to 0.0 the same user is admitted again.
9. `test_mcp_tool_needs_the_middleware`: `asyncio.run(app.mcp_app.call_tool("count",
   {"definition": {}}))` (no HTTP request) raises or returns an error, and never returns counts.

Run: `uv run pytest -q`. Dashboard check: n/a.

## Risks

- **MCP SDK surface.** `MCPServer`, `streamable_http_app(...)`, `session_manager` and
  `ctx.request_context.request` are from `mcp` 2.1.1 (locked). The SDK marks some neighbouring
  APIs as provisional. If an `mcp` upgrade changes them, the parity and auth tests fail loudly
  rather than letting requests through unauthenticated, because the middleware sits outside the
  SDK.
- **Stateless JSON transport.** No server-to-client streaming, sampling or resumable sessions.
  The five tools need none of them. A later MCP App (decision 10) may need sessions; it would
  then need per-session auth instead of reading the user per POST.
- **In-process limiter.** It resets on restart and is per process (see the `ponytail:` comment).
  It slows differencing down but does not prevent it. The audit log is the control of record, as
  in `COHORT_TOOL.md`.
- **Password backend over plain HTTP** on the tailnet sends the password on every request
  (`authen.py` docstring). The tailnet encrypts transport between nodes. Production moves to
  Zitadel behind Traefik/TLS.
- **DNS-rebinding protection off** for `/mcp`. Acceptable because every request must carry
  credentials that a rebinding page on another origin does not have. Revisit if a backend ever
  authenticates by network location alone.
- **FastAPI is a new dependency** (decided by ARCHITECTURE decision 5). It pulls in
  `annotated-doc`; everything else it needs is already locked.
