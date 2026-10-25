# Spec #54: follow-ups from the #35 review

Issue #54 collects eight minor and nit findings from the #35 review (`genomics-app`,
`mcp/src/uccc_genomics_mcp/app.py`) that were left open at merge. Two are tests that cannot fail,
one is an idle-connection hole in `GET /mcp`, one is third-party script on the authenticated
origin, and four are wording in the MCP instructions, tool docstrings and README.

Every fix is in `app.py`, `tests/test_app.py`, `README.md` and two sentences of the #35 spec. No
data, SQL, suppression or de-identification changes.

## Goal

1. **code-r0-1.** `test_errors_agree` checks the MCP error text after the SDK's
   `Error executing tool <name>: ` prefix, so the tool name can no longer satisfy the check.
2. **code-r0-2 / security-r0-1.** `test_mcp_tool_needs_the_middleware` fails unless the in-process
   `count` call raises `ToolError` with "not authenticated" (the `_mcp_user` fail-closed path).
3. **code-r0-3.** An authenticated `GET /mcp` gets `405 Method Not Allowed` with `Allow: POST`
   instead of opening the SDK's standalone SSE stream. The MCP Streamable HTTP spec allows this:
   a server that offers no SSE stream at the endpoint answers GET with 405.
4. **security-r0-2.** No Swagger UI: `FastAPI(docs_url=None)`. `/api/openapi.json` stays.
5. **ux-r0-1.** The MCP `INSTRUCTIONS` and the `count` docstring say what `patients`,
   `denominator` and `reports` count, and that a patient with reports from both vendors counts
   once.
6. **ux-r0-2.** The `search_vocabulary` docstring states the `q` rules, the 50-result cap and what
   `field` and `parent` mean.
7. **ux-r0-3.** The README says `--auth none` asks for no login.
8. **ux-r0-4.** The README says that a count or pivot the cohort module rejects still uses the
   rate limit, and a test pins it. (This is the issue's "smaller change": document, don't
   reorder.)

## Non-goals

- No change to `cohort/`, `saved.py`, `authen.py`, `server.py`, `cohort_api.py`, the dashboard,
  `web/`, `sql/`, `deid.py` or systemd units. **`research_id` and `report_id` are untouched**:
  nothing here reads or computes them.
- No new output path and no change to what any existing one returns. All numbers still come from
  `cohort.count` / `cohort.pivot`, already suppressed (`MIN_CELL = 5`, secondary suppression,
  whole-cohort rule). The 405 and the removed docs page return no data.
- `web/openapi.json` and `web/src/api.gen.ts` do not change: the new `GET /mcp` route is
  `include_in_schema=False`, and `docs_url` does not affect `app().openapi()`.
  `test_openapi_snapshot` must still pass without running `bun run gen`.
- No reordering of `rate_limit` and validation in `run_count` / `run_pivot`.
- No change to `DELETE /mcp` or other methods: the SDK already answers them without holding a
  connection open.
- No vendored Swagger UI assets. Interactive docs can come back later from local static files if
  someone needs them.
- No new dependencies.

## Design

### `mcp/src/uccc_genomics_mcp/app.py`

**`INSTRUCTIONS`.** Replace the sentence `"Counts are distinct patients. "` with:

```text
patients, denominator, the funnel and years count distinct patients across Caris and FMI (a patient with reports from both vendors counts once). A breakdown or pivot cell counts the patients with a report having that value, so one patient can be in several cells and cells need not add up to patients. reports counts reports.
```

The rest of the string is unchanged. "Counts once" holds for the totals because `research_id` is the same keyed
hash for the same patient across vendors (README, "De-identification").

**`count` docstring.** Append one sentence:

```text
`denominator` is the patients in the population (in a breakdown cell: the population's patients with that value), the base for a percentage; `reports` counts reports, not patients.
```

This matches `cohort/suppress.py`: `CountResult.denominator` is funnel step 0 and
`BreakdownCell.denominator` comes from `RawCount.denominators[dim][value]` (population patients).

**`search_vocabulary` docstring.** Replace it with:

```text
Find the vocabulary values (genes, protein changes, oncotree codes, markers, ...) that match
free text, to put into a cohort definition. Returns values only, no counts. `q` is a
case-insensitive substring of the value, at most 100 characters; an empty `q` returns nothing
unless `field` is given (then that field's values). At most 50 results (`limit` is clamped to
1-50). Each entry's `field` names the definition field the value goes in (e.g. `alteration.gene`,
`alteration.aa`) and `parent` the gene, biomarker or IHC marker it belongs under (e.g. `KRAS` for
an `alteration.aa` value); pass `field` and `parent` back to list one field's values.
```

