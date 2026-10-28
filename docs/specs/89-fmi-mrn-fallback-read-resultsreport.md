# Spec #89: FMI MRN fallback, read `ResultsReport/CustomerInformation/MRN`

`fmi.rows_for()` reads the MRN only from `FinalReport/PMI/MRN`. FoundationOne Monitor XML has no
`FinalReport` (so no `PMI`) but carries the MRN at `ResultsReport/CustomerInformation/MRN`, and
some regular reports have an empty PMI MRN with a value there. Those reports load with
`fmi.report.mrn` NULL. Monitor files also carry no name or DOB, so `deid` gives each one a
per-report `research_id` (`'nopid:' || vendor || id`). The Monitor report is then not linked to
the same patient's other reports, and patient counts in the de-id file and the cohort tool are
inflated.

All examples below are synthetic. Facts about the real files are structural only (no values, no
counts).

## Findings (checked 2026-10-28 by the supervisor on all real FMI XML: element names and presence only)

- `CustomerInformation` is always a direct child of the root `ResultsReport`, never inside
  `FinalReport`. It appears in Monitor files and in regular files.
- Its children are exactly `CSN`, `MRN`, `NPI`, `PhysicianId`, `ReferenceID` and `TRF`. It has
  **no** name, DOB, collection date or received date, so the MRN is the only identity field
  worth a fallback. Monitor reports keep NULL name, DOB and dates.
- `CSN` (an encounter number), `TRF` and `ReferenceID` are identifiers. This change doesn't load
  them (Non-goals).
