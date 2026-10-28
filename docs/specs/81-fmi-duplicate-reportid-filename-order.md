# Spec #81: FMI duplicate ReportId, choose the file by content, not filename order

`fmi.load()` walks `raw/fmi/*.xml` in filename order and keeps the first file per `ReportId`; later
files with the same id go to `fmi.load_error` as `duplicate report_id`. FMI delivered some reports
twice: a full file (FinalReport + `<variant-report>` with short variants, CNAs, rearrangements,
VAF, depth, position) and a reduced copy (FinalReport only). The reduced copy sorts first, so the
full file is rejected and those reports fall back to the #76/#79 derived rows. The issue also
carries review finding code-r0-1 from #82 (the `is_vus` lookup compares normalized names against
raw `VariantProperty` names).

All examples below are synthetic. Facts about the real files are structural only (no counts).

## Findings (checked 2026-10-27, supervisor, all real FMI XML, aggregates only)

- A `ReportId` appears in at most two files. Every pair is one **full** file (has
  `<short-variant>` / `<copy-number-alteration>` / `<rearrangement>` elements) plus one **reduced**
  copy; never both full, never neither.
- The reduced copy never has a `<variant-report>` element at all.
- The full file always has a FinalReport, and its patient identity (MRN digits, else
  `lower(last)|lower(first)|dob`, as `deid.IDENTITY`) equals the reduced copy's in every pair.
- The full file's FinalReport matches the reduced copy's in every pair: same Genes/Alterations
  `(gene, name)` set, same `VariantProperties` set, same Trial and PertinentNegative counts,
  same `Version`, same amendment count.
- The reduced copy has the newer file mtime in every pair, so "newest file wins" would pick the
  wrong one.

So the full file is a strict superset of the reduced copy, and choosing it changes neither
`report_id` nor `research_id`.

## Goal

1. When several XML files parse to the same `ReportId`, load exactly one, chosen by content:
   the file with variant-report variant elements, then higher FinalReport `Version`, then more
   amendments, then newer mtime, then the larger relative path (only to make the result
   deterministic). Never filename order.
2. Only the chosen file's rows reach `fmi.*` (no variant rows from both files of a pair). The
   #76/#79 per-report rule ("derive from Genes block / VariantProperties only when the report has
   no `<short-variant>`") is evaluated on the chosen file, because each file's rows are built
   independently by `rows_for` and only the chosen file's rows are kept.
3. The non-chosen files are logged in a new PHI-side table `fmi.duplicate_file` with the chosen
   file and the reason; they no longer appear in `fmi.load_error`.
4. If files sharing a `ReportId` disagree on patient identity (never seen), load none of them and
   log every one to `fmi.load_error`.
