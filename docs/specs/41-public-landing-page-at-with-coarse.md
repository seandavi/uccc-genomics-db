# Spec #41: public landing page at `/` with coarse totals; Discover moves to `/discover`

Issue #41 (rescoped by Sean, 2026-10-30): the campus app (`genomics-app`) gets a public landing
page at `/` with a few coarse totals from one public endpoint, and Discover moves behind sign-in at
`/discover`. Retiring the Cloudflare dashboard and `genomics-cohort-api` is a follow-up.

This changes three written rules, so the PR updates them (list under Docs):
AGENTS.md "Don't weaken Cloudflare Access" (genomics-app's open routes), ARCHITECTURE decision 12
(where the public totals live) and README's "Every request but `/api/health` needs a login".

## Goal

1. `GET /` is public under every `--auth` mode and serves a landing page. It says what the resource
   is and who may use it, has a **Sign in to Discover** link, and shows coarse totals from
   `GET /api/public/summary`. It uses Discover's design tokens (`web/src/styles.css`).
2. Discover is served at `/discover`, behind `authen` as `/` is today.
3. Old share links `/#d=…` keep working. The landing page's script sends any `#d=` hash to
   `/discover#d=…` with `location.replace`, both on load and on `hashchange`. A signed-in visitor
   lands in Discover. A signed-out one gets the existing sign-in page at `/discover`
   (`authen.signin_page`, which keeps the fragment) and comes back to `/discover#d=…`. The server
   never sees the fragment, so the redirect has to run in the browser.
4. `GET /api/public/summary` needs no auth and sends `Cache-Control: public, max-age=3600`. It takes
   no parameters and returns only fixed, coarse aggregates (Design §2).
5. All other `/api/*` routes, `/mcp`, `/auth/*` and `/discover` behave as before. The one exception:
   a sign-in with no usable `next` now lands on `/discover` instead of `/` (Design §3).

## Non-goals

- Retiring the Cloudflare Worker dashboard (`dashboard/`), `genomics-cohort-api`, its systemd unit
  or its Traefik route. `dashboard/` and `cohort_api.py` are not touched.
- No change to `deid.py`, `sql/*.sql`, `mart.*`, the PHI column lists or id hashing.
  `research_id` and `report_id` are not affected.
- No change to the cohort module (`cohort/`), its suppression or the MCP tools.
- The landing page makes no authenticated call. In particular it does not call `/api/me`: a
  signed-out 401 there would trigger the transport's sign-in redirect. So the button reads
  "Sign in to Discover" for signed-in visitors too (for them it simply opens Discover).
- No link from Discover's header back to `/`, no per-IP rate limit on the public endpoint (it is
  served from an in-process cache; see Risks), and no "data as of" date. The issue's field list is
  the whole response.
- No systemd unit or production hosting for `genomics-app` (still development only, README).

## Design

### 1. Routes and the auth gate (`mcp/src/uccc_genomics_mcp/app.py`)

Add, next to `RequireUser`:

```python
PUBLIC_PATHS = ("/api/health", "/api/public/summary", "/")   # open under every --auth mode


def public_path(path: str) -> bool:
    """True for the routes anyone may call: health, the public summary, the landing page and the
    built assets (hashed JS/CSS from the public repo; no data). normpath first, so
    /assets/../discover.html is not an asset."""
    return path in PUBLIC_PATHS or posixpath.normpath(path).startswith("/assets/")
```

- `RequireUser.__call__` replaces `scope["path"] == "/api/health"` with `public_path(scope["path"])`,
  keeping `authen.open_path` as it is. The method is not checked, as for `/api/health` today:
  `POST /` gets StaticFiles' 405 and `POST /api/public/summary` gets FastAPI's 405.
- `/index.html` stays gated: only the exact path `/` is open. `posixpath.normpath("//assets/x")`
  keeps the double slash, so that path is gated too.
- In `app(static_dir)`, before the `StaticFiles` mount, register `GET /discover` serving
  `<static_dir>/discover.html` with `fastapi.responses.FileResponse`
  (`include_in_schema=False, response_model=None`). Register it only when `static_dir` is set and
  `os.path.isfile(os.path.join(static_dir, "discover.html"))` is true at `app()` time. StaticFiles
  also serves `/discover.html` (gated). Don't use a `discover/index.html` directory: StaticFiles
  would answer `/discover` with a redirect to an absolute `http://` URL built from the request,
  which is wrong behind a TLS proxy.
