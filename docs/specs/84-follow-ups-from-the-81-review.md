# Spec #84: follow-ups from the #81 review

Issue #84 has one finding from the #81 review that was not fixed before merge: **code-r0-1**
(minor). `patient_identity` in `src/uccc_genomics/fmi.py` falls back to
`lower(last)|lower(first)|dob` when a report has no MRN, and nothing tests that fallback. The only
identity test (fixture C in `dup_db`, `ORD-0004444-01`) changes just the MRN, so it reads only
`report[7]`. A wrong index for DOB, first name or last name (`report[8]`, `[10]`, `[11]`) would let
two different MRN-less patients merge under one ReportId. A fallback that returns `None` too
often would hide real conflicts. The suite passes in both cases.

This spec adds one unit test. It changes no code and no doc.

All examples are synthetic: they reuse the `FMI` fixture in `tests/test_pipeline.py` (Jane Doe,
DOB `1930-02-03`, MRN `000123456`).

## Goal

Pin `patient_identity`'s three branches with a test that fails if any index or branch is wrong:

1. MRN present (digits): the identity is the MRN digits.
2. No MRN (empty `<MRN></MRN>`, or no digits in it): the identity is
   `lower(LastName)|lower(FirstName)|DOB`.
3. No MRN and any of LastName, FirstName or DOB missing: the identity is `None`.

## Non-goals

- No change to `fmi.py`, `deid.py`, `deid.IDENTITY`, the load, or any SQL. The issue's alternative
  (a fourth `dup_db` pair with an empty MRN and a different LastName, checked in `fmi.load_error`)
  is not added. The unit test is direct, does not run the pipeline subprocess, and covers more
  cases. The `dup_db` fixture C test already pins the load's use of `patient_identity` (any
  disagreement means both files go to `load_error`).
- No test that compares `patient_identity` with `deid.IDENTITY` evaluated in SQL. The review did
  not ask for it. The literal-value assertion below pins the format the docstring promises.
- MRN formatting (dashes, spaces) is not tested here. The digit stripping is unchanged since #81.
- No data change. Nothing touches the de-id file, the mart, the dashboard loader, the cohort API
  or an MCP tool, so no small-cell rule applies. **`research_id` and `report_id` stability is not
  affected.**
- No new dependency. No doc change: ARCHITECTURE, COHORT_DISCOVERY, README, PLAN and COHORT_TOOL
  say nothing that this contradicts.

## Design

One file changes: `tests/test_pipeline.py`. Nothing under `src/uccc_genomics/`, `mcp/`,
`dashboard/`, `web/` or `systemd/` changes.

Add `test_fmi_patient_identity` directly after `test_fmi_choice_tie_breaks`. It uses the
same pattern as that test: write synthetic XML under pytest's `tmp_path`, parse it with
`rows_for`, and pass the report tuple (`rows_for(path)[0]`) to `patient_identity`. It builds
variants of `fmi_report(...)` with `str.replace` on the fixture's PMI elements. It never reads
`$DATA`, `$DATA/raw/` or the PHI file. `rows_for` calls `os.path.relpath(path, RAW)` only to
record a source path; that works for any path and needs no `DATA` override, as in
`test_fmi_choice_tie_breaks`.

```python
def test_fmi_patient_identity(tmp_path):
    from uccc_genomics.fmi import patient_identity, rows_for

    def ident(xml):
        path = tmp_path / "r.xml"
        path.write_text(xml)
        return patient_identity(rows_for(str(path))[0])

    no_mrn = fmi_report("ORD-0007777-01", mrn="")
    names = "<FirstName>Jane</FirstName><LastName>Doe</LastName>"
    dob = "<DOB>1930-02-03</DOB>"
    # Literal value pins the order and the indices of last, first and DOB in the report tuple
    assert ident(no_mrn) == "doe|jane|1930-02-03"
    assert ident(no_mrn.replace(names, "<FirstName>JANE</FirstName><LastName>DOE</LastName>")) == "doe|jane|1930-02-03"
    assert ident(fmi_report("ORD-0007777-01", mrn="N/A")) == "doe|jane|1930-02-03"  # no digits: no MRN
    # Each fallback field separates two MRN-less patients
    for other in (no_mrn.replace("<LastName>Doe<", "<LastName>Roe<"),
                  no_mrn.replace("<FirstName>Jane<", "<FirstName>Joan<"),
                  no_mrn.replace(dob, "<DOB>1931-02-03</DOB>")):
        assert ident(other) not in (None, ident(no_mrn))
    # MRN on one file, absent on the other: different identities
    assert ident(fmi_report("ORD-0007777-01")) == MRN != ident(no_mrn)
    # Any fallback field missing: None
    for missing in (no_mrn.replace(dob, ""), no_mrn.replace("<LastName>Doe</LastName>", ""),
                    no_mrn.replace("<FirstName>Jane</FirstName>", "")):
        assert ident(missing) is None
```

