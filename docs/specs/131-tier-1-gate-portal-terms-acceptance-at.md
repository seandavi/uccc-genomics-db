# #131 Tier 1 gate: portal terms acceptance at first login

Design record: `docs/HONEST_BROKER.md` (decision 3: "The Tier 1 gate is terms acceptance"; text in §
"Portal terms"). Part of #16, after #132. Identified data never enters Postgres, logs, the repo or
GitHub. This change stores only who accepted which terms version, and when.

## Goal

1. After sign-in, a user who has not accepted the **current** terms version sees the terms as a full
   page, with **Accept** and **Sign out**, before Discover or any other gated page.
2. Acceptance is stored in Postgres as `(sub, terms_version, accepted_at)`. Changing the terms means
   bumping `TERMS_VERSION`, and then every user is asked again.
3. Until the user accepts, REST (`/api/*`) and MCP (`/mcp`) answer **403** with a clear message.
4. An unaccepted user can reach only:
   - the accept route (`POST /api/terms/accept`)
   - sign-out (`POST /auth/logout`, under `--auth authentik`)
   - the routes that are already open: `/api/health`, `GET /api/public/summary`, the landing page
     `/`, `/assets/*`, and `/auth/login` and `/auth/callback`

   Every other route refuses them.

## Non-goals

- Login logging and the query log beyond today's stdout audit line. Tier 1's "Login and query log"
  is a later issue.
- Revoking an acceptance, or an admin view of who accepted. The rows are in Postgres for whoever
  needs them.
- Any change to Discover (`web/`). Discover already shows a failed request's `detail`
  (`describeError` returns `e.message` for statuses other than 401 and 429), so the 403 message reaches the user
  unchanged. The new routes are `include_in_schema=False`, so `web/openapi.json` and `api.gen.ts`
  don't change.
- Editable terms text (env, database or file). The text is a code constant. Changing it is a code
  change plus a `TERMS_VERSION` bump.
- A separate `GET /terms` route. The terms page is served in place at whatever gated address the
  browser opened (see Design § 3). That keeps the `#d=` share-link fragment and needs no `next`
  parameter, so it opens no redirect.
- The cohort API (`cohort_api.py`, Cloudflare Access) and the tailnet MCP server (`server.py`). The
  gate applies to `genomics-app` only.
- `deid`, the DuckDB files, the mart, suppression. Nothing here reads or writes them.

## Decisions taken (from the issue, design and supervisor)

- **Terms text** is HONEST_BROKER.md § "Portal terms" verbatim, with `[health system]` filled in as
  **UCHealth** (supervisor, 2026-10-30). `TERMS_VERSION = "2026-10-30"`. The PR body must open with:
  "Portal terms wording (incl. 'UCHealth') needs Sean/privacy office sign-off before merge."
- **Where the gate is off.** Acceptance lives in Postgres.
  - `--auth none` and `--auth password` (development stand-ins) without a database: the gate is
    off, and everything else keeps working as it does today. With a database, the gate is on in
    every mode.
  - `--auth access` and `--auth authentik`: `main()` refuses to start without `DATABASE_URL`. If one
    of these modes somehow runs without a database (tests that build `app.app()` directly), the gate
    fails **closed** with 503.

## Design

### 1. New module `mcp/src/uccc_genomics_mcp/terms.py`

```python
"""Portal terms: the Tier 1 gate (docs/specs/131-*.md, text from docs/HONEST_BROKER.md § "Portal terms").

A signed-in user who has not accepted TERMS_VERSION gets the terms page (a browser opening a page) or a 403
(/api/*, /mcp) from app.RequireUser. Acceptance is one row per (sub, terms_version) in Postgres. To change
the terms, edit TERMS_TEXT and bump TERMS_VERSION: everyone is asked again, and older rows stay as the
record. Holds staff `sub`s only, never patient data.
"""
import html
import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from starlette.responses import HTMLResponse

from uccc_genomics_mcp import authen, saved

TERMS_VERSION = "2026-10-30"
TERMS_TEXT = (
    "The clinical genomics portal contains de-identified, date-shifted data belonging to UCHealth and made "
    "available through the University of Colorado Cancer Center. Access is limited to approved cancer center "
    "members for research planning, feasibility, and cohort discovery. By using the portal, I agree not to "
    "attempt to identify any individual, link portal data with other sources to re-identify individuals, or "
    "share screenshots or exports beyond my study team. Identifiable data is available only through an "
    "approved honest-broker request tied to an active IRB authorization. Queries are logged.")
TERMS_REQUIRED = ("You have not accepted the current portal terms. Open /discover in a browser (or reload "
                  "it) to read and accept them.")
ACCEPT_PATH = "/api/terms/accept"
DEV_MODES = ("none", "password")

terms_acceptance = sa.Table(
    "terms_acceptance", saved.metadata,
    sa.Column("sub", sa.Text, primary_key=True),             # authen.User.sub
    sa.Column("terms_version", sa.Text, primary_key=True),
    sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

# ponytail: positive answers only, per process; an acceptance is never revoked and a bump changes the key.
# Grows by one entry per user per version.
_accepted: set[tuple[str, str]] = set()
```

