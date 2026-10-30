# uccc-genomics-db

Vendor NGS reports (Caris, Foundation Medicine) as one local DuckDB, with
per-vendor schemas and a cross-vendor `unified` layer for cohort queries.

```
Caris S3 bucket ──aws s3 sync──▶ $DATA/raw/caris/<case>/   (json + geneTPM csv)
FMI CIFS share on FMI host ──tar|ssh──▶ $DATA/raw/fmi/*.xml
                                   │  genomics load
                                   ▼
                 $DATA/genomics_phi.duckdb   schemas caris.*, fmi.*     — identifiers present, never leaves this host
                                   │  genomics deid
                                   ▼
                 $DATA/genomics.duckdb       schemas caris.*, fmi.*, unified.*, mart.*   — de-identified, the one you query
```

`DATA` defaults to `/data/davsean/genomics`. `CARIS_BUCKET` (s3://bucket/) and
`FMI_SRC` (host:dir) are site-specific and live in the gitignored `.env` at the
repo root, which `config.py` reads (copy `.env.example`); `STALE_DAYS` (default 21) is the limit for `genomics check`. Caris creds are the `[default]` AWS profile; FMI needs
passwordless ssh to the FMI host.

## Run

```bash
uv sync
uv run genomics all                 # sync + load both vendors, then deid (~20 min, TPM CSVs dominate)
uv run genomics sync --vendor fmi   # or any single step / vendor
uv run genomics load --vendor caris
uv run genomics deid
uv run genomics check            # fail if a vendor's newest received date is older than STALE_DAYS (21)
```

Every load is a full drop-and-rebuild from the raw mirror; the mirror is the
rebuildable backstop and the bucket/share are the source of truth.

## Encryption and keys

Both DuckDB files are AES-256-GCM encrypted (DuckDB ≥ 1.4 native encryption:
file, WAL and temp spill). They cannot be opened without the key, so plain
`duckdb genomics.duckdb` fails by design. Use:

```bash
uv run genomics shell          # duckdb CLI, de-identified file attached read-only as `db`
uv run genomics shell --phi    # the identified file, as `phi`
```

or from Python: `from uccc_genomics.config import connect, DEID_DB, DEID_DB_KEY;
con = connect(db=(DEID_DB, DEID_DB_KEY, "READ_ONLY"))`.

| file in `$DATA` | purpose | share with |
|---|---|---|
| `.db_key_phi` | opens `genomics_phi.duckdb` | nobody |
| `.db_key` | opens `genomics.duckdb` | whoever legitimately gets the de-id file |
| `.deid_key` | HMAC-style key behind `research_id` / hashed `report_id` | nobody; losing it changes every id on the next rebuild |

All three are mode 600, generated on first use, and are **not** in the
rebuildable set: back them up wherever the PHI file is backed up. This is
encryption at rest, not access control — anyone holding a key has that
whole file. The raw mirrors under `$DATA/raw/` are *not* encrypted; that's a
LUKS-volume question for the host, not a repo one.

Scheduled daily by `systemd/genomics.{service,timer}` (10:30 MT, ntfy on
failure — the platform convention in `monode/infrastructure/SCHEDULING.md`):

```bash
ln -sf $PWD/systemd/genomics.service $PWD/systemd/genomics.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now genomics.timer
```

The unit runs `genomics check` last, so ntfy fires when either vendor's newest received date is older
than `STALE_DAYS`, and the FMI sync fails (rather than reusing the old mirror) when the share is empty
or unmounted.

## Layout

```
src/uccc_genomics/
  cli.py        genomics sync|load|deid|all|check [--vendor] | shell [--phi]
  config.py     paths ($DATA), bucket, FMI source, key files, connect() (encrypted ATTACH)
  db.py         bulk_insert: rows -> temp JSONL -> try_cast per column (executemany is ~100x slower)
  caris.py      sync() + load(): report JSON + gene TPM CSV -> caris.*
  fmi.py        sync() + load(): report XML -> fmi.*  (incl. blocks the old parser skipped)
  deid.py       generic: drop PHI columns, keyed-hash ids, per-patient date shift, leak assert
  sql/caris_views.sql, fmi_views.sql, unified.sql, mart.sql
  data/disease_crosswalk.csv   vendor disease term -> OncoTree code/name, organ system, NCIt (-> reference.disease_crosswalk)
mcp/            genomics-mcp: read-only MCP server over the de-id file (mcp/README.md);
                genomics-cohort-api: the cohort page's floored-count endpoint (below)
                app.py: genomics-app, FastAPI REST (/api/*) + MCP (/mcp) over cohort/, behind authen
                cohort/: cohort definition, operations, cohort_id, compiler and suppression over mart.*
dashboard/      Observable Framework site over aggregates of the de-id file (below)
web/            Discover: React + TypeScript (Vite, bun) cohort builder over genomics-app's REST API (below)
tests/          pytest: synthetic load -> deid -> unified, MCP query guard, cohort API, dashboard loader governance
```

```bash
uv run pytest          # ~30 s; the loader tests skip when $DATA/genomics.duckdb is absent
(cd dashboard && npm test)   # cohort page helpers
(cd web && bun install && bun run typecheck && bun test)   # Discover app
```

## Schemas

**`caris.*`** — `report` (one per case, newest JSON wins over Addended/Corrected
re-deliveries), `specimen`, `test`, `result` (one row per biomarker record,
`kind` + raw `payload` JSON), `gene_tpm` (all ~68k genes per case). Typed
views over `result`: `variant` (`vaf_pct`, `read_depth`, plasma/buffy-coat VAF
for liquid; `wildtype = true` means tested-negative), `cna`, `fusion`, `ihc`,
`wts_expression`, `tmb`, `msi`, `loh`, `therapy`.

**`fmi.*`** — `report` (one per ReportId; FoundationOne Monitor files have no
FinalReport, so their id is the file name and they carry no name, DOB or dates. Their MRN comes from
`ResultsReport/CustomerInformation`, as does the MRN of a report whose PMI MRN is empty; `mrn_source`
says which, PHI-side only),
`sample`, `short_variant` (with `is_vus`, `subclonal`, `source`), `cna` (with `source`), `rearrangement`,
`biomarker` (TMB, MSI, LOH…), `non_human`, `pertinent_negative`, `alteration`
(curated Genes block), `therapy`, `trial`, `amendment`, `load_error` (files that
failed to parse, or files of one ReportId that disagree on the patient — nothing is dropped silently),
`duplicate_file` (FMI delivered some reports in two files, a full one and a copy without the
variant report: the file with variant-report variant elements loads, then higher `Version`, more
amendments, newer mtime; the others are listed here with `chosen_file` and `reason`; PHI-side only). Views `tmb`, `msi`, `loh`.
`source` is `variant_report`, or `genes_block` for rows derived from the curated Genes block on
reports without `<short-variant>` / `<copy-number-alteration>` elements (older reports, #76), or (short_variant
only) `variant_properties` for VUS listed only in `VariantProperties` on reports without
`<short-variant>` elements (#79).

**`unified.*`** (de-identified file only) — `patient`, `report`, `variant`,
`cna`, `fusion`, `biomarker` (long: TMB/MSI/LOH/PD-L1 and the other Caris IHC markers), `gene_tested`
(Caris wild-type records + FMI pertinent negatives). Each is a
`UNION ALL BY NAME` across vendors with a `vendor` column; vendor-specific
detail stays in `caris.*` / `fmi.*` and joins back on `report_id`.
`variant.tier` (`pathogenic`, `likely_pathogenic`, `vus`, `likely_benign_or_benign`,
`unclassified`) is the one significance column to filter on, derived per vendor;
`is_vus` and `vendor_call` stay as the vendor's own flags, and the cohort API's
default "pathogenic" is the first two tiers. `variant.source` / `cna.source` carry the
FMI provenance above (NULL for Caris); FMI `genes_block` short variants have tier
`likely_pathogenic` unless VUS, an inference rather than a vendor call. FMI
`variant_properties` rows are VUS (tier `vus`). `variant.consequence` is lower case
(vendor terms are otherwise unchanged). `biomarker.call_norm` folds the Caris HER2
IHC spellings (`HER2-Low`/`Low`, `HER2-Positive`/`Positive`, ...) while `call` keeps
the raw string. `biomarker.clone` is the PD-L1 antibody clone (`22c3`, `sp142`), NULL on every other row. `report.collected_year_complete` is false while the date-shifted
collection year can still gain reports (the ±182-day shift), so a trailing partial
year can be flagged.
`report.disease_text` / `oncotree_code` / `organ_system` / `ncit_code` come from
`reference.disease_crosswalk` (hand-curated, in the package) where the vendor's
term is mapped; unmapped terms keep the vendor string as `disease_text` with
`oncotree_code = 'OTHER'`, and `raw_disease_text` always has the original.

**`mart.*`** (de-identified file only; tables rebuilt by `genomics deid` from `unified.*`,
`sql/mart.sql`) — the cohort mart of `dashboard/COHORT_DISCOVERY.md` §3.2. Read by the cohort module
(`mcp/src/uccc_genomics_mcp/cohort/`).
`mart.report` is one row per `unified.report` row with the population dimensions: `year`,
`year_complete`, `sex`, `age`/`age_band` (Caris tissue only, else `unknown`), `oncotree`, `organ`,
`disease`, `assay_class`, `assay_name`, `purity`, `site_type`/`site` (Caris, first tumor
specimen), `has_wts` (Caris RNA/cfTNA gene TPM file or `wtsExpression` records), `collected_on`
(the per-patient shifted collection date; it only orders two reports of one patient for the
`sequence` criterion and is never output).
`mart.fact` is one row per finding (`research_id`, `vendor`, `report_id`, `kind`, `key`, `sub`,
`val`, `num`, `unit`, `tier`), and the columns mean this per `kind`:

| kind | key | sub | val | num / unit | tier |
|---|---|---|---|---|---|
| `alteration` | gene | `mutation`, `amplification`, `loss` or `fusion` | protein change (mutation), partner gene (fusion) | | mutation rows only |
| `biomarker` | `TMB`, `MSI`, `LOH` | | `call_norm` | value / `mut/Mb`, `%` | |
| `ihc` | Caris IHC marker name | PD-L1 clone | `call_norm` | score / `TPS`, `CPS`, `% stained` | |
| `expression` | gene | | | TPM percentile / `percentile` | |
| `tested_negative` | gene | `wildtype` or `pertinent_negative` | | | |
| `actionability` | `caris_level1`, `fmi_fda_any_indication`, `fmi_trial` | biomarker or gene | therapy / NCT id | | |
| `specimen` | `site_type`, `site`, `purity` | | text | purity % / `%` | |

`unit` is NULL whenever `num` is. Mutation rows carry **every** tier, benign included, so a
consumer filters `tier` (the default is `pathogenic` + `likely_pathogenic`) on `sub = 'mutation'`
rows; amplification, loss and fusion rows have no tier. Viral findings, CNA copy number and VAF
are not in the mart. `data` and `sequence` criteria read `mart.report` (`has_wts`, `assay_class`,
`vendor`, `collected_on`).

```sql
-- patients with a KRAS G12C call from either vendor, and whether they also had TMB-High
SELECT v.research_id, v.vendor, v.report_id, b.call AS tmb
FROM unified.variant v
LEFT JOIN unified.biomarker b ON b.report_id = v.report_id AND b.name = 'TMB'
WHERE v.gene = 'KRAS' AND v.hgvs_p ILIKE '%G12C%';
```

## De-identification (`deid.py`)

- Drops name, MRN, DOB, address, physician/pathologist/facility blocks, free-text
  pathology comments, file names and sample names.
- `report_id` → keyed hash of the vendor accession. `research_id` → keyed hash
  of normalized MRN, or of `last|first|dob` when the vendor left MRN empty
  (FMI does on ~20% of reports). Same patient ⇒ same `research_id` across vendors.
  FMI's MRN is the PMI copy, else `ResultsReport/CustomerInformation/MRN` (#89). That fallback
  changed `research_id` for the reports it reaches, mostly FoundationOne Monitor, from a per-report
  id to the patient's. It was a correction: patient counts dropped, and a downstream list holding an
  affected report's old `research_id` no longer finds it. A regular report reached this way also gets
  new shifted dates (the offset follows the patient), now consistent with that patient's other reports.
  Two copies of one FMI report are compared pairwise. When both carry an MRN, it decides. Otherwise
  they are one patient when both carry last|first|dob and it agrees, or when neither carries any
  identity; any other pair sends every copy to `fmi.load_error`. If the chosen copy has no MRN, it
  takes it from a twin (`mrn_source = 'duplicate_copy'`).
- Every DATE/TIMESTAMP shifted per patient by a stable offset in ±182 days;
  intervals survive. Ages capped at 89.
- Key in `$DATA/.deid_key` (mode 600). Same key ⇒ same IDs on rebuild.
  Losing it breaks linkage to any downstream cohort lists — back it up with
  the PHI file.
- Asserts no Caris/FMI accession or sample-id pattern survives in any text
  column of the output. The new file is built as `genomics.duckdb.tmp` and
  renamed onto `genomics.duckdb` only when that check passes, so a failed
  rebuild leaves the previous file (and the MCP server / cohort API) as they were.

## Dashboard

`dashboard/` is an [Observable Framework](https://observablehq.com/framework/)
site: five pages of aggregates over `genomics.duckdb`. Four pages run on one
data loader (`src/data/summary.json.py`) that runs at build time, drops every
cell under `MIN_CELL = 5` and emits no row-level ids. The cohort page instead
asks the cohort API (below) live.

1. **Overview** (`/`) — counts, reports by collection year, assays, top diseases per vendor.
2. **Cohort exploration** (`/cohort`) — patient counts and prevalence for any combination of
   organ system (with solid-tumor and GI presets), disease, gene, exact protein change,
   alteration class, sex, age band, vendor, assay class and year window, from
   `GET /api/cohort`. The filter state is the page's query string, so a link is a cohort
   definition. Display helpers are in `src/components/cohort.js`, covered by `npm test`.
3. **Genes** (`/genes`) — alteration frequency by gene, disease × gene heatmap, exact protein changes within a gene (sub-floor changes pooled as "other"), one gene or one exact alteration across diseases.
4. **Biomarkers** (`/biomarkers`) — TMB, MSI, PD-L1, LOH, VAF distributions, and every other Caris IHC marker (HER2, ER/PR, AR, MMR, ALK, CLDN18, FOLR1 …) by disease with calls shown as Caris reports them. FMI has no IHC.
5. **Coverage & quality** (`/coverage`) — panels, gene coverage, report status, purity, known gaps.

Google Analytics (`G-KLLV1GCF4E`) is in the page head.

```bash
cd dashboard && npm install
npm run dev      # live preview on http://localhost:3000
npm run build    # -> dashboard/dist/, ~5 s
npm run deploy   # -> Cloudflare Worker `uccc-genomics-dashboard` (needs CLOUDFLARE_API_TOKEN)
```

Hosting is a Cloudflare Workers static-assets site, deployed by the systemd
service after every daily load with the `cdsci-cloudflare-workers-token`
secret from GSM. Users reach it at `https://uccc-genomics.cancerdatasci.org`
behind **Cloudflare Access** (one-time PIN to an institutional email), so no
Claude, VPN or tailnet is needed. `workers_dev` and preview URLs are off in
`dashboard/wrangler.toml` because Access only guards the custom domain.

Access is configured (done 2026-09; the hostname 302s to the Access login
for anonymous requests) as: Zero Trust → Access → Applications → Self-hosted,
domain `uccc-genomics.cancerdatasci.org`, identity provider One-time PIN,
policy Allow "Emails ending in" `@cuanschutz.edu`, session 24h. Add domains
there, not in this repo. If the Access application is ever deleted, comment
out `routes` in `dashboard/wrangler.toml` first: the Worker would otherwise
serve the site unauthenticated on the custom domain.

Known One-time PIN failure: the PIN email also carries a sign-in link that
redeems the same code, and campus mail scanners (Safe Links, Proofpoint)
follow it on arrival, so the user sees "this PIN has already been used". No
Access setting removes the link. Workaround is "Request new code" and typing
it at once; the durable fix is switching the IdP to Microsoft Entra ID for
the campus tenant (issue #17).

### Cohort API

`mcp/src/uccc_genomics_mcp/cohort_api.py` (`genomics-cohort-api`,
`systemd/genomics-cohort-api.service`), designed in `dashboard/COHORT_TOOL.md`.
A fixed-parameter endpoint: every parameter is an allow-list read from the DB
(values with under 5 patients are left out), values reach SQL only as bound
parameters, every count under 5 becomes `null` (plus secondary suppression and
the whole-cohort rule), and every request is logged to journald with the
user's email from the Access JWT. It uses the MCP server's hardened read-only
connection, one per request, so the daily rebuild needs no restart.
`tests/test_cohort_api.py` pins all of that on a synthetic DB and checks the
real DB against hand-written SQL.

```bash
uv run genomics-cohort-api --auth none --static dashboard/dist --port 8091
# local dev: API + built site same-origin at http://localhost:8091/cohort.html
journalctl --user -u genomics-cohort-api   # audit log, one JSON line per query
```

In production the dashboard Worker (`dashboard/worker.js`) forwards `/api/*`
to `uccc-genomics-api.cancerdatasci.org`, a proxied hostname for Traefik on
this host (`monode/infrastructure/compose/traefik/config/uccc-genomics-api.yml`),
which routes to `172.19.0.1:8090`. That hostname is not behind Access itself:
the API refuses any request without a valid Access JWT (header or
`CF_Authorization` cookie, both forwarded by the Worker) for `ACCESS_TEAM` /
`ACCESS_AUD` in `.env`, the team and AUD tag of the `uccc-genomics` Access
application. Only `/api/health` is open, for the GCP uptime check
(`monode/infrastructure/terraform/apps/uccc_genomics/`).

The site only ever contains suppressed aggregates, but it does leave campus:
if the DUA reads "data or any derivative", host it on the box behind Traefik
instead (nginx over `dist/`, IP allowlist).

### Cohort app (genomics-app)

`mcp/src/uccc_genomics_mcp/app.py`: the campus cohort site's backend (docs/ARCHITECTURE.md). One
process serves REST at `/api/*` (OpenAPI schema at `/api/openapi.json`; no Swagger UI) and MCP
(Streamable HTTP, stateless) at `/mcp` (POST only; `GET /mcp` is 405, no SSE stream), both thin
layers over `cohort/`. Every request but the open routes needs a login through `authen`
(`--auth access|password|none|authentik`; `none`: no login, local dev only). The open routes are
`/api/health`, `GET /api/public/summary`, the landing page `/` and its `/assets/*`, and, under
`authentik`, the three `/auth/*` sign-in paths. `count` and `pivot` are limited
to 60 a minute per user across both surfaces (a count or pivot the cohort module rejects, such as
an unknown vocabulary value or a pivot of a definition that has no pivot, still uses the limit; a
body that fails schema validation does not) and logged to stdout as one JSON line each (user,
cohort_id, definition, suppressed patients); the line carries the user's `sub` and `email`. The MCP tools are `search_vocabulary`, `apply_op`,
`count`, `pivot` and `describe_definition`, plus the saved-cohort tools below; there is no SQL
tool.

    uv run python -m uccc_genomics_mcp.authen    # once: put APP_USER and the printed APP_PASSWORD_HASH in .env
    uv run genomics-app --auth password --host <tailnet-addr> --port 8092 [--static <dir>]
    # http://<tailnet-addr>:8092/api/openapi.json, MCP clients at http://<tailnet-addr>:8092/mcp

`GET /api/public/summary` (#41) feeds the landing page. It takes no parameters and returns fixed
aggregates over `mart.report`: patients, reports and tumor types (OncoTree codes other than `OTHER`
with at least 5 patients) each floored at 5 and rounded to the nearest 10, the vendors with at least 5
patients, and patients by year of first sample for the years with at least 5 patients (a year in
that range with fewer shows null). It is cached per de-id file and sent with `Cache-Control: public,
max-age=3600`.

`--static` serves a built front end: the landing page at `/` and Discover (below) at `/discover`.
Production runs it in a container ([Production (container)](#production-container)).

**Campus sign-in (Authentik)** (#95). `--auth authentik` signs members of one Authentik group in
through the central Authentik run from seandavi/monode (`infrastructure/compose/authentik/README.md`
§ Contract for apps; the application, provider and group are seandavi/monode#130: slug
`uccc-genomics`, confidential client, group binding `uccc-genomics-dashboard`, and one Strict
redirect URI `<APP_BASE_URL>/auth/callback` per deployment). Settings in `.env` (placeholders in
`.env.example`; the app refuses to start naming every missing or invalid one):

| Variable | Meaning |
|---|---|
| `AUTHENTIK_ISSUER` | `https://<authentik-host>/application/o/uccc-genomics/` (ends with `/`) |
| `AUTHENTIK_CLIENT_ID` | `uccc-genomics` |
| `AUTHENTIK_CLIENT_SECRET` | the provider's client secret (below) |
| `APP_BASE_URL` | the URL users open, e.g. `http://<tailnet-addr>:8092`; must match the redirect URI (an `https://` base makes the cookies `Secure`, so reaching the app over `http://` then loops through sign-in) |
| `SESSION_SECRET` | signs the app's cookies, at least 32 characters |
| `AUTHENTIK_GROUP` | optional, default `uccc-genomics-dashboard` |

    # client secret: from Secret Manager into .env, never printed
    printf 'AUTHENTIK_CLIENT_SECRET=%s\n' "$(gcloud secrets versions access latest \
      --secret=uccc-genomics-authentik-client-secret --project=<gsm-project>)" >> .env
    python -c "import secrets; print('SESSION_SECRET=' + secrets.token_urlsafe(48))" >> .env
    uv run genomics-app --auth authentik --host <tailnet-addr> --port 8092 --static web/dist

The flow is authorization code with PKCE, `state` and `nonce`. Access is the `groups` claim of the
ID token and nothing else (never email or domain), and fails closed. The app then keeps the user in
its own signed cookie for at most 8 hours (not extended on use), so removing someone from the group
takes effect at their next sign-in, up to 8 hours later. `/api/*` and `/mcp` also accept
`Authorization: Bearer <access token>` from the same provider, checked on every call like the ID
token; how a local MCP client obtains one is not built here. `/api/*` and `/mcp` answer 401 without
a login (with `WWW-Authenticate: Bearer realm="uccc-genomics"`), or 503 with `Retry-After` when a Bearer
token can't be checked because Authentik is unreachable. The app fetches Authentik's discovery document
and key set at most once per 30 s, so a token signed with a new key is refused for up to 30 s after the
last fetch and accepted after one refetch; a browser opening a gated page (Discover at `/discover`) gets a page that sends it to `/auth/login` and back to the same address, a
`#d=` share link included; a sign-in with no usable `next` lands on `/discover`. `GET /api/me` returns the
caller's own `sub`, `email` and whether Discover shows "Sign out". Check it once as the contract
asks: a member gets in (`/api/me` answers), a non-member is refused at Authentik or on the callback.
A refusal page names the group (`AUTHENTIK_GROUP`) and says to ask the UCCC genomics team; a failure
that is not about the group says "Sign-in failed; try again."

Users are keyed on `sub`; saved cohorts and snapshots belong to it, and the rate limit counts per
`sub`. Rows saved under an earlier backend (owner = `APP_USER` or an email) stay unreachable until a
person moves them once: sign in, read your `sub` from `/api/me`, then (`cohort_version.created_by`
is provenance and stays):

```bash
psql "$DATABASE_URL" -v old='<old owner>' -v new='<sub from /api/me>' <<'SQL'
BEGIN;
UPDATE cohort   SET owner      = :'new' WHERE owner      = :'old';
UPDATE snapshot SET created_by = :'new' WHERE created_by = :'old';
COMMIT;
SQL
```

**Saved cohorts** (`saved.py`, #36). A logged-in user can save a cohort definition, edit it with
operations (each edit is a new immutable revision), list and delete their cohorts, read the history,
revert, snapshot one for a grant feasibility statement, and resolve a shared `cohort_id`. Postgres
(SQLAlchemy async + asyncpg, Alembic migrations in `mcp/src/uccc_genomics_mcp/migrations/`) holds
four tables: `cohort_version` (content-addressed selecting part of a definition), `cohort`,
`cohort_revision` (the append-only chain) and `snapshot` (the suppressed `CountResult` and its data
date). It holds definitions, operations and suppressed results only: no patient data, no
unsuppressed count. Setting `DATABASE_URL` in `.env` (a standard `postgresql://` URI) turns it on;
without it the saved routes answer 503 and everything else works. REST and MCP tools, one line each:

- `POST /api/saved` / `save_cohort`; `GET /api/saved` / `list_saved_cohorts`; `GET /api/saved/{id}` / `get_saved_cohort`
- `POST /api/saved/{id}/apply` / `apply_saved_op`; `GET /api/saved/{id}/history` / `saved_cohort_history`
- `POST /api/saved/{id}/revert` / `revert_saved_cohort`; `DELETE /api/saved/{id}` / `delete_saved_cohort`
- `POST /api/saved/{id}/snapshot` / `snapshot_saved_cohort` (rate-limited and audited like `count`);
  `GET /api/snapshots` / `list_snapshots`
- `GET /api/versions/{cohort_id}` / `get_cohort_version`

```
# once, by a person, on the host's shared cluster: create a database and role for the app, then
uv run alembic -c mcp/alembic.ini upgrade head
# tests: a throwaway Postgres (CI uses a service container)
docker run --rm -d --name genomics-test-pg -e POSTGRES_PASSWORD=test -p 127.0.0.1:55432:5432 postgres:17
TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/postgres uv run pytest -q
docker rm -f genomics-test-pg
```

Without `TEST_DATABASE_URL` the Postgres tests skip with a message. The app never migrates on start.

### Discover (web/)

The cohort builder (COHORT_DISCOVERY.md §3.3), a React + TypeScript app built with Vite and bun.
It sends only cohort definitions and edit operations to `/api/*` (never SQL), shows every
suppressed count as "<5", keeps versions in the browser's local storage and shares a cohort as a
link holding its definition. Compare (2-4 local versions side by side) and the Feasibility statement
are in the top bar. No third-party requests; the build sets a same-origin CSP. The build has two
pages: the public landing page (`index.html`, `/`) and Discover (`discover.html`, `/discover`). An
old share link `/#d=…` is sent on to `/discover#d=…` by the landing page's script.

    (cd web && bun install && bun run build)
    uv run genomics-app --auth password --host <tailnet-addr> --port 8092 --static web/dist
    # http://<tailnet-addr>:8092/discover (the landing page is at /)

`bun run dev` serves the app with hot reload and proxies `/api` to a genomics-app on
127.0.0.1:8092. After changing a model in `cohort/` or `app.py`, run `bun run gen` (rewrites
`web/openapi.json` and `web/src/api.gen.ts`); pytest and `bun run typecheck` fail until you do.

### Production (container)

`Dockerfile` builds `genomics-app` and the built `web/` into one image (non-root uid 10001, no
secrets, data or keys inside; `.dockerignore` is an allowlist). `deploy/compose.yaml` runs it on the
pipeline host behind the host's Traefik (`proxy` network, Let's Encrypt through the `cloudflare`
resolver, grey-cloud DNS) with Authentik sign-in, and on `pg_main_stack_default` for Postgres. Every
route but the open ones needs a login in the Authentik group. `/mcp` is not routed (MCP stays on the
tailnet, `genomics-mcp`), and the container publishes no port. Traefik rate-limits each client address (average 20/s, burst 50) on every route; it exists for the open ones (`/`, `/assets/*`, `/auth/*`, `/api/public/summary`), and signed-in traffic from a shared campus NAT address shares it.

It mounts only `genomics.duckdb` and `.db_key` from `$DATA`, read-only, and runs as the uid:gid that
owns `.db_key` (mode 600). The PHI file, its key, `.deid_key` and `raw/` are never mounted. `deid.py`
replaces `genomics.duckdb` by rename and a file bind mount keeps the old inode, so `genomics.service`
runs `docker restart uccc_genomics_app` right after `genomics all` (skipped while the container does
not exist). The app serves the previous file until then, and a few seconds of downtime a night is the
cost.

**Settings, once.** `deploy/.env` (gitignored; placeholders in `deploy/.env.example`), created with
`umask 077`. Secrets come from Secret Manager and are never echoed:

    cd deploy && umask 077 && cp .env.example .env     # then edit the non-secret values: APP_HOST, HOST_DATA, AUTHENTIK_ISSUER, DATABASE_URL role/database
    stat -c '%u %g' "$DATA/.db_key"                    # -> APP_UID APP_GID
    for s in authentik-client-secret:AUTHENTIK_CLIENT_SECRET session-secret:SESSION_SECRET; do   # printf is a builtin: no secret in `ps`
      printf '%s=%s\n' "${s#*:}" "$(gcloud secrets versions access latest \
        --secret="uccc-genomics-${s%:*}" --project=<gsm-project>)" >> .env    # a later line overrides the placeholder
    done
    # the database password (uccc-genomics-db-password-onclappc02), URL-encoded into DATABASE_URL:
    printf 'DATABASE_URL=postgresql://<role>:%s@pg_main:5432/<database>\n' "$(gcloud secrets versions access latest \
      --secret=uccc-genomics-db-password-onclappc02 --project=<gsm-project> \
      | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip(), safe=""))')" >> .env

`uccc-genomics-session-secret` does not exist until a person creates it, once:

    python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" \
      | gcloud secrets create uccc-genomics-session-secret --data-file=- --project=<gsm-project>

**Migrations** are unchanged: `uv run alembic -c mcp/alembic.ini upgrade head` from the host
checkout when a release adds one (the app never migrates on start).

**Build, validate, up.** Agents never run `up`, `restart` or `down` against production.

    git pull && docker build -t uccc-genomics-app:$(git rev-parse --short HEAD) .
    # set APP_TAG in deploy/.env to that sha
    docker compose -f deploy/compose.yaml config -q    # -q: plain `config` prints the secrets
    docker compose -f deploy/compose.yaml up -d
    docker compose -f deploy/compose.yaml ps           # wait for "healthy"
    curl -sS https://<APP_HOST>/api/health             # {"status":"Healthy"}

Then sign in once: a group member gets in and `/api/me` answers; `/mcp` gives Traefik's 404.

**Logs.** `docker compose -f deploy/compose.yaml logs -f genomics-app`. The audit lines (one JSON
line per count or pivot) are on stdout; Docker rotates them at 10 x 50 MB.

**Rollback.** `docker image ls uccc-genomics-app`, set `APP_TAG` in `deploy/.env` to the previous
tag, `docker compose -f deploy/compose.yaml up -d`.

**monode follow-ups, for a person, before the first `up`:**

1. An A record for `<APP_HOST>` to the host's public IP, `proxied = false`, in
   `terraform/apps/dns/cancerdatasci_org.tf` (check with `dig` first; TLS-ALPN-01 cannot issue a
   certificate without it).
2. A second uptime check and alert policy in `terraform/apps/uccc_genomics/` on
   `https://<APP_HOST>/api/health` (status 200, body contains `Healthy`), like the existing one.
3. The GSM session secret above.

The Authentik redirect URI `https://<APP_HOST>/auth/callback` is already registered.

## Cleanup

Identified data must only ever exist in `$DATA/raw/` and `$DATA/genomics_phi.duckdb`.

```bash
rm -rf /tmp/caris* /tmp/fmi* ~/*_scratch*      # any sampled reports pulled for inspection
rm -f $DATA/*.duckdb.wal                        # stale WAL from an interrupted load
rm -f $DATA/.duckdb_init_*                      # shell init files (contain the DB key); regenerated by `genomics shell`
```

Never `--delete` toward the bucket or share; mirrors are read-only from the source's point of view.

## Known gaps

FMI viral calls (`fmi.non_human`) are loaded but not offered as a cohort filter until
someone with domain knowledge has reviewed them (`dashboard/COHORT_DISCOVERY.md` §1).

FMI reports without `variant-report` results (older ones) get short variants and amplification/loss
calls derived from the Genes block (#76), but not Genes-block rearrangement, truncation, deletion,
duplication or fusion names, nor biomarker calls (TMB, MSI, HRD, tumor fraction). An ambiguous bare
`loss` under `CDKN2A/B` and `p16INK4a loss and p14ARF loss …` names are skipped too. Derived
protein-change rows have no position, depth or cds_effect (except splice/promoter names), and
their tier is the inferred `likely_pathogenic`, pending confirmation. VUS on these reports come from
`VariantProperties` (#79) with gene and protein change only (no VAF, depth or position; cds_effect
only for splice/promoter names). VUS named as copy-number, rearrangement, fusion or truncation calls,
`p16INK4a … loss` names, and plain protein changes under a slash gene name (`CDKN2A/B` style) are
not derived.

## Not in scope

Caris XML/PDF/VCF, FMI PDFs, FMI panel gene lists (so `gene_tested` for FMI
is pertinent-negatives only), a full OncoTree ontology (the crosswalk covers
the terms seen so far; new vendor terms land as `OTHER` until added to the
CSV), publishing to cdsci-lake/R2 (PHI; the de-id file is still a
limited dataset under the DUAs — keep it on campus). `PLAN.md` has the
reasoning.