5. code-r0-1: the `VariantProperties` VUS lookup set also holds normalized keys, so the Genes-block
   path, the VariantProperties dedup (#79) and the variant-report path agree on what is "the same
   variant".

### Why choose one file, not merge

The findings show the full file carries everything the reduced copy has (same FinalReport content,
same identity) plus the variant report. A merge (report-level fields from one file, variant tables
from another) adds code for a case that doesn't occur and opens the double-counting risk the issue
forbids. Choosing one file keeps every table coming from a single XML, as today.

### Why "load none" on an identity conflict

Two files claiming one `ReportId` with different patients means one of them is wrong, and there is
no content rule that says which. Loading either could attach a report's findings to the wrong
`research_id`, which then flows into cohort counts. Loading neither keeps wrong data out, and
`fmi.load_error` lists both files, so nothing is dropped silently (AGENTS.md). Today's behaviour
(first file by name wins) is no safer, just arbitrary.

## Non-goals

- No merge of rows across files. No change to `rows_for`'s per-file output except the `vus` set
  (Design §2).
- No "newest file wins" rule: the findings show it picks the reduced copy.
- No change to `deid.py`, the PHI column lists, id hashing, date shifting or the leak assert.
  `report_id` is the `ReportId` shared by every file of a pair, so its keyed hash is unchanged.
  `research_id` is unchanged because the chosen file's identity equals the other file's (enforced
  by Goal 4, not assumed). `fmi.duplicate_file` has no `report_id` column, so `deid.build` does
  not copy it (it copies only tables with the key column, as with `load_error`), and its file
  names never reach the de-id file.
- No new output path and no suppression change. More variant rows reach the dashboard loader
  (`MIN_CELL = 5`), the cohort API (floored counts, secondary suppression, whole-cohort rule) and
  MCP only through `unified.*` / `mart.*`, which already apply their small-cell rules.
- No change to `unified.sql`, `mart.sql`, `fmi_views.sql`, the `genes_block_*` parsers, the #76
  Genes-block derivation or the #79 VariantProperties derivation.
- No change to `sync()`. (GNU `tar xf` restores the archived mtime, so `os.path.getmtime` on the
  mirror is the share's mtime.)
- No new dependency. No change under `dashboard/`, `web/`, `mcp/` or `systemd/`.
- Re-checking the IRB delivery against the rebuilt data is the orchestrator's job on the host
  after the daily rebuild.

## Design

### 1. `src/uccc_genomics/fmi.py`, duplicate resolution

**DDL**: add one table after `load_error`:

```sql
CREATE TABLE duplicate_file (file VARCHAR, chosen_file VARCHAR, reason VARCHAR);
```

`file` and `chosen_file` are paths relative to `RAW` (`fmi/<name>.xml`), the same form as
`fmi.report.source_file` and `fmi.load_error.file`. The `ReportId` is
`fmi.report.report_id WHERE source_file = chosen_file`; no `report_id` column, on purpose
(Non-goals).

**New module-level constant and two functions** (place them after `rows_for`):

```python
# Rank of a file among files sharing a ReportId (#81), compared in this order; the max is loaded.
CHOICE = ("variant_elements", "version", "amendments", "mtime", "path")


def choice_key(path, report, t):
    """CHOICE tuple for one parsed file: has variant-report short variants, CNAs or rearrangements;
    FinalReport Version (-1 if absent); amendment count; file mtime; path relative to RAW."""
    return (bool(t["rearrangement"]) or any(r[-1] == "variant_report" for r in t["short_variant"] + t["cna"]),
            -1 if report[2] is None else report[2], report[35], os.path.getmtime(path), os.path.relpath(path, RAW))


def patient_identity(report):
    """deid.IDENTITY for one fmi.report row: MRN digits, else lower(last)|lower(first)|dob, else None."""
    mrn, dob, first, last = report[7], report[8], report[10], report[11]
    if mrn:
        return mrn
    return None if None in (last, first, dob) else f"{last.lower()}|{first.lower()}|{dob}"
```

Report tuple indexes, from `rows_for` / the DDL: `2` version, `7` mrn (already digits only, may be
`""`), `8` dob, `10` first_name, `11` last_name, `35` n_amendments. `dob` is compared as the XML
text; files of one report carry the same text, and a format difference counts as a conflict
(the safe side).

**`load()`** keeps its shape; the loop body changes from "first wins, later raise" to
"parse all, then resolve per `ReportId`":

```python
    parsed, errors = {}, []
    for path in files:
        try:
            report, t = rows_for(path)
        except Exception as e:  # noqa: BLE001 — logged to a table, never swallowed
            errors.append((os.path.relpath(path, RAW), f"{type(e).__name__}: {e}"[:300]))
            continue
        parsed.setdefault(report[0], []).append((path, report, t))
    reports, children, duplicates = [], {}, []
    for rid, cands in parsed.items():
        # Files of one ReportId must be one patient; otherwise load none (#81)
        if len({patient_identity(c[1]) for c in cands}) > 1:
            errors += [(os.path.relpath(c[0], RAW), f"ValueError: conflicting patient identity for report_id {rid}")
                       for c in cands]
            continue
        # FMI re-delivered some reports as a reduced copy without the variant report; the
        # filename order picked that copy (#81). Choose by content; log the others.
        keys = [choice_key(*c) for c in cands]
        best = max(range(len(cands)), key=keys.__getitem__)
        path, report, t = cands[best]
        reports.append(report)
        for k, rows in t.items():
            children.setdefault(k, []).extend(rows)
        for j, c in enumerate(cands):
            if j != best:
                reason = next(n for n, a, b_ in zip(CHOICE, keys[best], keys[j]) if a != b_)
                duplicates.append((os.path.relpath(c[0], RAW), os.path.relpath(path, RAW), reason))
```

then, after the existing `bulk_insert(con, "load_error", errors)`:

```python
    bulk_insert(con, "duplicate_file", duplicates)
```

- Add `"duplicate_file"` to the `DROP TABLE IF EXISTS` list and to the row-count print list.
- `reason` is the first `CHOICE` name where the chosen key and the other key differ. Keys never
  tie: the relative path is unique per file.
- The `seen` set and the `duplicate report_id` `ValueError` are removed; a file whose `rows_for`
  raises still lands in `load_error` exactly as today.
- Memory: every parsed file is held until resolution. `children` already holds every file's rows
  today, so the peak is about the same.
- Module docstring: after "Files that fail land in fmi.load_error instead of being dropped
  silently." add "A ReportId delivered in several files loads one, chosen by content
  (fmi.duplicate_file lists the others)."

### 2. `src/uccc_genomics/fmi.py`, `rows_for`: normalized VUS keys (code-r0-1)

Replace

```python
    vus = {(vp.get("geneName"), vp.get("variantName")) for vp in fr.findall(".//VariantProperties/VariantProperty")
           if b(vp.get("isVUS"))} if fr is not None else None
```

with

```python
    # VariantProperties lists only the VUS calls; absence => not VUS (when a FinalReport exists at all).
    # Raw names plus the parsed (gene, protein_effect) the short_variant rows carry, so an aliased
    # gene ("KMT2C (MLL3)") or a p16INK4a name matches its row on every path (#81).
    vus = None
    if fr is not None:
        vus = set()
        for vp in fr.findall(".//VariantProperties/VariantProperty"):
            if b(vp.get("isVUS")):
                vus.add((vp.get("geneName"), vp.get("variantName")))
                if sv := genes_block_short_variant(vp.get("geneName"), vp.get("variantName") or ""):
                    vus.add((sv[0], sv[2]))
```

(the existing comment line above the old expression is replaced by the new comment).

- The set only grows: every key it held before is still there, so no row that was `is_vus = true`
  becomes false.
- Genes-block rows already look up `(sg, prot)`, the normalized pair; a Genes-block alteration
  that is also a VUS under an aliased gene now gets `is_vus = true` (tier `vus`), and the #79 block
  still skips it as already derived, so it stays one row.
- Variant-report rows look up `(gene, protein-effect)`; FMI names those with the plain symbol, so
  a VUS listed under `KMT2C (MLL3)` or as `p16INK4a A57V` under `CDKN2A/B` now matches the
  `KMT2C` / `CDKN2A A57V` short variant. This is the same fix on the third path; without it the
  carried VUS of the duplicated reports could come back as `unclassified`.

### 3. Vendor source fields (PLAN.md mapping)

No new columns in any data table. `fmi.duplicate_file`:

| column | source |
|---|---|
| `file` | path of the non-chosen XML relative to `$DATA/raw` |
| `chosen_file` | path of the loaded XML for the same `FinalReport/ReportId` (= `fmi.report.source_file`) |
| `reason` | first `CHOICE` field that ranked `file` lower: `variant_elements` (`<short-variant>`, `<copy-number-alteration>`, `<rearrangement>` under `variant-report`), `version` (`FinalReport/Version`), `amendments` (count of `Amendmends/Amendmend`), `mtime`, `path` |

### 4. `README.md`

Schemas, `fmi.*`: change "`report` (one per XML; FoundationOne Monitor files …)" to
"`report` (one per ReportId; FoundationOne Monitor files have no FinalReport, so their id is the
file name and they carry no patient block)" and, after the `load_error` item, describe the new
table: "`load_error` (files that failed to parse, or files of one ReportId that disagree on the
patient — nothing is dropped silently), `duplicate_file` (FMI delivered some reports in two
files, a full one and a copy without the variant report: the file with variant-report variant
elements loads, then higher `Version`, more amendments, newer mtime; the others are listed here
with `chosen_file` and `reason`; PHI-side only)."