- Update the module docstring and the `RequireUser` docstring: the open routes are `/api/health`,
  `/api/public/summary`, `/`, `/assets/*` and, under authentik, the `/auth/*` sign-in paths.

New route (in `app()`, with the others; it stays in the OpenAPI schema):

```python
@application.get("/api/public/summary")
def get_public_summary(response: Response) -> public.PublicSummary:
    """Open: fixed coarse totals for the landing page. No parameters; every count is floored at 5
    and rounded to the nearest 10 (public.coarse)."""
```

- It calls `public.summary()`. On success it sets `response.headers["Cache-Control"] =
  "public, max-age=3600"`. `Response` is `fastapi.Response`; FastAPI injects it when it is a
  parameter, and it does not show in the schema.
- On any exception it prints `f"public summary: {e}"` to stderr and returns
  `JSONResponse({"detail": "totals unavailable"}, status_code=503)`, without the error text (as
  `/api/health` does).
- It has no query, path or body parameters. Query strings are ignored, so `?oncotree=X` returns the
  same body.

### 2. The summary (`mcp/src/uccc_genomics_mcp/public.py`, new)

```python
"""The public landing page's totals (docs/specs/41-*.md): fixed, unfilterable aggregates over mart.report,
each floored at MIN_CELL and rounded to the nearest PUBLIC_ROUND. No parameters reach SQL."""
import os
from pydantic import BaseModel
from uccc_genomics_mcp.cohort.suppress import MIN_CELL, YearCount
from uccc_genomics_mcp.server import DEID_DB, get_db

PUBLIC_ROUND = 10


class PublicSummary(BaseModel):
    patients: int | None      # distinct research_id; null = under MIN_CELL
    reports: int | None       # rows of mart.report
    tumor_types: int | None   # oncotree codes (not NULL, not 'OTHER') with >= MIN_CELL patients
    vendors: list[str]        # vendor values with >= MIN_CELL patients, sorted ("caris", "fmi")
    first_year: int | None    # first / last year in by_year
    last_year: int | None
    by_year: list[YearCount]  # patients by year of their first sample, first_year..last_year
    min_cell: int             # MIN_CELL: the landing page shows null as "<5"
    round_to: int             # PUBLIC_ROUND: the landing page says counts are rounded to it


def coarse(n: int) -> int | None:
    """None under MIN_CELL (0 included), else n to the nearest PUBLIC_ROUND, halves up, so never under 10."""


def summary() -> PublicSummary:
    """Computed once per de-id file (keyed on its mtime, like queries.vocabulary)."""
```

- `coarse(n)` is `None if n < MIN_CELL else (n + PUBLIC_ROUND // 2) // PUBLIC_ROUND * PUBLIC_ROUND`.
  Integer arithmetic avoids Python's banker's `round()`. For example 0, 4 → None; 5, 14 → 10;
  15 → 20; 1234 → 1230; 1235 → 1240.
- `PUBLIC_ROUND` is a constant, not `.env`. It is independent of `suppress.ROUND` / `COHORT_ROUND`,
  which governs signed-in counts.
- Cache: `_summary = {"mtime": None, "v": None}`, refreshed when `os.path.getmtime(DEID_DB)`
  changes, with the same unlocked pattern as `queries.vocabulary()`. One connection per refresh
  (`get_db()`, closed in `finally`).
- SQL. Every statement is fixed text; nothing from the request is bound or interpolated. Read only
  `mart.report` (columns `research_id`, `report_id`, `vendor`, `oncotree`, `year`,
  `year_complete`):

  ```sql
  SELECT count(DISTINCT research_id), count(*) FROM mart.report;
  SELECT count(*) FROM (SELECT oncotree FROM mart.report
                        WHERE oncotree IS NOT NULL AND oncotree <> 'OTHER'
                        GROUP BY oncotree HAVING count(DISTINCT research_id) >= $min_cell);
  SELECT vendor FROM mart.report GROUP BY vendor
    HAVING count(DISTINCT research_id) >= $min_cell ORDER BY vendor;
  -- first-sample year per patient, as Discover's accrual (compile.py `pp`); complete as compile.py's year_complete row
  WITH pp AS (SELECT research_id, min(year) AS yr FROM mart.report WHERE year IS NOT NULL GROUP BY 1),
       c AS (SELECT year, bool_and(year_complete) AS complete FROM mart.report
             WHERE year IS NOT NULL GROUP BY 1)
  SELECT pp.yr, count(*), c.complete FROM pp JOIN c ON c.year = pp.yr GROUP BY 1, 3 ORDER BY 1;
  ```

  `$min_cell` is bound to `MIN_CELL`, a constant.
