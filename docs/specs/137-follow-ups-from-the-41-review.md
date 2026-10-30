# Spec #137: follow-ups from the #41 review

Issue #137 collects the minor and nit findings from the #41 review (the public landing page and
`GET /api/public/summary`) that were not fixed before merge. It also has three comments from the
orchestrator, taken from a screenshot of the signed-out landing page at 1440px:

- **ux-r0-1**: the sparkline's lighter (partial-year) and hatched (`<5`) bars are not explained, and
  the sr-only table does not mark a partial year.
- **ux-r0-2** + comment 1: the Vendors cell renders at the 28px bold number size and wraps over
  several lines.
- **ux-r0-3**: on the landing page `Count` titles a null with the Discover text
  `SUPPRESSED` ("Fewer than 5 patients, or hidden so that a small count cannot be worked out by
  subtraction"). The unit is wrong for reports and tumor types, and the subtraction clause does not
  apply to this fixed endpoint.
- **ux-r0-4**: the label "Collection years" claims more than the value, which is the first and last
  year of first sample with at least 5 patients.
- **code-r1-1**: the #41 spec's test plan for `test_public_summary_values` describes the old method.
- Comment 2: the access copy says "To get access, ask the UCCC genomics team", but campus sign-in
  admits any CU Anschutz Google account (then the portal terms, #131).
- Comment 3: collection years include the date-shift spillover year (one past the current year).
  The range and the sparkline should stop at the current year, with spillover folded into it.

## Goal

1. `public._compute()` folds every year after the current calendar year into the current year
   before counting, so `first_year`, `last_year` and `by_year` never pass the current year. The
   patients from spillover years count toward the current year's bar.
2. The landing page explains both bar styles in its hint, marks partial years in the sr-only table,
   renders Vendors at body size, titles its `<5` cells without the Discover subtraction text, labels
   the year range "First-sample years" and gives the corrected access copy.
3. The #41 spec's test plan and acceptance wording for `test_public_summary_values` describe what
   the test actually does.

## Non-goals

- **Discover's accrual** (the start-page sparkline and the Accrual tab, fed by
  `cohort/compile.py` `by_year`) keeps showing spillover years. It is a signed-in page with its
  own suppression, its spillover handling is documented in `dashboard/COHORT_DISCOVERY.md`
  ("Partial years (the current year and date-shift spillover) are shaded and marked "*""), and
  the accrual rate is computed over those years. Changing it is a separate issue.
- No change to `PublicSummary`'s fields or types, so no change to `web/openapi.json`,
  `web/src/api.gen.ts` or `web/src/types.ts`. Only the field comments for `first_year` /
  `last_year` / `by_year` change.
- No change to `coarse`, `MIN_CELL`, `PUBLIC_ROUND`, the outlier rule (`big`), the vendor or
  tumor-type queries, the caching, the route or its open-route status.
- No change to `deid.py`, `sql/*.sql` or the mart. `year` and `year_complete` in `mart.report` are
  as before. **`research_id` and `report_id` are not touched.**
- No change to `Sparkline` in `Start.tsx` (the landing page passes it already-capped years).
- The refusal page text in `authen.py` ("ask the UCCC genomics team") stays: it is shown to someone
  outside the group, for whom asking is the right advice.
- No new dependencies.

## Design

### 1. `mcp/src/uccc_genomics_mcp/public.py`: fold spillover into the current year

Add `from datetime import date` and bind the current year as a SQL parameter in the `years` query.
Both CTEs cap the year with `least(…, $this_year)`:

```python
        # first-sample year per patient, as Discover's accrual (compile.py `pp`); complete as compile.py's
        # year_complete row. Years after this one (date-shift spillover, up to 182 days) fold into this year.
        years = con.execute(
            "WITH pp AS (SELECT research_id, least(min(year), $this_year) AS yr FROM mart.report "
            "WHERE year IS NOT NULL GROUP BY 1), "
            "c AS (SELECT least(year, $this_year) AS year, bool_and(year_complete) AS complete FROM mart.report "
            "WHERE year IS NOT NULL GROUP BY 1) "
            "SELECT pp.yr, count(*), c.complete FROM pp JOIN c ON c.year = pp.yr GROUP BY 1, 3 ORDER BY 1",
            {"this_year": date.today().year}).fetchall()
```

- The fold happens before `coarse()` and before the `big` (≥ `MIN_CELL`) filter, so a spillover
  year with 1–4 patients adds to the current year instead of being dropped as an outlier, and the
  rounding is applied once to the folded count (never to a sum of rounded counts).
- `complete` for the current year is `bool_and` over the current year and the spillover years. Both
  are incomplete by construction (`unified.sql`: `make_date(year(collected_on), 12, 31) + 182 <
  current_date`), so the current year stays `complete: false`.
- `this_year` is a Python `int` bound as a named parameter, like `$min_cell`. No request input
  reaches it.
- Field comments in `PublicSummary`:
  `first_year: int | None    # first / last year in by_year; never after the current year`
  and `by_year: list[YearCount]  # patients by year of their first sample, first_year..last_year;
  later (date-shifted) years fold into the current year`.
- The module docstring gains one sentence: "Years after the current one (date-shift spillover)
  count as the current year."

Small-cell rule: unchanged. Every count still goes through `coarse()` (null under 5, else rounded
to the nearest 10). The fold only merges cells. It never splits one, so it cannot produce a count
under 5 where there was none before.

### 2. `web/src/Answer.tsx`: optional title on `Count`

```tsx
export function Count({n, minCell, title = SUPPRESSED}: {n: number | null | undefined; minCell: number; title?: string}) {
  if (n == null) return <span className="suppressed" title={title}>{`<${minCell}`}</span>;
  return <>{fmtCount(n)}</>;
}
```

Every existing call site leaves `title` out, so Discover's output does not change.

### 3. `web/src/Landing.tsx`

- **Access copy** (comment 2). Replace the third paragraph with:

  ```tsx
  <p>Discover is for University of Colorado researchers and staff. Sign in with your CU Anschutz
    Google account. Researchers without a CU Anschutz account can ask the UCCC genomics team for access.</p>
  ```

- **Titles** (ux-r0-3). Inside `Landing`, after `const s = summary;`, derive both titles from the
  response's `min_cell`:

  ```tsx
  const few = s ? `Fewer than ${s.min_cell}` : "";   // the landing page's <5 title: no subtraction on this fixed endpoint
  ```

  Pass `title={`${few} patients`}` to the Patients `Count` and to each sr-only table `Count`, and
  `title={few}` to the Reports and Tumor types `Count`s.
- **Vendors** (ux-r0-2). The vendors cell becomes `<div className="text">`.
- **Year label** (ux-r0-4). `<dt>Collection years</dt>` becomes `<dt>First-sample years</dt>`. The
  `first_year === last_year` single-year logic stays.
- **sr-only table** (ux-r0-1). The year cell becomes
  `<td>{y.year}{!y.complete && " (partial year)"}</td>`.
- **Hint** (ux-r0-1). Add the bar sentence after the rounding sentence:

  ```tsx
  <p className="hint">Counts are rounded to the nearest {s.round_to}; fewer than {s.min_cell} shows as
    &lt;{s.min_cell}. A lighter bar is a year not yet complete; a hatched bar is fewer
    than {s.min_cell}. A patient sequenced by both vendors counts once. Years are approximate: dates
    are shifted per patient for de-identification.</p>
  ```

  The "Years are approximate" sentence stays as it is (comment 3).

### 4. `web/src/styles.css`

After the `.totals dd` rule (line 231), add:

```css
.totals .text dd { font-size: var(--fs-md); line-height: var(--lh-md); font-weight: 600; }
```

Body size, not a full-row span: a span would leave the year cell alone on the next row at desktop
width. Both tokens already exist in `:root`, so `styles.test.ts` ("every token used is defined")
still passes.

### 5. Docs

- `docs/specs/41-public-landing-page-at-with-coarse.md` (code-r1-1):
  - Test plan, the `test_public_summary_values` bullet: replace "Compare against `coarse()` of
    plain SQL and the rules above." with "The test patches `coarse` to the identity and asserts the
    raw literal counts first, so a broken `OTHER`/NULL/`HAVING` filter fails before rounding can
    hide it, then restores `coarse` and checks the rounded values."
  - Acceptance criteria: replace "The values match hand-computed `coarse()` of plain SQL on the
    synthetic mart." with "The unrounded values (with `coarse` patched to the identity) match
    literal counts of the synthetic mart, and the rounded values match `coarse()` of those."
- `README.md`, the `GET /api/public/summary` paragraph (line 312): after "…(a year in that range
  with fewer shows null)" add "; years after the current one (date-shift spillover) count as the
  current year".