These are the rules `Vocabulary.search` already applies (`cohort/vocabulary.py`: strip and lower
`q`; `len(q) > 100` or empty `q` with no `field` gives `[]`; `limit = max(1, min(limit, 50))`) and
`VocabEntry.parent` (`alteration.aa` → gene, `biomarker.call` → name, `ihc.clone`/`ihc.call` →
marker). Note the issue's suggested "q must be non-empty" is not quite right: empty `q` with
`field` lists that field.

**`GET /mcp`.** Inside `app()`, with the other routes and **before**
`application.router.routes.extend(sub.routes)`:

```python
    @application.get("/mcp", include_in_schema=False)
    def get_mcp():
        """No standalone SSE stream (stateless JSON): the MCP spec's answer is 405."""
        return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "POST"})
```

Starlette tries routes in order. For GET this `APIRoute` is a full match and wins. For POST it is
only a partial (method) match, so the router goes on to the SDK's `Route("/mcp")`, which has no
method list, and POST behaves exactly as before. Checked against FastAPI 0.162.0 / Starlette 1.6.0
(locked). `RequireUser` still runs first, so an unauthenticated `GET /mcp` stays 401.

**Docs.** In the `FastAPI(...)` call change `docs_url="/api/docs"` to `docs_url=None`. Keep
`openapi_url="/api/openapi.json"` and `redoc_url=None`. With `docs_url=None` FastAPI also does not
register the OAuth2 redirect route. An authenticated `GET /api/docs` then falls through to the
static mount (404) or, without `--static`, to 404.

### `tests/test_app.py`

- **`test_errors_agree`**: last line becomes
  `assert word in m["content"][0]["text"].split(": ", 1)[1]`. With mcp 2.1.1 the text is
  `Error executing tool <tool>: <message>`, so the split leaves the message, e.g.
  `pivot: the definition has no pivot`, `criteria.c1.gene: 'NOTAGENE' is not in the vocabulary`.
  All five current cases still pass after the split (checked by printing the messages).
- **`test_mcp_tool_needs_the_middleware`** becomes:

  ```python
  def test_mcp_tool_needs_the_middleware(ids):
      with pytest.raises(ToolError, match="not authenticated"):
          asyncio.run(app.mcp_app.call_tool("count", {"definition": {}}))
  ```

  with `from mcp.server.mcpserver.exceptions import ToolError` at the top (the class `app.py`
  imports). `MCPServer.call_tool` documents that it raises `ToolError` when the tool raises one;
  in-process the message is `Error executing tool count: not authenticated`, and `match` is a
  `re.search`.
- **`test_mcp_get_is_405`** (new, next to `test_refused_without_login`):

  ```python
  def test_mcp_get_is_405(client):
      # json first: without the route the SDK answers 406 here; the event-stream request would hang
      for accept in ("application/json", "text/event-stream"):
          r = client.get("/mcp", auth=AUTH, headers={"accept": accept})
          assert (r.status_code, r.headers["allow"]) == (405, "POST")
  ```

  The `application/json` request comes first so a regression fails on a 406 assertion before the
  `text/event-stream` request could open the endless stream.
- **`test_refused_without_login`**: update the comment above `kw` (the SSE stream it describes no
  longer opens); keep the `accept: application/json` header. Remove `("GET", "/api/docs")` from
  `GATED`: the route no longer exists, and unknown paths are already covered by
  `("GET", "/no/such/path")`.
- **`test_no_swagger_ui`** (new):

  ```python
  def test_no_swagger_ui(client):
      assert client.get("/api/docs", auth=AUTH).status_code == 404
      assert client.get("/api/openapi.json", auth=AUTH).status_code == 200
  ```

- **`test_rejected_requests_use_the_rate_limit`** (new, after `test_rate_limit`):

  ```python
  def test_rejected_requests_use_the_rate_limit(client, monkeypatch):
      monkeypatch.setattr(app, "RATE_LIMIT", 1)
      assert rest(client, "POST", "/api/pivot", {}).status_code == 400   # DefinitionError: no pivot
      assert rest(client, "POST", "/api/cohort", {}).status_code == 429
  ```

  It pins the README sentence below. A body that fails schema validation (422 on REST, the SDK's
  argument validation on MCP) never reaches `run_count` / `run_pivot`, so it does not use the
  limit. The test does not need to pin that.

### `README.md` ("Cohort app (genomics-app)")

- `(OpenAPI at `/api/docs`)` → `(OpenAPI schema at `/api/openapi.json`; no Swagger UI)`.
- `` (`--auth access|password|none`) `` → `` (`--auth access|password|none`; `none`: no login,
  local dev only) ``.
- After "`count` and `pivot` are limited to 60 a minute per user across both surfaces", add:
  "(a count or pivot the cohort module rejects, such as an unknown vocabulary value or a pivot
  of a definition that has no pivot, still uses the limit; a body that fails schema validation
  does not)".