- Years. `first_year` and `last_year` are the smallest and largest year with `>= MIN_CELL`
  first-sample patients (both None when no year qualifies). `by_year` lists every year in that
  range that has at least one first-sample patient, as
  `YearCount(year, patients=coarse(n), complete)`, so a year inside the range with 1–4 patients
  shows null. Years outside the range are dropped. A date-shifted outlier year with one patient
  therefore never appears, not even as "<5".
- Reuse `cohort.suppress.YearCount`, which has the same shape Discover's sparkline already reads,
  so the OpenAPI schema keeps one `YearCount`.
- `coarse()` is applied to `patients`, `reports`, `tumor_types` and every `by_year[].patients`. The
  only other numbers are years and the two constants `min_cell` and `round_to`.

**Small-cell rule for this output path.** Every count is floored at 5 (null, shown as "<5") and
rounded to the nearest 10. Only vendors and tumor types with at least 5 patients are counted or
listed. The year range is limited to years with at least 5 patients. The endpoint takes no
parameters, so no two responses can be subtracted. Within one response, total patients
against the year sum (or reports against patients) are two counts each rounded to 10, so their
difference is no more precise than ±10 per term. A patient with reports in several years counts
once (first sample), and a patient with reports from both vendors counts once in `patients`.

### 3. Sign-in fallback (`mcp/src/uccc_genomics_mcp/authen.py`)

`_safe_next` returns `"/discover"` instead of `"/"` for a missing or refused `next`. Sign-in
exists for Discover, and the refusal and expiry pages' plain "Sign in" link (`/auth/login` without
`next`) should land there. `logout`'s fallback URL stays `"/"`, which is now the landing page.
Update the `_safe_next` docstring.

### 4. Front end (`web/`)

Two Vite entries, so the landing page is a separate HTML file:

| File | Change |
|---|---|
| `web/discover.html` | new: today's `web/index.html` (title `Discover · UCCC genomics`, `/src/main.tsx`) |
| `web/index.html` | now the landing page: title `UCCC genomics`, `<div id="root">`, `<script type="module" src="/src/landing-main.tsx">` |
| `web/vite.config.ts` | `build: {rolldownOptions: {input: {landing: "index.html", discover: "discover.html"}}}` |
| `web/src/landing-main.tsx` | new entry, below |
| `web/src/Landing.tsx` | new: `discoverRedirect`, `Landing` |
| `web/src/Start.tsx` | `Sparkline` exported, props generalised (below) |
| `web/src/transport.ts` | `fetchPublicSummary` |
| `web/src/types.ts` | `export type PublicSummary = S["PublicSummary"];` |
| `web/src/styles.css` | `.landing` layout and `a.btn-primary` (below) |
| `web/openapi.json`, `web/src/api.gen.ts` | regenerated with `bun run gen` |

Use `rolldownOptions`, not `rollupOptions`, which Vite 8's `index.d.ts` marks deprecated. A
scratch build with this config (not committed) emitted `dist/index.html`, `dist/discover.html` and
shared `dist/assets/*`. In `bun run dev`, Vite's HTML fallback serves `/discover` from
`discover.html`, so dev needs no extra config. The CSP plugin's `transformIndexHtml` runs for both
HTML entries. The files are named `Landing.tsx` and `landing-main.tsx`, not `landing.tsx`, so
they can't collide on a case-insensitive filesystem.

**`Landing.tsx`**

```ts
/** "/discover" + hash for a share link (#d=…), else null: old links to /#d=… open in Discover. */
export function discoverRedirect(hash: string): string | null;

export function Landing({summary, error}: {summary: PublicSummary | null; error: boolean}): JSX.Element;
```

`discoverRedirect(hash)` returns `hash.startsWith("#d=") ? "/discover" + hash : null`. Markup
(class names are the contract for CSS; copy may be polished but must keep the facts):