- `dashboard/COHORT_DISCOVERY.md` and `docs/ARCHITECTURE.md` describe neither the landing copy nor
  the public year range in this detail and need no change.

## Acceptance criteria

- [ ] `public.summary()` on a synthetic mart with years `Y-2`, `Y-1`, `Y` and `Y+1`
      (`Y = date.today().year`) returns no year after `Y` in `by_year` or `last_year`, and the
      unrounded `Y` count is the patients whose first sample is in `Y` plus those whose first
      sample is in `Y+1`.
- [ ] A 1–4-patient spillover year is folded, not dropped as an outlier, and the fold happens
      before the ≥ 5 filter: 3 patients only in `Y`, 3 only in `Y+1` and 1 with reports in both
      give `Y` 7 unrounded (10 rounded), where today `Y` (4) and `Y+1` (3) would both be cut.
- [ ] A patient with reports in both `Y` and `Y+1` counts once, in `Y`.
- [ ] `by_year` for `Y` has `complete: false`.
- [ ] The existing `test_public_summary_values` assertions (years 2022–2024) still pass unchanged.
- [ ] Every count in the response is still null or a multiple of 10 that is at least 10
      (`test_public_summary_counts_are_coarse` unchanged and passing).
- [ ] Web: the landing page renders "Sign in with your CU Anschutz Google account." and "Others can
      ask the UCCC genomics team for access.", and no longer renders "To get access, ask the UCCC
      genomics team".