- After "(Streamable HTTP, stateless) at `/mcp`" add "(POST only; `GET /mcp` is 405, no SSE
  stream)".
- The example comment `# http://<tailnet-addr>:8092/api/docs, ...` → `/api/openapi.json`.

### `docs/specs/35-genomics-app-fastapi-rest-and-mcp-over.md`

The #35 spec records the old behaviour in two places this change contradicts. Edit those two
only (the rest of the spec is history):

- `docs_url="/api/docs"` in "REST routes" → `docs_url=None` with "(#54: no Swagger UI; it loaded
  CDN script without SRI)".
- "Stateless JSON means no sessions and no SSE: each POST is self-contained" → append "`GET /mcp`
  is answered 405 by an app route ahead of the SDK's (#54), so no standalone SSE stream opens."

`docs/ARCHITECTURE.md`, `dashboard/COHORT_DISCOVERY.md`, `dashboard/COHORT_TOOL.md` and `PLAN.md`
do not mention `/api/docs` or `GET /mcp`; they need no change.

## Acceptance criteria

- [ ] `test_errors_agree` checks the MCP text after the first `": "`; all five cases pass.
- [ ] `test_mcp_tool_needs_the_middleware` uses `pytest.raises(ToolError, match="not
      authenticated")`, has no `except Exception` and no `getattr` defaults.
- [ ] Authenticated `GET /mcp` with `accept: application/json` and with `accept:
      text/event-stream` returns 405 with `Allow: POST` (`test_mcp_get_is_405`). Unauthenticated
      `GET /mcp` and `POST /mcp` are still 401. `POST /mcp` tool calls still work (parity tests).
- [ ] `GET /api/docs` with credentials is 404; `GET /api/openapi.json` is 200
      (`test_no_swagger_ui`).
- [ ] `test_openapi_snapshot` passes with `web/openapi.json` unchanged (`git diff --stat web/`
      empty).
- [ ] `INSTRUCTIONS` contains "a patient with reports from both vendors counts once" and
      "cells need not add up to patients", "reports counts reports", and no longer contains "Counts are distinct patients.".
- [ ] The `count` docstring explains `denominator` and `reports`; the `search_vocabulary`
      docstring states the 100-character and empty-`q` rules, the 50-result cap and `field` /
      `parent`. Both show in `tools/list` descriptions.
- [ ] README: `none` reads as no login; rejected counts/pivots use the limit; `/api/docs`
      replaced by `/api/openapi.json`; `GET /mcp` is 405.
- [ ] `test_rejected_requests_use_the_rate_limit` passes.
- [ ] The two #35 spec sentences are updated as above.
- [ ] `uv run pytest -q` passes. Dashboard and web checks: n/a (no change under `dashboard/` or
      `web/`, and the API models and OpenAPI document are unchanged).

## Test plan

All in `tests/test_app.py`, on the synthetic #34 mart that the module fixture `mart_file` builds
in a temp dir (`build_mart` / `write_mart` from `test_cohort.py`). No `$DATA`, no raw files, no
PHI file, no network, no Postgres needed (`DATABASE_URL` is unset by the `client` fixture).

```bash
uv run pytest -q tests/test_app.py
uv run pytest -q
git diff --stat web/            # empty
```

New or changed tests: `test_errors_agree`, `test_mcp_tool_needs_the_middleware`,
`test_mcp_get_is_405`, `test_refused_without_login` (GATED list and comment), `test_no_swagger_ui`,
`test_rejected_requests_use_the_rate_limit`.

## Risks

- **MCP clients that GET first.** A client that opens `GET /mcp` before POSTing now gets 405. The
  Streamable HTTP spec names 405 as the server's way to say "no SSE stream here", and clients fall
  back to POST-only. Before this change the same client got an idle stream that carried nothing.
- **Error prefix is SDK text.** The `split(": ", 1)[1]` relies on mcp 2.1.1's
  `Error executing tool <name>: ` prefix. If an upgrade drops the prefix, the split takes the
  message's own first `": "` and the check gets stricter, not weaker (or `IndexError` if there is
  no `": "`, a loud failure).
- **Unknown-op case stays loose.** For `{"op": "explode"}` the message after the prefix is
  pydantic's `1 validation error for apply_opArguments\nop\n ...`; `"op"` also appears in the
  model name `apply_opArguments`. The check is no longer satisfied by the tool prefix, as the
  issue asks, but this one case is still weak. Left as is to keep the issue's fix.
- **No interactive API docs.** Developers lose Swagger UI. `/api/openapi.json` and the generated
  `web/src/api.gen.ts` remain the API description.
- **Rejected requests use the limit.** Documented, not changed: a user who sends many invalid
  definitions can hit 429 sooner. That also slows probing, which is acceptable.
