# Spec #92: follow-ups from the #89 review

Issue #92 lists six minor/nit findings from the #89 review. Two were already fixed in #89's later
review rounds; the other four are a comment, a test comment and two doc sentences. This spec
changes no behaviour.

All examples are synthetic: they reuse the `FMI` fixture in `tests/test_pipeline.py` (Jane Doe,
DOB `1930-02-03`, MRN `000123456`). No real values or counts appear here.

## Status of each finding (checked against `origin/main` at e32a73c)

| Finding | Where | Status | Action |
|---|---|---|---|
| code-r0-4 | `fmi.patient_identity` | Partly fixed: `same_patient` now calls it for the no-identity case, so it is live. The misleading test comment remains. | Reword one comment in `test_fmi_patient_identity`. |
| security-r0-2 | `fmi.same_patient` | Fixed: the last line is `return patient_identity(a) is None and patient_identity(b) is None`, equivalent to the issue's `not any((a[7], na, b[7], nb))`. Spec #89 Goal 4 states it, and `dup_mixed_db` pair H (`ORD-0009999-01`, no MRN and no DOB on either copy) pins it in `test_fmi_duplicate_mixed_identity`. | None. |
| code-r2-1 | `README.md` de-id section | Open. | Replace the sentence (below). |
| code-r0-5 | `fmi.rows_for` MRN comment | Open: the parenthetical sits between "carry it" and what "there" refers to. | Replace the comment (below). |
| security-r0-3 | `docs/specs/89-...md`, History | Mostly fixed: the count is gone; "a real duplicate pair had" still reads as one observed instance. | Reword (below). |
| code-r1-2 | `docs/specs/89-...md`, Risks › Seam | Open: "(test 4)" points at the `dup_mixed_db` test. | Change to "(tests 2 and 5)". |

## Goal

1. The `rows_for` MRN comment reads as one clear sentence about where the MRN comes from.
2. `test_fmi_patient_identity` no longer implies that an MRN-only copy and an MRN-less copy of
   one `ReportId` are different patients (`load()` decides that with `same_patient`).
3. The README states the duplicate-copy rule as `same_patient` implements it.
4. Spec #89 has no observed-instance wording about real files and no wrong test reference.

## Non-goals

- No code change beyond one comment in `src/uccc_genomics/fmi.py`. `patient_identity` stays:
  `same_patient` uses it, and `test_fmi_patient_identity` / `test_fmi_mrn_fallback` pin the
  `deid.IDENTITY` format its docstring promises. The issue's other option (remove it and move its
  assertions) is not taken, because the function is live again.
- No new test. security-r0-2 asked for "a test either way"; pair H in `dup_mixed_db` is that
  test, added in #89 round 1.
- No change to `deid.py`, `deid.IDENTITY`, any SQL, the de-id file, the mart, the dashboard
  loader, the cohort API or an MCP tool, so no small-cell rule applies. **`research_id` and
  `report_id` stability is not affected.**
- No new dependency. ARCHITECTURE, COHORT_DISCOVERY, PLAN and COHORT_TOOL say nothing about this;
  only README changes, and it changes to match the code.

## Design

Four files change. Nothing under `mcp/`, `dashboard/`, `web/` or `systemd/` changes.

### `src/uccc_genomics/fmi.py` (code-r0-5)

In `rows_for`, replace the three comment lines above
`pmi_mrn, ci_mrn = mrn_digits(...)` with:

```python
    # PMI MRN, else ResultsReport/CustomerInformation/MRN (namespaced rr: in real files, hence {*}):
    # Monitor files have no PMI but carry it there, and some reports leave the PMI copy empty (#89).
    # CustomerInformation has no name/DOB/dates.
```

Only the comment changes; the code lines below it are untouched.

### `tests/test_pipeline.py` (code-r0-4)

In `test_fmi_patient_identity`, replace the comment

```python
    # MRN on one file, absent on the other: different identities
```

with

```python
    # MRN on one file, absent on the other: the identities differ in kind. load() compares copies
    # with same_patient, which can still pair them (test_fmi_duplicate_mixed_identity).
```

The assertion under it is unchanged.

### `README.md` (code-r2-1)

In the de-identification bullet list, replace the two sentences that start "When two copies of one
FMI report differ only in which identity fields they carry" and end
"(`mrn_source = 'duplicate_copy'`)." with:

```markdown
  Two copies of one FMI report are compared pairwise. When both carry an MRN, it decides. Otherwise
  they are one patient when both carry last|first|dob and it agrees, or when neither carries any
  identity; any other pair sends every copy to `fmi.load_error`. If the chosen copy has no MRN, it
  takes it from a twin (`mrn_source = 'duplicate_copy'`).
```

This is the issue's text with two corrections against the code: the donor step runs only when the
chosen copy has no MRN (`if report[7] is None` in `load()`), and a failing pair sends all copies to
`load_error`. Keep the two-space bullet-continuation indent of the surrounding lines.

### `docs/specs/89-fmi-mrn-fallback-read-resultsreport.md` (security-r0-3, code-r1-2)

- Risks › Seam: "`mrn_source` is dropped (test 4)" → "`mrn_source` is dropped (tests 2 and 5)".
  Test 2 checks `information_schema.columns` for `mrn_source` in `db` and `phi`; test 5 is
  `test_phi_columns_are_gone_and_ids_are_hashed`.
- History: "(a real duplicate pair had the MRN only in the reduced copy's `CustomerInformation`)" →
  "(a real duplicate pair can have the MRN only in the reduced copy's `CustomerInformation` and
  only name and DOB in the full copy)".

## Acceptance criteria

- [ ] `fmi.py` `rows_for` carries the comment above verbatim; `git diff` on `fmi.py` touches only
      comment lines.
- [ ] `test_fmi_patient_identity` carries the new comment; its assertions are unchanged.
- [ ] `README.md` no longer contains "every field both carry" and contains "When both carry an
      MRN, it decides".
- [ ] Spec #89 contains no "(test 4)" and no "a real duplicate pair had".
- [ ] `patient_identity` and `same_patient` code is unchanged (`git diff` shows no non-comment
      change in `src/`).
- [ ] `uv run pytest -q` passes.

## Test plan

- `uv run pytest -q`: no test changes behaviour; the existing `test_fmi_patient_identity`,
  `test_fmi_mrn_fallback`, `test_fmi_duplicate_mixed_identity` (pair H pins security-r0-2) and
  the `dup_db` tests must still pass. They build synthetic FMI XML under temp `DATA` dirs and never
  read `$DATA/raw/` or the PHI file.
- `git diff origin/main -- src` shows only comment lines.
- Dashboard check: n/a (no dashboard change). Web check: n/a (nothing under `web/` or the API
  models).

## Risks

- None to data or ids: comments and docs only. The one risk is a README sentence drifting from
  `same_patient` again; it now mirrors the docstring's branches one to one.