- Most reports whose PMI MRN is empty have no MRN anywhere (FMI's known gap). Most Monitor files
  do have `CustomerInformation/MRN`.

## Goal

1. `fmi.report.mrn` = the digits of `FinalReport/PMI/MRN`, else the digits of
   `ResultsReport/CustomerInformation/MRN`, else NULL. Both use the same digit normalization. A
   value with no digits (e.g. `N/A`) counts as empty, so the fallback applies to it.
2. A new PHI-side column `fmi.report.mrn_source` records which source was used: `'pmi'`,
   `'customer_information'` or NULL when there's no MRN. `deid` drops it, so it never reaches
   `genomics.duckdb`.
3. `research_id` follows from `mrn` as for every other report: `deid.IDENTITY["fmi"]` already
   reads `fmi.report.mrn`. A Monitor report with `CustomerInformation/MRN` gets the same
   `research_id` as that patient's other FMI and Caris reports.
4. The #81 duplicate-`ReportId` identity check (`fmi.patient_identity`) uses the same identity,
   including the fallback. It reads `report[7]`, the `mrn` field that Goal 1 now fills, so it
   needs no code change. A test pins the behaviour.

### This changes `research_id` for the affected reports (a correction)

For a report whose MRN exists only in `CustomerInformation` (mostly Monitor reports), the
`research_id` moves from a per-report id (keyed hash of `'nopid:fmi' || report_id`, or of
`last|first|dob` for a regular report that has those) to the patient's id (keyed hash of the MRN).
Its date-shift offset moves with it (`deid` keys the shift on the same identity). Monitor reports
carry no dates, so nothing visible shifts for them. This is a deliberate correction: the patient
key changes only for reports that were wrongly unlinked. For every report with a PMI MRN, and
for every report with no MRN anywhere, `research_id` is the same as before for the same key.
`report_id` is unchanged for every report. `deid.py`'s hashing doesn't change.

Consequences that the README states (Design §4):

- Patient counts (`unified.patient`, `mart.*`, the cohort API, the dashboard) drop by the number
  of Monitor reports that now link to an existing patient.
- Any downstream list that held the old per-report `research_id` of an affected report (a cohort
  list exported from MCP, an IRB delivery) won't find it after the next rebuild: that report now
  sits under the patient's `research_id`. Saved cohorts in Postgres hold definitions and
  suppressed counts, not ids, so their stored definitions are unaffected. A recount of a saved
  snapshot can differ from the stored one.

This doesn't contradict AGENTS.md's rule that `research_id` stays stable "for the same key and
same patient". The rule protects the hashing and the identity of correctly identified patients.
Here the input identity of mis-identified reports is fixed. The spec says so and the README
records it.

## Non-goals

- Name, DOB, collection date or received date from `CustomerInformation`: there are none
  (Findings).
- Loading `CSN`, `NPI`, `PhysicianId`, `ReferenceID` or `TRF`. If one is ever loaded it must be
  PHI-side only, dropped or hashed by `deid`, and covered by the leak check. That is a separate
  issue.
- Any change to `deid.py` beyond adding `mrn_source` to `DROP`. No change to `IDENTITY`, id
  hashing, date shifting or the leak check.
- No change to `unified.sql`, `mart.sql`, `fmi_views.sql`, `caris.py`, the #81 choice rule
  (`choice_key`, `CHOICE`) or the `genes_block_*` parsers.
- No new output path and no suppression change. Only the `research_id` values change, and those
  reach the dashboard loader (`MIN_CELL = 5`), the cohort API (floored counts, secondary
  suppression, whole-cohort rule) and MCP through `unified.*` / `mart.*`, which already apply
  their small-cell rules.
- Nothing under `dashboard/`, `web/`, `mcp/` or `systemd/` changes. No new dependency.
- Re-checking identified deliveries (IRB) and before/after counts on the real data is the
  orchestrator's job on the host after the daily rebuild. The numbers don't go in GitHub.

## Design

### 1. `src/uccc_genomics/fmi.py`

**DDL**: append one column at the **end** of `report`, after `source_file`, so every existing
tuple index (`report[2]`, `[7]`, `[8]`, `[10]`, `[11]`, `[35]` used by `choice_key` and
`patient_identity`) stays the same:

```sql
  ..., n_amendments INT, pathologist_comment VARCHAR, source_file VARCHAR, mrn_source VARCHAR);
```

**New helper** after `b()`:

```python
def mrn_digits(x):
    """Digits of an MRN text, else None (absent, empty, or no digits)."""
    return ("".join(ch for ch in x if ch.isdigit()) or None) if x else None
```

**`rows_for`**: replace

```python
    mrn = txt(pmi, "MRN")
    mrn = "".join(ch for ch in mrn if ch.isdigit()) if mrn else None
```

with

```python
    # PMI MRN, else ResultsReport/CustomerInformation/MRN: Monitor files have no PMI but carry it
    # there, and some reports leave the PMI copy empty (#89). CustomerInformation has no name/DOB/dates.
    pmi_mrn, ci_mrn = mrn_digits(txt(pmi, "MRN")), mrn_digits(txt(root.find("CustomerInformation"), "MRN"))
    mrn, mrn_source = (pmi_mrn, "pmi") if pmi_mrn else (ci_mrn, "customer_information" if ci_mrn else None)
```

and append `mrn_source` as the last element of the `report` tuple, after
`os.path.relpath(path, RAW)`. The tuple then has 39 fields, matching the DDL; `bulk_insert`
asserts the count.

- `txt(None, ...)` already returns None, so a file without `CustomerInformation` needs no special
  case.
- Small behaviour change: a PMI MRN with no digits used to load as `''`. Now it is NULL (or the
  fallback). Both `deid.IDENTITY` (`nullif(..., '')`) and `patient_identity` (`if mrn:`) treat
  `''` and NULL the same, so no `research_id` changes from this for a report with no fallback.

**`patient_identity`**: code unchanged. Docstring becomes
`"""deid.IDENTITY for one fmi.report row: MRN digits (PMI, else CustomerInformation), else
lower(last)|lower(first)|dob, else None."""`.

**Module docstring**: no change needed.

### 2. `src/uccc_genomics/deid.py`

Add `"mrn_source"` to `DROP`. Nothing else changes. The column holds no identifier, but the issue
keeps it PHI-side only: it marks which reports came through the fallback, which is load
provenance, not research data.

### 3. Vendor source fields (PLAN.md mapping)

| column | source |
|---|---|
| `fmi.report.mrn` | `FinalReport/PMI/MRN`, else `ResultsReport/CustomerInformation/MRN`; digits only; NULL if neither has a digit (PHI file only, dropped by `deid`) |
| `fmi.report.mrn_source` | `'pmi'` / `'customer_information'` / NULL: which of the two gave `mrn` (PHI file only, dropped by `deid`) |

PLAN.md's mapping row for `patient` (`report.mrn`) still holds and doesn't change.

### 4. `README.md`

- Schemas, `fmi.*`: change "`report` (one per ReportId; FoundationOne Monitor files have no
  FinalReport, so their id is the file name and they carry no patient block)" to "`report` (one
  per ReportId; FoundationOne Monitor files have no FinalReport, so their id is the file name and
  they carry no name, DOB or dates. Their MRN comes from `ResultsReport/CustomerInformation`, as
  does the MRN of a report whose PMI MRN is empty; `mrn_source` says which, PHI-side only)".