```html
<main class="landing">
  <h1>UCCC tumor sequencing</h1>
  <p class="lede">De-identified tumor sequencing reports from Caris Life Sciences and Foundation Medicine
    for University of Colorado Cancer Center patients, for checking whether a study is feasible.</p>
  <p>Discover counts how many patients fit a study: choose tumor types, genes, biomarkers and other
    criteria, then copy a feasibility statement for grant text. It shows counts, never patient records.</p>
  <p>Discover is for University of Colorado researchers and staff with campus sign-in. To get access,
    ask the UCCC genomics team.</p>
  <p><a class="btn-primary" href="/discover">Sign in to Discover</a></p>
  <section aria-labelledby="totals-h">
    <h2 id="totals-h">What's in it</h2>
    <!-- summary === null && !error: <p role="status">Loading totals…</p>
         error: <p role="status">Totals are not available right now.</p> -->
    <dl class="totals">
      <div><dt>Patients</dt><dd>{Count patients}</dd></div>
      <div><dt>Reports</dt><dd>{Count reports}</dd></div>
      <div><dt>Tumor types</dt><dd>{Count tumor_types}</dd></div>
      <div><dt>Vendors</dt><dd>Caris Life Sciences, Foundation Medicine</dd></div>
      <div><dt>Collection years</dt><dd>2016–2025</dd></div>   <!-- omitted when first_year is null -->
    </dl>
    <Sparkline years={by_year} minCell={min_cell} label="Patients by year of first sample" />
    <table class="sr-only"><caption>Patients by year of first sample</caption>…year | patients (Count)…</table>
    <p class="hint">Counts are rounded to the nearest {round_to}; fewer than {min_cell} shows as
      &lt;{min_cell}. A patient sequenced by both vendors counts once. Years are approximate: dates
      are shifted per patient for de-identification.</p>
  </section>
</main>
```

- The numbers are synthetic placeholders. Counts render with `Count` from `Answer.tsx` (null shows
  as `<5` with its title), so the landing page shows suppressed counts the way Discover does.
- Vendor labels are `{caris: "Caris Life Sciences", fmi: "Foundation Medicine"}`; any other value
  shows as is.
- The years show as `first–last`, or a single year when the two are equal.

**`landing-main.tsx`**

```ts
import "./styles.css";
const go = () => { const to = discoverRedirect(location.hash); if (to) location.replace(to); return to !== null; };
window.addEventListener("hashchange", go);   // a share link pasted into an open landing tab (#104)
if (!go()) { render <StrictMode><Root /></StrictMode> into #root }
```

`Root` holds `summary` and `error` state, calls `fetchPublicSummary()` once in an effect (a
rejection sets `error`), and renders `Landing`.

**`Start.tsx`.** `Sparkline({r})` becomes
`export function Sparkline({years, minCell, label}: {years: YearCount[]; minCell: number; label: string})`,
with the same bars and rules. The figcaption becomes `{label}, {min}–{max}`. `Start` passes
`years={total.by_year} minCell={total.min_cell} label="Patients by year of first qualifying report"`,
so Discover's output is unchanged.

**`transport.ts`**

```ts
/** GET /api/public/summary: the landing page's totals. Never redirects to sign-in (the route is open). */
export function fetchPublicSummary(fetchImpl: FetchLike = fetch): Promise<PublicSummary> {
  return requester(fetchImpl, () => {})("/api/public/summary");
}
```

**`styles.css`.** Add `.landing` (max-width ~48rem, centred, padding `var(--s6) var(--s4)`, `.lede` at
`--fs-lg`), `.totals` (a wrapping grid of `dt` muted / `dd` at `--fs-2xl` bold, `margin: 0`), and
`a.btn-primary` (`display: inline-block; padding: var(--s2) var(--s4); border-radius: 6px;
text-decoration: none;`, with the same colours as `.btn-primary`). Use only the existing tokens.

### 5. Docs (same PR)

- **AGENTS.md**, "Don't weaken Cloudflare Access": genomics-app's open routes are `/api/health`,
  `GET /api/public/summary` (coarse totals: floored at 5, rounded to 10, no parameters), the landing
  page `/` and its `/assets/*`, plus the `/auth/*` sign-in endpoints under authentik. Layout's `web/`
  line: the landing page (`index.html`) and Discover (`discover.html`).
- **README.md**, "Cohort app (genomics-app)": the open routes as above, a paragraph on
  `/api/public/summary` and its rule, and that `--static` serves the landing page at `/` and Discover
  at `/discover`. In "Discover (web/)", the URL becomes `http://<tailnet-addr>:8092/discover`,
  `/#d=` links redirect, and the sign-in fallback is `/discover`.
- **docs/ARCHITECTURE.md**: decision 12 now says the public totals are the campus app's landing
  page (`/`, `GET /api/public/summary`), and that the Cloudflare dashboard and `genomics-cohort-api`
  retire in a follow-up once production is live. Add `/api/public/summary` to the diagram's FastAPI
  line. The Development section says Discover is at `/discover`.
