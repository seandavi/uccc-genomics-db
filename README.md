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
                 $DATA/genomics.duckdb       schemas caris.*, fmi.*, unified.*   — de-identified, the one you query
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
  sql/caris_views.sql, fmi_views.sql, unified.sql
  data/disease_crosswalk.csv   vendor disease term -> OncoTree code/name, organ system, NCIt (-> reference.disease_crosswalk)
mcp/            genomics-mcp: read-only MCP server over the de-id file (mcp/README.md)
dashboard/      Observable Framework site over aggregates of the de-id file (below)
tests/          pytest: synthetic load -> deid -> unified, MCP query guard, dashboard loader governance
```

```bash
uv run pytest          # ~30 s; the loader tests skip when $DATA/genomics.duckdb is absent
cd dashboard && npm test   # cohort page arithmetic
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
`cna`, `fusion`, `biomarker` (long: TMB/MSI/LOH/PD-L1), `gene_tested`
(Caris wild-type records + FMI pertinent negatives). Each is a
`UNION ALL BY NAME` across vendors with a `vendor` column; vendor-specific
detail stays in `caris.*` / `fmi.*` and joins back on `report_id`.
`report.disease_text` / `oncotree_code` / `organ_system` / `ncit_code` come from
`reference.disease_crosswalk` (hand-curated, in the package) where the vendor's
term is mapped; unmapped terms keep the vendor string as `disease_text` with
`oncotree_code = 'OTHER'`, and `raw_disease_text` always has the original.

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
  column of the output.

## Dashboard

`dashboard/` is an [Observable Framework](https://observablehq.com/framework/)
site: five pages of aggregates over `genomics.duckdb`. Two data loaders
(`src/data/summary.json.py`, `src/data/cohort.json.py`) run at build time,
drop every cell under `MIN_CELL = 5` and emit no row-level ids; the pages are
pure client-side filtering over that JSON.

1. **Overview** (`/`) — counts, reports by collection year, assays, top diseases per vendor.
2. **Cohort exploration** (`/cohort`) — gene(s) × disease(s) × vendor × year window × VUS.
   Headline counts and prevalence come from all-years totals (year × disease × gene cells
   are mostly suppressed); expected accrual = prevalence × tested volume in the window;
   the arithmetic lives in `src/components/cohort.js` and is covered by `npm test`.
3. **Genes** (`/genes`) — alteration frequency by gene, disease × gene heatmap, exact protein changes within a gene (sub-floor changes pooled as "other"), one gene or one exact alteration across diseases.
4. **Biomarkers** (`/biomarkers`) — TMB, MSI, PD-L1, LOH, VAF distributions, and every other Caris IHC marker (HER2, ER/PR, AR, MMR, ALK, CLDN18, FOLR1 …) by disease with calls shown as Caris reports them. FMI has no IHC.
5. **Coverage & quality** (`/coverage`) — panels, gene coverage, report status, purity, known gaps.

Google Analytics (`G-HR1PFD75WN`) is in the page head.

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

The site only ever contains suppressed aggregates, but it does leave campus:
if the DUA reads "data or any derivative", host it on the box behind Traefik
instead (nginx over `dist/`, IP allowlist).

## Cleanup

Identified data must only ever exist in `$DATA/raw/` and `$DATA/genomics_phi.duckdb`.

```bash
rm -rf /tmp/caris* /tmp/fmi* ~/*_scratch*      # any sampled reports pulled for inspection
rm -f $DATA/*.duckdb.wal                        # stale WAL from an interrupted load
rm -f $DATA/.duckdb_init_*                      # shell init files (contain the DB key); regenerated by `genomics shell`
```

Never `--delete` toward the bucket or share; mirrors are read-only from the source's point of view.

## Not in scope

Caris XML/PDF/VCF, FMI PDFs, FMI panel gene lists (so `gene_tested` for FMI
is pertinent-negatives only), a full OncoTree ontology (the crosswalk covers
the terms seen so far; new vendor terms land as `OTHER` until added to the
CSV), publishing to cdsci-lake/R2 (PHI; the de-id file is still a
limited dataset under the DUAs — keep it on campus). `PLAN.md` has the
reasoning.
