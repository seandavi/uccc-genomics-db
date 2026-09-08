# Cohort discovery and feasibility tool

Design for the tool Sean asked for on 2026-09-08: "fine tuning of patient
selection based on disease, demographics available (age, gender), and assay
data, filtered by dates", with patient counts and per-year accrual so a user
can judge trial feasibility. Inputs: issues #18 (exact protein change) and
#22 (Caris IHC calls). All numbers below were measured against the
de-identified DuckDB on 2026-09-08 with `uv run python` from the repo root;
the scripts are one-off and not committed.

## a. What users need

A trialist or disease-group lead wants to know, before writing a protocol,
how many UCCC patients would have been eligible and how fast they show up.
Today's cohort page answers "how many reports carry an alteration in gene X
in disease Y" and estimates accrual by multiplying an all-years prevalence
by tested volume. It cannot narrow by sex, age, assay class, exact protein
change or biomarker call, and it counts reports rather than patients.

Three questions the tool must answer directly:

1. "KRAS G12C non-small cell lung cancer, aged 18 to 75, tested by liquid
   biopsy, collected 2023 or later. How many patients, and how many per year?"
2. "HER2-low or HER2-positive breast cancer by Caris IHC, female, 2022 to
   2025. How many patients could a HER2-directed ADC study screen?"
3. "MSI-high or TMB-high endometrial or colorectal cancer, any vendor, last
   three years, patients not reports."

The answer shape is the same each time: patients matching, reports matching,
patients by collection year, and a few breakdown bars (disease, vendor and
assay class, alteration class, sex, age band) so the user can see what the
cohort is made of and where to loosen a filter.

## b. What the data supports

### Size and dimensions

| Measure | Value |
|---|---|
| Reports | 5,874 (Caris 2,351, FMI 3,523) |
| Patients (distinct `research_id`) | 5,412 |
| Patients with exactly one report | 5,009 (93%) |
| Patients tested at both vendors | 51 |
| Collection years present | 2005 to 2027 (2027 is date-shift spillover; 82 FMI reports have no date) |
| Reports per year, 2023 to 2026 | 508, 697, 1,007, 734 |
| Distinct `disease_text` | 60 (50 have 5 or more patients) |
| Distinct `organ_system` | 30 |
| Distinct `assay_name` / `assay_class` | 15 / 3 (tissue, liquid, heme) |

Because 93% of patients have one report, patient and report counts differ
by a few percent on most cohorts. The tool should still count patients,
because that is the number a protocol needs, and the difference grows for
longitudinal diseases (breast: 432 reports, 365 patients).

### Demographics available

| Field | Where | Completeness | Notes |
|---|---|---|---|
| Sex (`gender`) | `unified.report`, both vendors | 100% | FMI mixes `Male` and `male`; normalise with `lower()`. No patient has conflicting values across reports. |
| Age at collection | `caris.specimen.age_at_collection`, Caris only | 100% of Caris reports, but see next row | Not on `unified.report`; the tool must join it in or the unified view must expose it. |
| Age, Caris liquid | same | unusable | All 813 liquid-biopsy specimens carry a sentinel value that the de-id cap turns into 89. Tumor specimens: 27 of 2,345 at 89, which is plausible. Treat liquid age as unknown until the source field is checked. |
| Age, FMI | none in the de-id file | 0% | `fmi.report.dob` is loaded into the PHI file and dropped by `deid.py` without deriving an age. Deriving `age_at_collection` before the drop is a small pipeline change; DOB completeness in the PHI file was not measured here. |
| Race, ethnicity, vital status, stage | not present in either vendor feed | | The vendors do not send them. |

So today an age filter applies only to Caris tissue reports (1,939 of 5,874).
With the deid change it would cover FMI as well. The tool must show "unknown"
as an age band and say which reports it covers.

Caris tissue age distribution: under 40: 141, 40s: 227, 50s: 366, 60s: 744,
70s: 684, 80 and over: 183. Cancer-typical.

### How many cells survive the small-cell floor

Cells are counted on distinct patients. `cells_ok` is cells with 5 or more
patients; `pct` is the share of patient-cells that live in surviving cells,
which is the share of the population a static cube could still describe.