The rules below matter more than the code:

- **Read `TERMS_VERSION` at call time** in every function, never at import time. No default
  arguments, and no module-level strings built from it. A test monkeypatches it to simulate a
  bump.
- **Fail closed.** Only `gate_on()` can turn the gate off. Any error from `accepted()` refuses the
  request.

```python
def gate_on() -> bool:
    """False only for a development stand-in (--auth none|password) with no database: there is nowhere to
    record acceptance. main() refuses --auth access|authentik without DATABASE_URL."""
    return saved._engine is not None or authen.AUTH["mode"] not in DEV_MODES


async def accepted(sub: str) -> bool:
    """True if sub accepted the current TERMS_VERSION. saved.Unavailable without a database."""
    key = (sub, TERMS_VERSION)
    if key in _accepted:
        return True
    async with saved._begin() as conn:
        found = (await conn.execute(sa.select(terms_acceptance.c.sub).where(
            terms_acceptance.c.sub == sub, terms_acceptance.c.terms_version == TERMS_VERSION))).first()
    if found:
        _accepted.add(key)
    return found is not None


async def accept(sub: str) -> None:
    """Record that sub accepted the current TERMS_VERSION; accepting again keeps the first accepted_at."""
    async with saved._begin() as conn:
        await conn.execute(insert(terms_acceptance).values(sub=sub, terms_version=TERMS_VERSION)
                           .on_conflict_do_nothing())
    _accepted.add((sub, TERMS_VERSION))


def page(sign_out: bool) -> HTMLResponse:
    """The full-page terms for a signed-in browser that hasn't accepted, served in place (status 403,
    Cache-Control: no-store). Accept POSTs JSON to ACCEPT_PATH and reloads, so the address and its #fragment
    stay. Sign out (authentik only) POSTs /auth/logout and goes to the returned url, as Discover does."""
```

`page()` specifics:

- Built on `authen._HEAD`, the same head, `lang`, viewport and `<h1>` as the sign-in pages.
- Then `<h2>Portal terms</h2>`, `<p>{html.escape(TERMS_TEXT)}</p>` and
  `<p>Version {html.escape(TERMS_VERSION)}</p>`.
- Then `<p><button type="button" id="accept">Accept</button>`. When `sign_out` is true, add
  ` <button type="button" id="sign-out">Sign out</button>`. Close with `</p>` and
  `<p id="error" role="alert"></p>`.
- Then one inline `<script>`. The version is embedded with `json.dumps(TERMS_VERSION)`. The script:
  - Accept runs
    `fetch("/api/terms/accept", {method: "POST", credentials: "same-origin", headers: {"content-type": "application/json"}, body: JSON.stringify({version: V})})`.
    On `r.ok` it calls `location.reload()`. Otherwise it sets `#error`'s text to the response's
    `detail`, falling back to "Accepting failed; try again." On a network error it shows
    "Network error; try again.".
  - Sign out (when present) runs
    `fetch("/auth/logout", {method: "POST", credentials: "same-origin"})`, then `.json()`, then
    `location.assign(j.url)`. On failure it puts "Sign-out failed; try again." in `#error`.
- `HTMLResponse(..., status_code=403, headers={"Cache-Control": "no-store"})`.

The page must not open the user's other data. It carries no counts, no `sub` and no email.

### 2. Migration `mcp/src/uccc_genomics_mcp/migrations/versions/0003_terms_acceptance.py`