- De-identification, after the `research_id` bullet, add: "FMI's MRN is the PMI copy, else
  `ResultsReport/CustomerInformation/MRN` (#89). That fallback changed `research_id` for the
  reports it reaches, mostly FoundationOne Monitor, from a per-report id to the patient's. It
  was a correction: patient counts dropped, and a downstream list holding an affected report's
  old `research_id` no longer finds it."

`docs/ARCHITECTURE.md`, `dashboard/COHORT_DISCOVERY.md`, `dashboard/COHORT_TOOL.md`, `PLAN.md`,
`AGENTS.md` and the MCP schema text don't change: none of them describes where FMI's MRN is read,
and no de-id column changes.

## Acceptance criteria

- [ ] A Monitor-shaped file (no `FinalReport`) with `CustomerInformation/MRN` = `000-123456`
      loads with `mrn = '000123456'` and `mrn_source = 'customer_information'`.
- [ ] In the de-id file that Monitor report has the same `research_id` as the same patient's
      regular FMI report and Caris case; `unified.report` groups it with them.
- [ ] A Monitor file without `CustomerInformation`, or with an empty or no-digit MRN there,
      loads with `mrn` and `mrn_source` NULL and keeps its own per-report `research_id`.
- [ ] A regular report with both MRNs present uses the PMI one (`mrn_source = 'pmi'`).
- [ ] A regular report with an empty or no-digit PMI MRN and a `CustomerInformation/MRN` uses the
      latter (`mrn_source = 'customer_information'`).
- [ ] Two files of one `ReportId`, one with the PMI MRN and one with only
      `CustomerInformation/MRN` (same digits), are one patient for #81: the full file loads, the
      other goes to `fmi.duplicate_file`, and neither goes to `load_error`.
- [ ] `mrn_source` exists in `phi.fmi.report` and in no table of the de-id file; `deid`'s leak
      check passes with `CustomerInformation` identifiers (`TRF…`) present in the raw XML.
- [ ] `deid.py` differs only by `"mrn_source"` in `DROP`; `unified.sql`, `mart.sql`,
      `choice_key` and `patient_identity`'s code are unchanged.
- [ ] README updated as in Design §4.
- [ ] `uv run pytest -q` passes. Dashboard and web checks n/a.

## Test plan

All in `tests/test_pipeline.py`, synthetic XML only, in `tmp_path` / a temp `DATA` via
`pipeline()`. No `$DATA/raw`, no PHI file.

**Fixture helper** (module level, before `fmi_report`):

```python
def with_customer_information(xml, mrn):
    """`xml` with a ResultsReport/CustomerInformation block (FMI's children, synthetic values) carrying `mrn` (#89)."""
    return xml.replace("<ResultsReport>", "<ResultsReport>\n <CustomerInformation><CSN>9000001</CSN>"
                       f"<MRN>{mrn}</MRN><NPI>1234567890</NPI><PhysicianId>999</PhysicianId>"
                       "<ReferenceID>REF-1</ReferenceID><TRF>TRF00001</TRF></CustomerInformation>", 1)
```

`fmi_report` gains `ci_mrn=None`: after building `xml` as today, return
`with_customer_information(xml, ci_mrn)` when `ci_mrn is not None`. Docstring: append "; ci_mrn
adds a CustomerInformation block carrying that MRN".

`TRF00001` matches `deid.ID_PATTERN`, so a pipeline run where any `CustomerInformation` value
reached a copied text column would fail the leak check.

**Tests**

1. `test_fmi_mrn_fallback(tmp_path)`: a unit test on `rows_for`. Write each XML to
   `tmp_path / "r.xml"` and compare `(report[7], report[-1])` for `report, _ = rows_for(path)`:
   - `fmi_report("ORD-0007001-01", ci_mrn="0000999999")` → `(MRN, "pmi")`. PMI wins.
   - `fmi_report("ORD-0007001-01", mrn="", ci_mrn="000-123456")` → `(MRN, "customer_information")`.
   - `fmi_report("ORD-0007001-01", mrn="N/A", ci_mrn=MRN)` → `(MRN, "customer_information")`.
   - `with_customer_information(FMI_MONITOR, "000-123456")` → `(MRN, "customer_information")`.
   - `FMI_MONITOR` → `(None, None)`; `with_customer_information(FMI_MONITOR, "")` → `(None, None)`;
     `with_customer_information(FMI_MONITOR, "N/A")` → `(None, None)`.
   - `fmi_report("ORD-0007001-01", mrn="", ci_mrn="")` → `(None, None)`;
     `fmi_report("ORD-0007001-01", mrn="N/A")` → `(None, None)` (was `''`).
   - `patient_identity` of `fmi_report("ORD-0007001-01", mrn="", ci_mrn=MRN)` == `MRN`.
   - `len(report) == 39`, which pins `mrn_source` as the last field.
2. `monitor_mrn_db` module fixture:
   `pipeline(..., {"ORD-0001234-01.xml": FMI, "ORD-0005678-01.xml": with_customer_information(FMI_MONITOR, "000-123456"), "ORD-0005679-01.xml": FMI_MONITOR})`
   (default Caris case, same `MRN`).
   `test_fmi_monitor_links_by_customer_information_mrn(monitor_mrn_db)`:
   - `set(SELECT report_id, mrn, mrn_source FROM phi.fmi.report)` ==
     `{("ORD-0001234-01", MRN, "pmi"), ("ORD-0005678-01", MRN, "customer_information"), ("ORD-0005679-01", None, None)}`.
   - `sorted(n for _, n in SELECT research_id, count(*) FROM db.unified.report GROUP BY 1)` ==
     `[1, 3]`. The group of 3 holds `db.caris.report`'s `research_id`, so the Caris case, the
     regular FMI report and the linked Monitor report share one id, and the unlinked Monitor
     report has its own.
   - `count(*) FROM db.unified.patient` == 2.
   - `count(*) FROM information_schema.columns WHERE table_catalog = 'db' AND column_name = 'mrn_source'`
     == 0, and `== 1` for `table_catalog = 'phi'`.
3. #81 identity with the fallback: add one pair to the `dup_db` fixture:
   `"ORD-0005555-01.xml": fmi_report("ORD-0005555-01")` (full, PMI MRN) and
   `"ORD-0005555-01_v2.xml": fmi_report("ORD-0005555-01", mrn="", full=False, ci_mrn=MRN)`
   (reduced, MRN only in `CustomerInformation`). Without the fallback the reduced copy's identity
   would be `doe|jane|1930-02-03` and the pair would be a conflict, so this pins Goal 4. Update:
   - `test_fmi_duplicate_report_loads_full_file`: the expected `(report_id, source_file)` set
     gains `("ORD-0005555-01", "fmi/ORD-0005555-01.xml")`, and the per-id loop covers
     `ORD-0005555-01` with the same counts.
   - `test_fmi_duplicate_file_log`: the expected set gains
     `("fmi/ORD-0005555-01_v2.xml", "fmi/ORD-0005555-01.xml", "variant_elements")`; `load_error`
     is still exactly 3 rows.
   - `test_fmi_duplicate_deid`: unchanged (still one distinct `research_id`, equal to Caris's).
4. `test_phi_columns_are_gone_and_ids_are_hashed`: add `"mrn_source"` to the set of columns that
   must be absent from the de-id `caris` / `fmi` schemas.
5. Existing tests pass otherwise unchanged. `monitor_db` / `wts_db` use `FMI_MONITOR` without
   `CustomerInformation`, so their Monitor report stays unlinked; `test_fmi_patient_identity`'s
   `mrn="N/A"` case still falls to the name branch.

Checks: `uv run pytest -q`. Dashboard `npm test` n/a (no dashboard change). Web check n/a.

## Risks

- **Counts move.** Patient counts drop as Monitor reports join their patients. Cohort results by
  patient scope can change (a Monitor finding now counts toward the patient who had the tissue
  report). That's the fix. Real before/after numbers are checked on the host and don't go in
  GitHub.
- **Downstream ids shift** for the affected reports (see "This changes `research_id`"). The README
  records it, and the PR text must say it.
- **Wrong MRN in `CustomerInformation`.** If FMI ever put a different patient's MRN there, a report
  would join the wrong patient. PMI wins whenever it has digits, so that can only happen where PMI
  is empty. #81's check would catch a disagreement between files of one `ReportId`. No other
  cross-check exists, and none exists for the PMI MRN either.
- **Seam.** `fmi.py` feeds every FMI consumer, and `deid.DROP` is the PHI column list. For a report
  with a PMI MRN, every loaded value is unchanged apart from the new `mrn_source = 'pmi'`.
  `report_id` can't change. `mrn_source` is dropped (test 4), and the `CustomerInformation`
  identifiers aren't loaded (the leak check with `TRF00001` in tests 2 and 3).
- **PHI.** The fallback MRN lives only in `phi.fmi.report.mrn`, which `deid` already drops; it
  reaches the de-id file only as the keyed `research_id` hash.