| Cube (grain) | cells | cells_ok | pct of patients in surviving cells |
|---|---|---|---|
| disease × year | 551 | 244 | 90.0 |
| disease × vendor × assay class × year | 854 | 306 | 83.0 |
| disease × sex × vendor × class × year | 1,174 | 324 | 74.5 |
| disease × sex × age band (4) × vendor × class × year | 1,517 | 333 | 64.7 |
| disease × sex × age band, all years | 278 | 165 | 95.9 |
| disease × gene, all years | 7,012 | 1,383 | 72.1 |
| disease × gene × year | 18,044 | 987 | 30.2 |
| disease × gene × sex × age band | 11,572 | 1,281 | 53.8 |
| disease × gene × sex × age × vendor × class × year | 23,148 | 678 | 16.5 |
| gene × protein change, all diseases and years | 16,442 | 450 | 27.9 |
| disease × gene × protein change, all years | 20,421 | 286 | 14.3 |
| disease × gene × protein change × year | 23,798 | 136 | 5.0 |
| disease × gene × protein change × sex × age × vendor × class × year | 24,851 | 92 | 2.6 |

Reading: every filter dimension added to a pre-aggregated cube roughly
halves the share of the population it can still describe. At the grain the
requirement asks for (exact change plus demographics plus year) a static
cube keeps 2.6% of the data. This is the number that decides the
architecture.

The reason a live query does better is not more data but where the floor
is applied. A cube must suppress every fine cell before publication. A query
suppresses only the answer the user asked for, which is one number over the
whole filter, so a cohort of 9 patients spread over four years is
publishable as 9 even though every per-year cell is under 5.

Worked example, KRAS G12C in non-small cell lung cancer:

| Ask | Patients |
|---|---|
| all years | 12 |
| collected 2023 or later | 9 |
| liquid biopsy, any year | 2 (shown as "<5") |
| per year: 2018, 2019, 2023, 2025, 2026 | 1, 2, 4, 2, 3 (every cell "<5") |

A static cube shows nothing for this cohort. A live query shows 12 and 9 and
an honest "<5 per year" chart. That is the whole feasibility story for the
first example question.

### Uniqueness, which bounds the privacy risk

| Quasi-identifier tuple | Patients alone in their cell |
|---|---|
| disease × sex × year | 270 of 5,412 |
| disease × sex × age band × vendor × class × year | 667 of 5,412 |
| disease × gene (pathogenic), patient-gene pairs | 3,497 of 32,673 |

So 12% of patients are unique on the demographic tuple alone. A live
endpoint that returns exact counts for any filter lets a user who already
knows one patient's tuple learn that patient's mutation status by
differencing two queries. Section c covers the mitigations.

### Query cost

One cohort query (report join variant, four filters, distinct patients)
runs in under 20 ms on the 1.9 GB encrypted file; five in a row took 90 ms
including connection reuse. Load is not a concern at this audience size.

## c. Architecture options

### (i) Bigger static cube

Extend `cohort.json.py` with sex, age band, assay class, exact protein
change and biomarker call dimensions, keep the page client-side.

| | |
|---|---|
| Filters | All of them, but as marginals. Intersections are estimated by independence (prevalence × volume), as the page does today. |
| Counts | Estimates, not counts, for any combination beyond two dimensions. Patient counts only where the all-years cell survives. |
| Privacy | Same as today. Nothing changes at query time; the floor is applied once at build. No differencing risk beyond what the static site already carries. |
| Effort | 2 days (loader sections, page controls, `cohort.js` arithmetic, tests). |
| Operations | None new. Built by the existing daily service. |
| Ceiling | 64.7% of patients describable at the demographic grain, 16.5% with gene, 2.6% with exact change. The example questions cannot be answered with counts. |

### (ii) On-host cohort query API behind Cloudflare Access

A small HTTP service on onclappc02 that accepts a fixed set of filter
parameters (no SQL from the client), runs one parameterised query against
the de-id file, applies the floor to every number in the response, and
returns JSON. The dashboard page calls it. Two ways to put it on the
Access-protected hostname:

- (ii-a) Cloudflare Tunnel: `cloudflared` as a systemd user service, ingress
  to `127.0.0.1:8090`, DNS CNAME to the tunnel. Outbound-only, origin not
  reachable from the internet. A new component on the host; the platform
  docs in `monode/infrastructure` have no tunnel today.
- (ii-b) Traefik: the platform's existing pattern for proxied (orange-cloud)
  hostnames with the Cloudflare Origin Certificate, as `cmgd` and
  `cfde-atlas` already do. A file-provider router for
  `Host(uccc-genomics.cancerdatasci.org) && PathPrefix(/api)` to the host
  process. No new daemon.