Use the same header style as `0002`: `revision = "0003"`, `down_revision = "0002"`, and the
docstring "portal terms acceptance (#131)".

```python
def upgrade() -> None:
    op.create_table(
        "terms_acceptance",
        sa.Column("sub", sa.Text(), nullable=False),
        sa.Column("terms_version", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("sub", "terms_version"))


def downgrade() -> None:
    op.drop_table("terms_acceptance")
```

`migrations/env.py`: change the registering import to
`from uccc_genomics_mcp import broker, terms  # noqa: F401  registers the broker and terms tables on saved.metadata`.
With that import, `command.check` (in the `pg_url` test fixture) sees no drift.

### 3. The gate in `app.py`

- Add `terms` to the import line: `from uccc_genomics_mcp import authen, broker, cohort, public, saved, terms`.
- In `RequireUser.__call__`, replace the final `await self.app(scope, receive, send)` (the one after
  `scope["state"] = ...`) with the block below. Authentication stays exactly as it is, so the gate
  runs only for a user who is already signed in:

```python
        scope["state"] = {**scope.get("state", {}), "user": u}   # a fresh dict per request
        path = scope["path"]
        if path != terms.ACCEPT_PATH and terms.gate_on():
            try:
                ok = await terms.accepted(u.sub)
            except saved.Unavailable as e:   # --auth access|authentik built without a database: closed
                await JSONResponse({"detail": str(e)}, status_code=503)(scope, receive, send)
                return
            if not ok:
                if scope["method"] == "GET" and not path.startswith("/api/") and path != "/mcp":
                    response = terms.page(sign_out=authen.AUTH["mode"] == "authentik")
                else:
                    response = JSONResponse({"detail": terms.TERMS_REQUIRED}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
```

  Any other exception from `accepted()` (Postgres down, or the table missing because migration
  `0003` wasn't run) propagates and becomes a 500. It still never serves the route.
- Update `RequireUser`'s docstring, and the module docstring's sentence about `RequireUser`. Add
  one clause: "then refuses a signed-in user who has not accepted the current portal terms
  (`terms.py`): the terms page for a browser navigation, 403 for /api/* and /mcp; only
  `POST /api/terms/accept` is exempt".
- New model, next to `Me`:

```python
class TermsAccept(BaseModel):
    version: str = Field(max_length=64)   # the TERMS_VERSION the page showed
```

- New route, registered next to `/api/me`:

```python
    @application.post(terms.ACCEPT_PATH, include_in_schema=False)
    async def post_terms_accept(body: TermsAccept, u: authen.User = Depends(user)) -> TermsAccept:
        if body.version != terms.TERMS_VERSION:
            raise HTTPException(409, "the portal terms have changed; reload the page to read the current version")
        await terms.accept(u.sub)
        return TermsAccept(version=terms.TERMS_VERSION)
```

  `saved.Unavailable` from `accept()` maps to 503 through the existing handler.
- The MCP surface needs no per-tool change. `/mcp` goes through `RequireUser`, so an unaccepted
  caller gets HTTP 403 `{"detail": TERMS_REQUIRED}` before the MCP SDK runs.
- `INSTRUCTIONS`: add one sentence at the end: "A 403 saying the portal terms are not accepted
  means the user must open /discover in a browser and accept them; tools can't do it."
- `main()`: after `authen.configure(args.auth)`, and before `uvicorn.run`:

```python
    if args.auth in ("access", "authentik") and saved.database_url() is None:
        raise SystemExit(f"--auth {args.auth} needs DATABASE_URL (in .env): portal terms acceptance is "
                         "recorded in Postgres")
```

  Production (`deploy/compose.yaml`) already requires `DATABASE_URL`, so nothing changes there.

**CSRF.**
- The accept route needs a signed-in user, takes JSON only and only records an acceptance.
- Under `authentik`, the session cookie is `SameSite=Lax`, so a cross-site POST carries no cookie.
- FastAPI 0.162 parses a body as JSON only when `content-type` is `application/json` (or `+json`).
  It checked that in `fastapi/routing.py`. A cross-site `<form>` (`text/plain`) gets a 422. A
  cross-site `fetch` with `application/json` needs a CORS preflight, and the app answers none.
- The 409 on a stale version stops a click on an old page from recording a version the user never
  saw.

### 4. Docs (same PR)

- **README.md**, § Cohort app (genomics-app). Add a paragraph **Portal terms (#131)** covering:
  - the gate, and which routes it leaves open
  - the 403 message
  - where the text and version live (`terms.py`) and how to bump them (edit `TERMS_TEXT`, bump
    `TERMS_VERSION`, deploy: everyone is asked again)
  - the table `terms_acceptance(sub, terms_version, accepted_at)` from migration `0003`
  - when the gate is off: dev stand-ins without a database
  - that `--auth access|authentik` refuse to start without `DATABASE_URL`
  - that an MCP client's user accepts once in a browser

  In § Production (container), say that the release with `0003` needs
  `uv run alembic -c mcp/alembic.ini upgrade head` **before** the new image starts. Without it every
  signed-in request is a 500.
- **docs/ARCHITECTURE.md**:
  - Decision 7: add `terms_acceptance` to the Postgres tables.
  - Decision 8: add one sentence. After sign-in, the app refuses a user who hasn't accepted the
    current portal terms (HONEST_BROKER.md decision 3; `terms.py`, #131).
- **docs/HONEST_BROKER.md**, under § "Portal terms": add one line. "As built (#131): the text is
  `TERMS_TEXT` in `mcp/src/uccc_genomics_mcp/terms.py`, with `[health system]` = UCHealth (pending
  privacy-office review), version `TERMS_VERSION`; acceptance is `terms_acceptance(sub,
  terms_version, accepted_at)`."
- **AGENTS.md**:
  - Layout: add the line `terms.py      portal terms gate (Tier 1): text, version, acceptance in Postgres`.
  - In the rule "Don't weaken Cloudflare Access", after the open-routes sentence, add: "Every other
    route also refuses a signed-in user who hasn't accepted the current portal terms (`terms.py`);
    only `POST /api/terms/accept` is exempt."

No other doc contradicts this change.

### Data, small cells, ids

- No DuckDB table, column or vendor field changes. No PLAN.md mapping applies.
- Nothing new leaves the de-id file. The terms page and the 403 carry fixed text only, with no
  counts. The small-cell rules of `cohort/` are untouched.
- `research_id` and `report_id` stability: unaffected. `deid.py`, the keys and hashing are not
  touched.
- Postgres gains `terms_acceptance`, which holds staff `sub` values and dates only.

## Acceptance criteria

- [ ] `terms.py` exists with `TERMS_VERSION = "2026-10-30"` and the HONEST_BROKER.md text with
  "UCHealth". It also has `TERMS_REQUIRED`, `ACCEPT_PATH`, `terms_acceptance`, `gate_on()`,
  `accepted()`, `accept()` and `page()`, as specified.
- [ ] Migration `0003` creates `terms_acceptance(sub, terms_version, accepted_at)` with
  PK `(sub, terms_version)`. It downgrades cleanly, and `alembic check` shows no drift.
- [ ] A signed-in, unaccepted user gets 403 on every `APIRoute` of `app.app()` except
  `ACCEPT_PATH` and the open ones, and on `POST /mcp`, `GET /mcp`, `/discover`, `/discover.html`,
  `/index.html` and an unknown path. JSON routes carry `{"detail": TERMS_REQUIRED}`. A browser
  `GET` of a non-`/api`, non-`/mcp` path gets the HTML terms page with `Cache-Control: no-store`.
- [ ] `/api/health`, `GET /api/public/summary`, `/`, `/assets/*` and (under authentik)
  `/auth/login`, `/auth/callback` and `POST /auth/logout` behave as before for an unaccepted user.
- [ ] `POST /api/terms/accept` behaves as follows:
  - with `{"version": TERMS_VERSION}`: 200, and the user then reaches every gated route
  - with another version: 409, and the user is still gated
  - a `text/plain` body: 422, and the user is still gated
  - with no login: 401
- [ ] Bumping `TERMS_VERSION` gates an accepted user again. Their old row stays.
- [ ] In Postgres, accepting writes one row. Accepting again keeps one row with the first
  `accepted_at`, and `accepted()` reads it back after the in-process cache is cleared.
- [ ] `gate_on()`:
  - false only for `none`/`password` without a database
  - `access`/`authentik` without a database answer 503 on gated routes, never 200
  - `main()` exits naming `DATABASE_URL` for `--auth access|authentik` without it
- [ ] The terms page has Sign out only under `--auth authentik`.
- [ ] Every existing test passes with its meaning kept (fixtures updated as below).
  `web/openapi.json` is unchanged.
- [ ] README, ARCHITECTURE.md, HONEST_BROKER.md and AGENTS.md are updated as in Design § 4.

## Test plan

There is a new file, `tests/test_terms.py`, and some existing fixtures change.

The tests use the synthetic #34 mart from `test_app` (`ids`, `mart_file` fixtures) and, for the
Postgres part, the throwaway database of `test_saved` (`pg_url`, `clean`; skipped without
`TEST_DATABASE_URL`). They never touch `$DATA/raw`, the PHI file, the real de-id file or the real
`DATABASE_URL`. Users are synthetic (`a@x.edu`).

**Existing fixtures** (so tests that aren't about the gate keep their meaning):

- `tests/test_saved.py`:
  - `clean`: add `terms_acceptance` to the `TRUNCATE` list, and
    `monkeypatch.setattr(terms, "_accepted", set())`.
  - `sclient`: also `monkeypatch.setattr(terms, "accepted", _yes)`, where `async def _yes(sub): return True`.
- `tests/test_broker.py`, `bclient`: the same `accepted` bypass.
- `tests/test_authen.py`, `issuer`: the same bypass. Authentik there runs without a database, so the
  gate would otherwise answer 503.
- `tests/test_app.py`, `test_access_backend`: the same bypass, because the mode switches to
  `access`. The `client` fixture (`password`, no database) needs nothing: the gate is off there,
  which `test_parity` and the other tests continue to exercise.

**`tests/test_terms.py`, without Postgres.** Fixture `gate(ids, tmp_path, monkeypatch)`:

- `monkeypatch.delenv("DATABASE_URL")`.
- Static dir as in `test_app.client`.
- `authen.user` faked from an `x-test-user` header, as in `bclient`.
- `monkeypatch.setitem(authen.AUTH, "mode", "access")`, so the gate is on without a database.
- `terms.accepted` and `terms.accept` replaced by an in-memory set keyed `(sub, terms.TERMS_VERSION)`,
  with the version read at call time.
- Yields a `TestClient(app.app(static))`.

Tests:

1. `test_unaccepted_user_is_refused_everywhere`:
   - Every `APIRoute` of `app.app()`, with path parameters filled as in
     `test_only_health_and_public_summary_are_open`, except `ACCEPT_PATH`, `/api/health` and
     `/api/public/summary`, answers 403 with `detail == TERMS_REQUIRED`.
   - So do `POST /mcp` (a `tools/call count` body), `GET /mcp`, `POST /api/cohort`, and every
     `test_app.GATED` entry.
   - The GET navigations (`/discover`, `/discover.html`, `/index.html`, `/no/such/path`) give
     `text/html` containing `TERMS_TEXT` (escaped), `TERMS_VERSION` and `id="accept"`.
2. `test_open_routes_stay_open_for_an_unaccepted_user`:
   - `/api/health` → 200.
   - `/api/public/summary` → 200.
   - `/` → the landing HTML.
   - `/assets/app.js` → 200.
3. `test_accept_opens_every_route`: POST `ACCEPT_PATH` with `{"version": TERMS_VERSION}` → 200.
   Then:
   - every `GATED` entry is no longer 403
   - `/discover` serves `<p>discover</p>`
   - the `/mcp` count gives 200 and not `isError`
4. `test_accept_wrong_version_is_409`. The user stays gated.
5. `test_accept_needs_json`: the right body sent as `content=` with `content-type: text/plain` → 422.
   The user stays gated.
6. `test_accept_needs_login` → 401. Fake user: no header raises `PermissionError`.
7. `test_version_bump_asks_again`: accept, then `monkeypatch.setattr(terms, "TERMS_VERSION", "2099-01-01")`.
   `/api/me` → 403, and the page shows `2099-01-01`.
8. `test_page`: unit tests on `terms.page(...)`:
   - `terms.page(True)` contains `id="sign-out"`; `terms.page(False)` doesn't
   - status 403, `cache-control: no-store`
   - `lang="en"` and the viewport meta are present
9. `test_gate_on`, parametrized over the four modes × engine set / unset, monkeypatching
   `saved._engine` to a sentinel or `None`. The result is false only for `none` and `password`
   without an engine.
10. `test_fails_closed_without_a_database`: with the real `terms.accepted` (no fake), mode `access`
    and no engine, `/api/me` → 503, never 200.
11. `test_main_needs_a_database`, for `access` (env `ACCESS_TEAM`/`ACCESS_AUD` set) and for
    `authentik` (the five `AUTHENTIK_*`/`APP_BASE_URL`/`SESSION_SECRET` vars set), each with
    `DATABASE_URL` unset:
    - `app.main(["--auth", mode])` raises `SystemExit` whose text contains `DATABASE_URL`
    - `uvicorn.run` is monkeypatched to fail the test if it is reached
    - `authen.AUTH` is monkeypatched to a copy first
12. `test_signed_in_authentik_user_sees_terms_with_sign_out`:
    - Uses `test_authen`'s `issuer`/`c` fixtures and `sign_in`, then re-monkeypatches `accepted`
      and `accept` to the in-memory store, overriding `issuer`'s bypass.
    - `GET /discover` → 403 HTML with `id="sign-out"`.
    - `POST /auth/logout` → 200.
    - After accepting, `GET /discover` → 200.

**`tests/test_terms.py`, with Postgres** (`clean` fixture; skipped without `TEST_DATABASE_URL`):

13. `test_acceptance_is_stored`:
    - `asyncio.run` with `saved.start(saved.database_url())` / `saved.stop()` around the calls, or a
      `TestClient` lifespan.
    - `accepted("a@x.edu")` is False.
    - After `accept`, `sql("SELECT * FROM terms_acceptance")` is one row with
      `sub == "a@x.edu"`, `terms_version == TERMS_VERSION` and a non-null `accepted_at`.
    - A second `accept` leaves one row with the same `accepted_at`.
    - After `terms._accepted.clear()`, `accepted` is True (read from the database).
    - After a version bump, False. The old row remains.
14. `test_gate_end_to_end_with_postgres`:
    - A client like `sclient`, but without the bypass, in mode `password`. The gate is on because
      there is a database.
    - `GET /api/saved` → 403.
    - `POST ACCEPT_PATH` → 200.
    - `GET /api/saved` → 200.
15. `test_migration_0003_round_trip`:
    - `command.downgrade(cfg, "0002")`: the table `terms_acceptance` is gone (`to_regclass` is
      null).
    - `command.upgrade(cfg, "head")`: it is back.

**Checks to run:**
- `uv run pytest -q`.
- With `TEST_DATABASE_URL` against a throwaway Postgres, `uv run pytest -q` again.
- `cd dashboard && npm ci && npm test`: n/a, Python only.
- `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`: run it anyway to show
  `openapi.json` and `api.gen.ts` are untouched. `test_openapi_snapshot` covers this.

## Risks

- **Wording not yet approved.** The text, including "UCHealth", needs Sean's and the privacy
  office's sign-off before merge. The PR keeps `needs:human`. Later wording changes only need
  `TERMS_TEXT` edited and `TERMS_VERSION` bumped.
- **Deploy order.** If the new image starts before `alembic upgrade head` adds `terms_acceptance`,
  every signed-in request is a 500. That fails closed, but the site is down. README § Production
  says to migrate first.
- **Per-process cache.** `_accepted` caches positive answers per worker. That is correct for any
  number of workers, because acceptance is never revoked and a version bump changes the key. An
  operator who deletes rows by hand must restart the app for it to take effect.
- **MCP clients** can't accept. A Bearer-token user must accept once in a browser. The 403 message
  and `INSTRUCTIONS` say so. Production doesn't route `/mcp` publicly anyway.
- **The dev exemption.** `--auth none|password` without a database skip the gate. Both are
  development stand-ins (AGENTS.md), and `main()` makes the production modes refuse to start without
  a database.
- **No-JS browsers** can't press Accept. Discover itself needs JavaScript, so nothing is lost.
- **Mid-session bump.** A Discover tab that is open during a deploy with a new version shows the
  403 message on its next request. Reloading shows the terms page. Nothing is lost: the definition
  is in the URL fragment.