- **dashboard/COHORT_DISCOVERY.md**: in §3.3 phase 1, Discover is at `/discover` and `/#d=` links go
  there. In §3.6, add a row "Public summary (#41) | anyone can read it | fixed aggregates, no
  parameters, floored at 5 and rounded to 10, years and categories limited to ≥ 5 patients".

## Acceptance criteria

- [ ] `GET /` without credentials returns the built landing page (200) under `--auth password` and
      `--auth authentik`, and so does `GET /assets/<file>`.
- [ ] `GET /discover`, `/discover.html`, `/index.html` and `/no/such/path` without credentials get a
      401 under password. Under authentik they get the sign-in page (401, the `location.replace`
      script). With credentials, `/discover` returns `discover.html`.
- [ ] `public_path`: True for `/`, `/api/health`, `/api/public/summary`, `/assets/x.js`; False for
      `/index.html`, `/discover`, `/assets/../discover.html`, `//assets/x`, `/api/public/summary/x`,
      `/api/publicx`.
- [ ] Enumerating every `APIRoute` of `app.app()` whose path starts with `/api/`, a request without
      credentials gets 401 for every route except `/api/health` and `/api/public/summary`.
- [ ] `GET /api/public/summary` without credentials returns 200,
      `Cache-Control: public, max-age=3600`, and exactly the keys `patients, reports, tumor_types,
      vendors, first_year, last_year, by_year, min_cell, round_to`.
- [ ] Every count in it (`patients`, `reports`, `tumor_types`, `by_year[].patients`) is null or a
      multiple of 10 that is at least 10. `min_cell == 5` and `round_to == 10`.
- [ ] No string in the response is a `research_id` or `report_id` of the synthetic mart, and every
      vendor is in `{"caris", "fmi"}`.
- [ ] The OpenAPI operation for `/api/public/summary` has no `parameters` and no `requestBody`.
      `GET /api/public/summary?oncotree=NSCLC&year=2023` returns the same body as without the query.
      `POST` is 405.
- [ ] The values match hand-computed `coarse()` of plain SQL on the synthetic mart. Tumor types
      leave out `OTHER`, NULL and codes under 5 patients. Vendors under 5 patients are left out. A
      single-patient outlier year is not in `by_year` and not `first_year`. A 1–4-patient year inside
      the range is in `by_year` with `patients: null`.
- [ ] `coarse`: 0→None, 4→None, 5→10, 14→10, 15→20, 1234→1230, 1235→1240.
- [ ] The summary is computed once per de-id file mtime: a second request does not call `get_db`,
      and a changed mtime does.
- [ ] If `get_db` raises, the response is 503 `{"detail": "totals unavailable"}` and the body
      holds none of the exception text.
- [ ] Authentik: a sign-in with no `next`, or a refused `next`, lands on `/discover`. `next`
      `/discover#d=abc` comes back as `/discover#d=abc`.
- [ ] Web: `discoverRedirect("#d=abc") === "/discover#d=abc"`; `""`, `"#x"` and `"#answer-h"` give
      null.
- [ ] Web: `Landing` renders the sign-in link (`href="/discover"`, `class="btn-primary"`, text
      "Sign in to Discover"), null counts as `<5`, the vendor labels and the year range, the rounding
      note, and the loading and error states. It renders no `<form>` and makes no authenticated call.
- [ ] Web: `fetchPublicSummary` GETs `/api/public/summary` same-origin. On a 401 it throws
      `TransportError` and never navigates.
- [ ] Web: `policy.test.ts` checks `index.html` and `discover.html` too (no external URL, network
      only in `transport.ts`).
- [ ] `bun run build` emits `dist/index.html` and `dist/discover.html`, both with the CSP meta tag.
- [ ] `web/openapi.json` and `web/src/api.gen.ts` are regenerated (`test_openapi_snapshot` and
      `bun run typecheck` pass).
- [ ] Docs updated as in Design §5.

## Test plan

Everything runs on synthetic data in temp dirs: the #34 `Mart` / `write_mart` / `use_mart` helpers
from `tests/test_cohort.py`. No test reads `$DATA/raw`, the PHI file or the real de-id file.

**`tests/test_app.py`**

- Fixture `client`: also write `static/discover.html` (`<p>discover</p>`) and
  `static/assets/app.js`, and patch `public.get_db`, `public.DEID_DB` and `public._summary` to the
  synthetic mart, as `ids` does for `app.get_db`.
- `GATED`: remove `("GET", "/")` and add `("GET", "/discover")` and `("GET", "/discover.html")`.
  `/index.html` stays.
