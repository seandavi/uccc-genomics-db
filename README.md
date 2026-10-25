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
repo root, which `config.py` reads (copy `.env.example`). Caris creds are the `[default]` AWS profile; FMI needs
passwordless ssh to the FMI host.

## Run

```bash
uv sync
uv run genomics all                 # sync + load both vendors, then deid (~20 min, TPM CSVs dominate)
uv run genomics sync --vendor fmi   # or any single step / vendor
uv run genomics load --vendor caris
uv run genomics deid
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

## Layout

```
src/uccc_genomics/
  cli.py        genomics sync|load|deid|all [--vendor] | shell [--phi]
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

**`fmi.*`** — `report` (one per XML; FoundationOne Monitor files have no
FinalReport, so their id is the file name and they carry no patient block),
`sample`, `short_variant` (with `is_vus`, `subclonal`), `cna`, `rearrangement`,
`biomarker` (TMB, MSI, LOH…), `non_human`, `pertinent_negative`, `alteration`
(curated Genes block), `therapy`, `trial`, `amendment`, `load_error` (files that
failed to parse — nothing is dropped silently). Views `tmb`, `msi`, `loh`.

**`unified.*`** (de-identified file only) — `patient`, `report`, `variant`,
`cna`, `fusion`, `biomarker` (long: TMB/MSI/LOH/PD-L1 and the other Caris IHC markers), `gene_tested`
(Caris wild-type records + FMI pertinent negatives). Each is a
`UNION ALL BY NAME` across vendors with a `vendor` column; vendor-specific
detail stays in `caris.*` / `fmi.*` and joins back on `report_id`.
`variant.tier` (`pathogenic`, `likely_pathogenic`, `vus`, `likely_benign_or_benign`,
`unclassified`) is the one significance column to filter on, derived per vendor;
`is_vus` and `vendor_call` stay as the vendor's own flags, and the cohort API's
default "pathogenic" is the first two tiers. `variant.consequence` is lower case
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
specimen), `has_wts` (Caris RNA/cfTNA gene TPM file or `wtsExpression` records).
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
rows; amplification, loss and fusion rows have no tier. Viral findings, CNA copy number, VAF and
the `data`/`sequence` criteria are not in the mart.

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
process serves REST at `/api/*` (OpenAPI schema at `/api/openapi.json`; no Swagger UI) and MCP (Streamable HTTP, stateless) at
`/mcp` (POST only; `GET /mcp` is 405, no SSE stream), both thin layers over `cohort/`. Every request but `/api/health` needs a login through
`authen` (`--auth access|password|none`; `none`: no login,
local dev only). `count` and `pivot` are limited to 60 a minute per user
across both surfaces (a count or pivot the cohort module rejects, such as an unknown value or a pivot
with no rows/cols, still uses the limit; a body that fails schema validation does not) and logged to stdout as one JSON line each (user, cohort_id, definition,
suppressed patients). The MCP tools are `search_vocabulary`, `apply_op`, `count`, `pivot` and
`describe_definition`, plus the saved-cohort tools below; there is no SQL tool.

    uv run python -m uccc_genomics_mcp.authen    # once: put APP_USER and the printed APP_PASSWORD_HASH in .env
    uv run genomics-app --auth password --host <tailnet-addr> --port 8092 [--static <dir>]
    # http://<tailnet-addr>:8092/api/openapi.json, MCP clients at http://<tailnet-addr>:8092/mcp

`--static` serves a built front end at `/` (Discover, below). Development only: no systemd
unit or deploy yet.

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
link holding its definition. No third-party requests; the build sets a same-origin CSP.

    (cd web && bun install && bun run build)
    uv run genomics-app --auth password --host <tailnet-addr> --port 8092 --static web/dist
    # http://<tailnet-addr>:8092/

`bun run dev` serves the app with hot reload and proxies `/api` to a genomics-app on
127.0.0.1:8092. After changing a model in `cohort/` or `app.py`, run `bun run gen` (rewrites
`web/openapi.json` and `web/src/api.gen.ts`); pytest and `bun run typecheck` fail until you do.

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

## Not in scope

Caris XML/PDF/VCF, FMI PDFs, FMI panel gene lists (so `gene_tested` for FMI
is pertinent-negatives only), a full OncoTree ontology (the crosswalk covers
the terms seen so far; new vendor terms land as `OTHER` until added to the
CSV), publishing to cdsci-lake/R2 (PHI; the de-id file is still a
limited dataset under the DUAs — keep it on campus). `PLAN.md` has the
reasoning.