`docs/ARCHITECTURE.md`, `dashboard/COHORT_DISCOVERY.md`, `PLAN.md`, `AGENTS.md` and the MCP schema
text don't change: none describes which FMI file wins, and no `unified.*` / `mart.*` column
changes.

## Acceptance criteria

- [ ] Two files with one `ReportId`, one full and one reduced, load the full file whether the
      reduced copy sorts first or last and whether the full file's mtime is older or newer:
      `fmi.report.source_file` is the full file.
- [ ] That report's `fmi.short_variant` / `fmi.cna` rows are only the full file's
      `variant_report` rows (no `genes_block`, no `variant_properties`, no doubled rows);
      `fmi.alteration`, `therapy`, `trial`, `pertinent_negative`, `amendment` and
      `rearrangement` hold one file's rows, not two.
- [ ] The reduced file is in `fmi.duplicate_file` with `chosen_file` = the full file and
      `reason = 'variant_elements'`, and not in `fmi.load_error`.
- [ ] With both files full or both reduced, the tie-break is `version`, then `amendments`, then
      `mtime`, then `path`, and `reason` names the deciding field.
- [ ] Files of one `ReportId` with different patient identity: no `fmi.report` row for that id,
      every file in `fmi.load_error` with `conflicting patient identity`, none in
      `fmi.duplicate_file`.