- [ ] Web: the hint contains "A lighter bar is a year not yet complete; a hatched bar is fewer
      than 5." and still contains "Years are approximate".
- [ ] Web: the sr-only table marks the incomplete year (`2018 (partial year)` in the synthetic
      summary) and does not mark complete years (`2016` without the suffix).
- [ ] Web: the label is "First-sample years", and "Collection years" is gone.
- [ ] Web: the vendors cell is `<div class="text">`. `styles.css` has a `.totals .text dd` rule with
      `font-size: var(--fs-md)`.
- [ ] Web: a null Tumor types count renders `title="Fewer than 5"`, a null by-year count in the
      sr-only table renders `title="Fewer than 5 patients"`, and the landing HTML does not contain
      the `SUPPRESSED` text ("worked out by subtraction").
- [ ] Web: `Count` without `title` still renders `title={SUPPRESSED}` (existing Discover tests in
      `answer.test.tsx` pass unchanged).
- [ ] The #41 spec's test-plan bullet and acceptance line read as in Design §5; README updated.
- [ ] `uv run pytest -q`, `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`
      pass. Dashboard check: n/a (nothing under `dashboard/` changes).

## Test plan

Everything runs on synthetic data in temp dirs. No test reads `$DATA/raw`, the PHI file or the
real de-id file.

**`tests/test_app.py`**

- `test_public_summary_folds_spillover_year(tmp_path, monkeypatch)`: build a `Mart` with the same
  `add()` helper as `test_public_summary_values`, using years relative to
  `Y = date.today().year`: 10 patients in `Y-1` (complete), 3 in `Y` (incomplete), 3 in `Y+1`
  (incomplete), and one patient with a report in `Y` and another in `Y+1` (both incomplete, so
  their first sample is `Y`). Add one `m.mutation(...)` so `write_mart` has a fact row. Patch
  `public.get_db`, `public.DEID_DB` and `public._summary` as `test_public_summary_values` does.
  - With `coarse` patched to the identity: `by_year` is `[(Y-1, 10, True), (Y, 7, False)]`,
    `last_year == Y`.
  - With `coarse` restored and `_summary` reset: `by_year` is `[(Y-1, 10, True), (Y, 10, False)]`,
    `last_year == Y`, and no `y.year > Y`.

  Relative years keep the test valid in any calendar year without patching `date`.

**`web/src/landing.test.tsx`** (the existing `SUMMARY` fixture already has a null `tumor_types`, a
null 2017 count and an incomplete 2018)

- Update `"a single year and no year"`: assert `"First-sample years"` is absent when there are no
  years (replacing the `"Collection years"` assertion).
- `"access copy names campus Google sign-in"`: contains "Sign in with your CU Anschutz Google
  account." and "Researchers without a CU Anschutz account can ask the UCCC genomics team for access."; does not contain "To get
  access".
- `"the hint explains partial and hatched bars"`: contains "A lighter bar is a year not yet
  complete; a hatched bar is fewer than 5." and "Years are approximate".
- `"the sr-only table marks partial years"`: contains `<td>2018 (partial year)</td>` and
  `<td>2016</td>`.
- `"year label and vendors cell"`: contains `<dt>First-sample years</dt>` and
  `<div class="text"><dt>Vendors</dt>`; does not contain "Collection years".
- `"landing <5 titles"`: matches `/Tumor types<\/dt><dd><span class="suppressed" title="Fewer than 5">/`,
  contains `title="Fewer than 5 patients"`, and does not contain "subtraction".

**`web/src/answer.test.tsx`**

- `"Count takes an optional title"` (add `Count` and `SUPPRESSED` to the `./Answer.tsx` import):
  `renderToStaticMarkup(<Count n={null} minCell={5} title="x" />)`
  contains `title="x"`; without `title` it contains `title="${SUPPRESSED}"` (the HTML-escaped form
  React emits, or check with `toContain("worked out by subtraction")`).

**`web/src/styles.test.ts`**

- `".totals .text dd is body size"`: `rule(".totals .text dd")` contains `var(--fs-md)`.

## Risks

- **New Year without a rebuild.** The summary is cached per de-id file mtime. If the daily rebuild
  did not run across 31 December, the cap stays at the old year until the next rebuild (the
  spillover year shows for that gap). The daily timer makes this a one-day window at most, which is
  acceptable.
- **Landing and Discover disagree on the last year.** After this change the landing page stops at
  the current year while Discover's accrual still shows the spillover year as a partial year. That
  is deliberate (Non-goals) and both say years are approximate.
- **The current-year bar grows.** The folded count includes patients whose shifted first sample is
  next year. The bar is already marked partial, and "Years are approximate" covers it.
- **Copy accuracy.** "Sign in with your CU Anschutz Google account" assumes the production Authentik
  flow uses campus Google sign-in and admits `@cuanschutz.edu` accounts into the group, as the
  orchestrator's comment says. If group membership becomes manual, this sentence and the
  "Others can ask" sentence need revisiting.