The implementer may reshape lines (wrapping to the file's usual width), but keeps every case
above. Reusing one `r.xml` path is fine: each call writes and parses it before the next.

`fmi_report(rid, mrn="")` yields `<MRN></MRN>`, which `txt` reads as `None`.
`fmi_report(rid, mrn="N/A")` keeps a non-empty MRN with no digits, which `rows_for` turns into
`""`; `patient_identity` treats that as no MRN, as `deid.IDENTITY`'s `nullif(..., '')` does.

Why each case catches the review's failure modes:

| Failure | Caught by |
|---|---|
| Wrong index for last, first or DOB (e.g. `report[12]`, FullName) | literal `"doe|jane|1930-02-03"` |
| First and last swapped | literal value |
| Fallback ignores one field (two patients merge) | the `other` loop (`!=`) |
| Fallback returns `None` too often (conflicts hidden) | `not in (None, ...)` and the literal value |
| No lower-casing | the `JANE`/`DOE` case |
| MRN branch shadowing the fallback, or vice versa | the MRN vs no-MRN case |
| `None` branch dropped (a partial identity like `doe|jane|None`) | the `missing` loop |

I checked the expected values on this branch against the current `rows_for` and
`patient_identity` with synthetic XML only. The fallback gives `doe|jane|1930-02-03`, the
`mrn="N/A"` case gives the same, the MRN case gives `000123456` and a missing DOB gives `None`.
So the test passes on the current code with no source change.

## Acceptance criteria

- [ ] `tests/test_pipeline.py` has `test_fmi_patient_identity`, which uses only synthetic XML in
      `tmp_path` and calls `rows_for` and `patient_identity`.
- [ ] It asserts the no-MRN fallback equals the literal `"doe|jane|1930-02-03"`, both for an
      empty `<MRN>` and for an MRN with no digits.
- [ ] It asserts the fallback is case-insensitive in first and last name.
- [ ] It asserts that changing LastName, FirstName or DOB alone (no MRN) gives a different,
      non-`None` identity.
- [ ] It asserts that an MRN on one file and none on the other give different identities, and
      that the MRN identity is the MRN digits.
- [ ] It asserts `None` when no MRN and DOB, LastName or FirstName is missing.
- [ ] With `report[8]`, `[10]` or `[11]` in `patient_identity` changed to another index, or with
      the fallback reduced to fewer fields, the test fails (checked by hand on a scratch edit
      that is not committed).
- [ ] No file outside `tests/test_pipeline.py` changes (besides this spec).
- [ ] `uv run pytest -q` passes.

## Test plan

- `uv run pytest -q tests/test_pipeline.py -k patient_identity`: the new test passes.
- Mutation check by hand, then revert with `git checkout src/uccc_genomics/fmi.py` (no stash):
  in `patient_identity`, change `report[11]` to `report[12]`, then `report[8]` to `report[9]`,
  then drop `{first.lower()}|` from the f-string. The test fails each time.
- `uv run pytest -q`: whole suite passes.
- Dashboard check (`npm ci && npm test`): n/a, Python-only change.
- Web check (`bun install --frozen-lockfile && bun run typecheck && bun test`): n/a, nothing
  under `web/` or the API models changes.

## Risks

- The `str.replace` targets must match the `FMI` fixture text exactly. If one does not match,
  `replace` does nothing, and the `other` or `missing` case would fail rather than pass silently
  (an unchanged XML gives the same identity, and `!=` and `is None` both fail). So a fixture edit
  breaks the test loudly. It cannot hide a defect.
- If the `FMI` fixture's name or DOB changes, the literal value must change with it.