- [ ] A file that fails to parse is still in `fmi.load_error` as today.
- [ ] The de-id file has no `duplicate_file` table and no `load_error` table; `deid` passes its
      leak check; the chosen report's `research_id` equals the same patient's Caris `research_id`.
- [ ] code-r0-1: a Genes-block alteration that is also a VUS under an aliased gene gets one
      `genes_block` row with `is_vus = true` (tier `vus`); a `variant_report` short variant whose
      VUS is listed under an aliased gene or a `p16INK4a` name gets `is_vus = true`.
- [ ] No change to `deid.py`, `unified.sql`, `mart.sql`, the `genes_block_*` parsers.
- [ ] `uv run pytest -q` passes. Dashboard and web checks n/a.

## Test plan

All in `tests/test_pipeline.py`, synthetic XML only, in `tmp_path` / a temp `DATA` via
`pipeline()`. No `$DATA/raw`, no PHI file.

**Fixtures** (module level, after `FMI_MONITOR`):

```python
def fmi_report(rid, mrn=MRN, full=True):
    """FMI as report `rid` for patient `mrn`; full=False is the reduced copy (no <variant-report>)."""
    xml = FMI.replace("ORD-0001234-01", rid).replace(f"<MRN>{MRN}</MRN>", f"<MRN>{mrn}</MRN>")
    return xml if full else re.sub(r"\s*<variant-report.*</variant-report>", "", xml, flags=re.S)
```

(add `import re` to the test module's imports; it isn't there today). The reduced copy keeps FMI's Genes block
(TP53 R175H, ERBB2 amplification) and VUS `PIK3CA E545K`, so if it were chosen it would produce
`genes_block` and `variant_properties` rows: their absence proves the full file won.

```python
@pytest.fixture(scope="module")
def dup_db(tmp_path_factory):
    # A: reduced copy sorts first ("." < "_"), written last (newer mtime, as on the share)
    # B: full file sorts first, written last (newer mtime)
    # C: one ReportId, two patients
    return pipeline(str(tmp_path_factory.mktemp("dup")), {
        "ORD-0002222-01_v2.xml": fmi_report("ORD-0002222-01"),
        "ORD-0002222-01.xml": fmi_report("ORD-0002222-01", full=False),
        "ORD-0003333-01_v2.xml": fmi_report("ORD-0003333-01", full=False),
        "ORD-0003333-01.xml": fmi_report("ORD-0003333-01"),
        "ORD-0004444-01.xml": fmi_report("ORD-0004444-01"),
        "ORD-0004444-01_v2.xml": fmi_report("ORD-0004444-01", mrn="0000777777"),
        "broken.xml": "<ResultsReport><nothing/></ResultsReport>"})
```

**Tests**

1. `test_fmi_duplicate_report_loads_full_file(dup_db)`:
   - `SELECT report_id, source_file FROM phi.fmi.report` = `{("ORD-0002222-01",
     "fmi/ORD-0002222-01_v2.xml"), ("ORD-0003333-01", "fmi/ORD-0003333-01.xml")}`.
   - for each of the two ids: `short_variant` count 4, all `source = 'variant_report'`;
     `cna` count 1, `source = 'variant_report'`; `rearrangement` 1; `alteration` 2;
     `therapy` 4; `trial` 2; `pertinent_negative` 1.
   - `PIK3CA E545K` on each id has `is_vus = true` (one row).
2. `test_fmi_duplicate_file_log(dup_db)`:
   - `SELECT file, chosen_file, reason FROM phi.fmi.duplicate_file` =
     `{("fmi/ORD-0002222-01.xml", "fmi/ORD-0002222-01_v2.xml", "variant_elements"),
       ("fmi/ORD-0003333-01_v2.xml", "fmi/ORD-0003333-01.xml", "variant_elements")}`.
   - `SELECT file, error FROM phi.fmi.load_error` =
     `{("fmi/ORD-0004444-01.xml", "ValueError: conflicting patient identity for report_id ORD-0004444-01"),
       ("fmi/ORD-0004444-01_v2.xml", <same error>), ("fmi/broken.xml", <its existing error>)}` — assert
     the two conflict rows exactly and that `fmi/broken.xml` is present; no row's error contains
     `duplicate report_id`.
   - no `phi.fmi.report` (or `short_variant`) row for `ORD-0004444-01`.
3. `test_fmi_duplicate_deid(dup_db)`:
   - `information_schema.tables` in catalog `db` has no `duplicate_file` and no `load_error`.
   - `SELECT DISTINCT research_id FROM db.fmi.report` is one value equal to
     `db.caris.report`'s `research_id` (same MRN).