Either way the Worker changes from `custom_domain = true` to a zone route,
with a five-line script that serves assets and passes `/api/*` through to
the origin. Access stays on the hostname, so the API is behind the same
one-time PIN and the browser sends the same cookie; no CORS. The API must
also validate the `Cf-Access-Jwt-Assertion` header against the Access
team's certificates, both so a direct hit on the origin IP is refused
(matters for ii-b) and to get the user's email for the audit log.

| | |
|---|---|
| Filters | Everything in the requirement, combined freely with AND across filter types and OR within one. Exact protein change, alteration class, biomarker and IHC calls, sex, age band, vendor, assay class and name, year range. |
| Counts | Exact patient and report counts for the whole filter, per-year patients, and breakdowns, each cell floored separately. |
| Privacy | Row-level data never leaves the host; the client never sends SQL. New risk: differencing. Mitigations, in order of value: (1) floor on every published number including breakdown bars, (2) audit log of user email, parameters and result for every call, (3) no negation or complement filters, (4) a fixed vocabulary for every parameter, taken from the DB, so free text cannot probe, (5) optionally round counts to the nearest 5 above the floor, which blunts differencing at the cost of precision users will notice at this scale (9 becomes 10), (6) a per-user rate limit. i2b2 and TriNetX solve the same problem with obfuscation of ±3 and a lockout after repeated near-identical queries. The audience is institutional staff behind Access who could read the EHR directly, so the residual risk is inference about a patient the user already knows. |
| Effort | 4 to 5 days: API with tests 1.5, edge routing and Access JWT 1, page 1.5, deid age derivation 0.5, docs 0.5. |
| Operations | One always-on host process with `Restart=always` (copy `systemd/genomics-mcp.service`), a `/health` endpoint that returns 200 and "Healthy" only if the DB opens, an Access bypass policy on `/api/health` so a GCP uptime check per `OBSERVABILITY.md` can probe it, and a row in the platform `INDEX.md`. The service must reopen the DB after the daily rebuild replaces the file, so open a connection per request as the MCP server does. |

### (iii) Reuse the MCP server's sandbox

`mcp/src/uccc_genomics_mcp/server.py` already has `get_db()` and
`harden()`: read-only encrypted attach, `enable_external_access = false`,
`lock_configuration = true`, pinned by `tests/test_mcp_query.py`. The
cohort API should import those two functions and nothing else. It should
not be a route on the running MCP process and it should not expose the
free-SQL `query` tool to the web: that tool returns rows, which is
row-level de-identified data leaving campus, and the README says the de-id
file stays on campus under the DUAs. Keep `/mcp` on the tailnet for
analysts and give the web a fixed-parameter endpoint.

| | |
|---|---|
| Filters and counts | As (ii). |
| Privacy | As (ii), plus the tested file-system sandbox for free. A separate process on a separate port means a proxy misconfiguration cannot expose `/mcp`. |
| Effort | Saves about half a day of (ii) and, more importantly, reuses tests. |
| Operations | As (ii); same package, second entry point, second unit file. |

## d. Recommendation

Build (ii-b) using (iii): a fixed-parameter cohort API in the `mcp` package,
on the same hostname behind the same Access application, routed by Traefik
in the platform's existing proxied-hostname pattern, with the Worker
passing `/api/*` to the origin. Reasons:

1. The requirement is exact change plus demographics plus year. A static
   cube keeps 2.6% of the data at that grain. No amount of loader work
   fixes that; it is a property of pre-suppression.
2. Query-time suppression answers the example questions today (12 and 9 for
   KRAS G12C NSCLC) without any new data.
3. The sandbox, the encrypted read-only open, the systemd pattern and the
   Access hostname all exist. The new code is one query builder, one
   response floor, one JWT check and one page.
4. Traefik plus Origin Certificate is the documented convention on this
   host, so no new component and no new platform doc; a tunnel would need
   both. If Traefik to a host process proves awkward, (ii-a) is a drop-in
   swap at the same cost.

Do not do (i) as a stepping stone. It would spend two days on a ceiling the
requirement is already past, and #18 already covers the one static addition
worth having (exact change on the Genes page).

## e. Phased plan

### Phase 1: the smallest thing materially better than today's page

Scope: patient counts for any combination of disease, sex, age band, vendor,
assay class, gene, alteration class, exact protein change, VUS toggle and
year range. Biomarkers and IHC come in phase 2.

API, `GET /api/cohort`, all parameters repeatable, values validated against
vocabularies read from the DB at startup:

| Parameter | Vocabulary |
|---|---|
| `disease` | `unified.report.disease_text` |
| `organ` | `unified.report.organ_system` |
| `sex` | female, male |
| `age` | <50, 50-64, 65-74, 75+, unknown (Caris tissue only until deid derives FMI age) |
| `vendor` | caris, fmi |
| `assay_class` | tissue, liquid, heme |
| `gene` | genes with at least one non-VUS alteration |
| `alt_class` | pathogenic, vus, amplification, loss, fusion (default: everything except vus) |
| `aa` | protein change with `p.` stripped, only with exactly one `gene` |
| `year_from`, `year_to` | integers in the data's range |

Response, every count floored (values under 5 returned as `null`):

```json
{"patients": 9, "reports": 9,
 "by_year": [{"year": 2023, "patients": null}, ...],
 "by_disease": [...], "by_vendor_class": [...], "by_alt_class": [...],
 "by_sex": [...], "by_age": [...],
 "meta": {"min_cell": 5, "age_covers": "Caris tissue reports only"}}
```

Semantics: AND across parameters, OR within a repeated parameter. A patient
is counted in the year of their first qualifying report in the window. A
report qualifies if it carries at least one alteration that matches the
gene, class and change filters.

Page, `dashboard/src/cohort.md` rebuilt over the API (the static loader and
`cohort.js` stay until the page is replaced, then go):

Controls, top to bottom:

- Disease (multi-select, sorted by patient count) with an organ-system
  group toggle.
- Sex, age band, vendor, assay class (checkbox groups, all on by default).
- Gene (multi-select). When exactly one gene is chosen, a protein-change
  multi-select appears, listing the changes seen for that gene.
- Alteration class checkboxes and the VUS toggle.
- Year range (two sliders, defaults as today: end two years back).
- A "copy link" button: the filter state is the query string, so a link is
  a shareable cohort definition.

Outputs:

- Patients matching, reports matching, and the count of patients in the
  window, as three cards. Under 5 shows "<5".
- Per-year patients bar chart over the window, with "<5" markers on
  suppressed years and the window total in the title.
- Accrual per year over the window and the existing tier badge from
  `cohort.js` `TIERS`.
- Breakdown bars: by disease, by vendor and assay class, by alteration
  class, by sex, by age band. Each bar floored separately; a note says bars
  can sum below the total.
- A sentence stating what age covers and that dates are shifted.

Tests that pin phase 1:

- pytest, synthetic DB (the existing load, deid, unified fixture): no
  number anywhere in a response is between 1 and 4; no key named
  `research_id` or `report_id` appears; an unknown parameter or a value
  outside the vocabulary returns 400; `aa` without exactly one `gene`
  returns 400; a request without a valid Access JWT returns 401; the
  patient count for a two-report patient is 1; the hardened connection
  refuses `read_text` (already in `test_mcp_query.py`, reused).
- npm test: the page's display helpers (null to "<5", first-year
  assignment, accrual arithmetic) under node, as `cohort.test.js` does now.

Deployment steps, each reversible: unit file for the API; Traefik file
router; DNS record to orange-cloud on the campus IP; wrangler route and
pass-through script; Access bypass policy for `/api/health`; uptime check;
`INDEX.md` row.

### Phase 2

- Biomarker and IHC parameters: `tmb`, `msi`, `pdl1`, `her2`, `mmr` from
  `unified.biomarker.call_norm` (needs #22's HER2 normalisation).
- Derive `age_at_collection` for FMI in `deid.py` before dropping `dob`, and
  mark Caris liquid ages unknown at load.
- "Request this cohort" button that opens a mail to Sean with the filter
  definition, as the entry point to the PHI data-request path in #16.

### Phase 3, only if asked

- All-of gene logic (co-mutation cohorts) and negative filters (tested and
  wild-type, from `unified.gene_tested`), each of which needs its own
  differencing review before it ships.

## f. Open questions for Sean

1. Exact counts at 5 and above, or rounded to the nearest 5? Exact is what
   users want at this scale (9 versus 10 matters); rounding blunts
   differencing. The audit log is there either way.
2. Should `deid.py` derive FMI age from DOB before dropping it, and should
   the Caris liquid sentinel be nulled at load? Both need a rebuild. Is
   DOB populated on most FMI reports in the PHI file? Not measured here.
3. Does a counts-only endpoint over the de-id file fit the DUAs the same
   way the static aggregates do? Only floored counts leave the host, but
   the endpoint is reachable from off campus through Access.
4. Traefik plus Origin Certificate (platform pattern, origin reachable by
   IP, JWT check mandatory) or Cloudflare Tunnel (new component, origin
   unreachable)? The doc recommends Traefik.
5. Is a patient counted in the year of their first qualifying report, or in
   every year they had one? First year is proposed for accrual.