- `test_public_paths_open`: `/`, `/assets/app.js` and `/api/public/summary` return 200 without auth.
  `/` returns the landing HTML.
- `test_public_path` (parametrized): the `public_path` table above.
- `test_only_health_and_public_summary_are_open`: for every `fastapi.routing.APIRoute` in
  `app.app().routes` with a path under `/api/` and each of its methods, substitute `{id}` with a
  uuid4 and `{cohort_id}` with `v1-0000000000000000`, send it without auth and with a JSON body of
  `{}` where needed. Expect 401 unless the path is `/api/health` or `/api/public/summary`.
- `test_public_summary_shape`, `test_public_summary_no_parameters`,
  `test_public_summary_counts_are_coarse` (walk the body with `walk()`, ids from the `ids` fixture),
  `test_public_summary_unavailable` (patch `public.get_db` to raise
  `RuntimeError("/secret/path")`).
- `test_public_summary_values`: a dedicated small `Mart` written to `tmp_path`. It has a
  `caris`/`fmi` mix, an `OTHER` code, a NULL oncotree, a code with 3 patients, a vendor value with 2
  patients, a 2-patient year between two 10+-patient years, and a 1-patient outlier year before them.
  Compare against `coarse()` of plain SQL and the rules above.
- `test_coarse` (parametrized), and `test_public_summary_cached` (count `get_db` calls; bump the
  patched mtime with `os.utime`).

**`tests/test_authen.py`**

- `make`: also write `static/discover.html`.
- `STATIC`: `("GET", "/discover")`, `("GET", "/index.html")`, `("GET", "/no/such/path")`.
- Add `("GET", "/")`, `("GET", "/api/public/summary")` to `test_open_paths`. The summary needs the
  synthetic mart, so patch `public` as in `test_app.py`, or accept 200 or 503 here, since the open
  check is what this test pins.
- `test_member_signs_in` expects `location == "/discover"`. In `test_next_is_same_site_only`, every
  refused `next` (and `None`) lands on `/discover`.

**`web/`** (`bun test`, `renderToStaticMarkup` as in `app.test.tsx`)

- `landing.test.tsx`: `discoverRedirect` cases; `Landing` with a synthetic summary (for example
  `patients: 1230, reports: 1560, tumor_types: 40, by_year` with one null year), with
  `summary=null`, and with `error=true`.
- `transport.test.ts`: `fetchPublicSummary` URL, method, credentials, and a 401 that throws without
  navigating.
- `policy.test.ts`: add `join(src, "..", "discover.html")` to `files`.
- The existing `Start` / sparkline tests still pass, with Discover's caption unchanged.

**Checks:** `uv run pytest -q`;
`cd web && bun install --frozen-lockfile && bun run typecheck && bun test`;
`cd web && bun run build` (inspect `dist/` for both HTML files and their CSP meta). The dashboard
check (`cd dashboard && npm ci && npm test`) is n/a, because nothing under `dashboard/` changes,
but run it anyway if it's cheap.

## Risks

- **A new unauthenticated output path.** This is what the issue asks for. The controls are no
  parameters, fixed SQL, floor 5 + round 10, categories and years limited to ≥ 5 patients, and a
  test that pins each of them. The totals now reach anyone on the internet who can reach the app,
  not only campus users. Before this change, the same kind of numbers sat behind Cloudflare Access
  on the dashboard. That trade-off is the issue owner's decision, recorded in ARCHITECTURE decision
  12.
- **`/assets/*` is public.** Discover's compiled JS and CSS become readable without sign-in. They
  are built from this public repo and hold no data, keys or `.env` values: no `VITE_*` variables are
  used, so Vite inlines nothing from the environment. `public_path` normalises the path, so
  `..` can't reach a gated file.
- **No rate limit on the open endpoint.** The cache makes a request one `os.path.getmtime` call
  plus serialisation. The ceiling is a flood of requests that just costs CPU; add a per-IP limit at
  Traefik when production hosting lands. (Done in `deploy/compose.yaml`, #129.)
- **Cache-Control and the daily rebuild.** A browser or proxy may show totals up to an hour old
  after the rebuild. That's acceptable for coarse totals.
- **Bookmarks to `/`.** Signed-in users who bookmarked `/` now land on the landing page, one click
  from Discover. Share links (`/#d=`) are redirected. Other fragments are left alone.
- **Production hosting** must serve `discover.html` at `/discover` the way the `/discover` route
  does. Until then `--static` is development only, as today.