4. `test_fmi_choice_tie_breaks(tmp_path)`: unit test on `choice_key` / `CHOICE` with files written
   in `tmp_path` and parsed by `rows_for`:
   - full vs reduced: full key > reduced key; first differing field index is
     `CHOICE.index("variant_elements")`, also when the full file's mtime is set older
     (`os.utime(path, (t0, t0))` on the full, `t0 + 100` on the reduced) and newer.
   - two reduced copies, one with `<Version>2</Version>`: Version 2 wins, field `version`.
   - two reduced copies, same Version, one with one
     `<Amendmends><Amendmend><ModifiedDts>2026-01-01T00:00:00</ModifiedDts><Type>Addendum</Type><IsSigned>true</IsSigned></Amendmend></Amendmends>`
     inside `FinalReport`: that one wins, field `amendments`.
   - two identical reduced copies with mtimes `t0` and `t0 + 100`: the newer wins, field `mtime`.
   - two identical copies with equal mtime: the lexically larger relative path wins, field `path`.
   (A helper `first_diff(a, b) = next(n for n, x, y in zip(CHOICE, a, b) if x != y)` in the test
   is fine; `load()` computes `reason` the same way and test 2 pins it end to end.)
5. code-r0-1, `FMI_GENES_ONLY`: add
   `<VariantProperty geneName="KMT2C (MLL3)" variantName="R100*" isVUS="true"/>` to its
   `VariantProperties`. Update:
   - `test_fmi_genes_block_short_variants`: the KMT2C row's `is_vus` becomes `True`
     (`("KMT2C", None, "R100*", None, None, None, True)`); still 7 rows.
   - `test_fmi_variant_properties_vus`: add an assert that `gene = 'KMT2C' AND protein_effect =
     'R100*'` on `GENES_ONLY` has `count(*) = 1` and `min(source) = 'genes_block'`; the
     variant_properties set and count 5 are unchanged.
   - `test_fmi_genes_block_tier`: move `("KMT2C", "R100*")` from the `likely_pathogenic` set to
     tier `vus` (`got == want | {("PIK3CA", "H1047R", "vus"), ("KMT2C", "R100*", "vus")}`).
   - `test_fmi_genes_block_not_duplicated`'s alteration count of 14 stays.
6. `test_fmi_vus_lookup_normalizes_names(tmp_path)`: write a file with a FinalReport
   (`ReportId` `ORD-0006666-01`) whose `VariantProperties` are
   `KMT2C (MLL3)` / `R100*` / `isVUS="true"` and `CDKN2A/B` / `p16INK4a A57V` / `isVUS="true"`,
   and a `variant-report` (namespace `NS`) with short variants `KMT2C` `R100*`, `CDKN2A` `A57V`
   and `TP53` `R175H`. `rows_for` gives `{(r[1], r[3], r[14]) for r in t["short_variant"]}` =
   `{("KMT2C", "R100*", True), ("CDKN2A", "A57V", True), ("TP53", "R175H", False)}`, all
   `source = 'variant_report'`.
7. Existing tests pass unchanged otherwise (`test_phi_columns_are_gone_and_ids_are_hashed` still
   sees one `load_error` row for `broken.xml` in the `db` fixture).

Checks: `uv run pytest -q`. Dashboard `npm test` n/a (no dashboard change). Web check n/a.

## Risks

- **Counts move for the duplicated reports.** Their variants now come from the variant report:
  rows gain VAF, depth and position, `genes_block` / `variant_properties` rows for them disappear,
  and tiers come from FMI's `status` instead of the inferred `likely_pathogenic`. That is the
  point. The variant-report path also picks up VUS flags under aliased gene names (Design §2),
  which can move rows from `unclassified` to `vus`. Default cohort counts (pathogenic +
  likely_pathogenic) can change for these reports; real before/after numbers are checked on the
  host and don't go in GitHub.
- **Identity conflict drops a report** that loads today (first file wins). Never seen in the real
  files; if it happens, both files are in `fmi.load_error` and a person decides.
- **mtime is a weak signal.** It is only the fourth tie-break, behind content and FinalReport
  fields, and the findings show it would pick the wrong file if used first.
- **Seam.** `fmi.py` feeds every FMI consumer. For a `ReportId` in a single file the loaded rows
  are unchanged except `is_vus`, which can only go from false to true (Design §2). `research_id`
  and `report_id` cannot change: the hashed id is the shared `ReportId`, and Goal 4 refuses to
  load files whose identity differs.
- **PHI.** `fmi.duplicate_file` holds file names (which embed accession-like ids) and stays in the
  PHI file: it has no `report_id` column, so `deid.build` skips it (test 3 pins this), and the
  leak check would fail the build if a file name ever reached a copied table.
