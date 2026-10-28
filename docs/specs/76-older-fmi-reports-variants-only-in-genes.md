# Spec #76: older FMI reports with variants only in the Genes block

Some FMI reports, mostly older ones, have an empty `<short-variants/>` (or no `variant-report`
results at all), but their curated `FinalReport/Genes/Gene/Alterations/Alteration` block lists
the variants. `fmi.py` loads that block into `fmi.alteration` and nothing else, so these reports
contribute no rows to `fmi.short_variant`, `fmi.cna`, `unified.variant`, `unified.cna`,
`mart.fact` or the cohort tool.

All examples below are synthetic. Facts about the real files are structural only (no counts).

## Findings (checked 2026-10-27)

From the de-identified file, read-only:

- Every report that has `fmi.alteration` rows but no `fmi.short_variant` rows also has no
  `fmi.cna`, `fmi.rearrangement` or `fmi.biomarker` rows. The whole `variant-report` result set
  is empty on these reports, not just `<short-variants>`. So copy-number calls in their Genes
  block are missing from `fmi.cna` as well.
- On reports that have both blocks, `Alteration/Name` uses the same strings as
  `short-variant/@protein-effect`: `R175H`, `Q61*`, `P72fs*9`, `A100_L104del`,
  `splice site 560-1G>C`, `promoter -124C>T`. For splice and promoter names the existing
  `cds-effect` is the name without the `splice site ` / `promoter ` prefix.
- Several changes in one gene are joined with `", "` (`E545K, E726K`), and one name can mix
  kinds (`G95fs*1, rearrangement exon 20`).
- `Gene/Name` can carry an alias in parentheses (`KMT2C (MLL3)`, `NSD2 (WHSC1 or MMSET)`). The
  part before ` (` matches `short-variant/@gene` on newer reports.
- CDKN2A appears under `Gene/Name` `CDKN2A/B` as `p16INK4a R58* and p14ARF P72L` or
  `p16INK4a S12*`. The matching `short-variant` row is gene `CDKN2A`, protein-effect = the
  p16INK4a change (`R58*`). Copy-number loss appears as `CDKN2A loss` / `CDKN2B loss`, or as a bare
  `loss` (both genes, ambiguous).
- Copy-number names are `amplification`, `loss` and `loss exon(s) N[-M]`. On dual-block reports
  these match `fmi.cna` rows (types `amplification` / `loss`). `deletion exons N-M`,
  `duplication exons`, `truncation exon N`, `rearrangement intron/exon N` and `X-Y fusion` match
  `fmi.rearrangement` instead.
- Biomarker pseudo-genes (`Tumor Mutation Burden`, `Blood Tumor Mutational Burden`,
  `Microsatellite status`, `HRD signature`, `Tumor Fraction`, `ctDNA Tumor Fraction`) carry calls
  or scores as names (`TMB-Low`, `MS-Stable`, `HRDsig Negative`, two-digit scores). `wildtype`
  also appears. None of these are variants.
- **Significance (inference):** on dual-block reports, every `fmi.short_variant` row whose
  gene + protein_effect is also listed in the Genes block has status `known` or `likely` and
  `is_vus = false`. None are `unknown`, none are VUS. The Genes block is FMI's list of reported
  alterations, but it doesn't say which of known/likely a given entry is.

From the real XML (supervisor, aggregates only, verified 2026-10-27):

- `AlterationProperty/@dnaFraction` is on a **percent scale** (0–100), not a fraction. Small
  percents below 1 occur, so a range test can't tell the scale apart. It is often missing or
  empty (copy-number and biomarker properties lack it).
- When `Alteration/Name` joins several changes, there is **one `AlterationProperty` per part**
  and its `@name` equals the part.

The legacy `foundation-medicine-xml-parser` reads only `short-variant` elements in the same
namespace, so it never derived these rows either. The legacy-file rows the issue mentions came
from somewhere else. This spec uses the Genes block as the source.

## Goal

1. For a report with **no** `<short-variant>` element, derive `fmi.short_variant` rows from its
   Genes block: one per short-variant part of each `Alteration/Name`.
2. For a report with **no** `<copy-number-alteration>` element, derive `fmi.cna` rows from its
   Genes block for amplification and loss parts.
3. Mark every row in both tables with a provenance column `source`: `'variant_report'` for rows
   from the `variant-report` elements (all rows today), `'genes_block'` for derived rows.
4. Carry `source` into `unified.variant` and `unified.cna`. In `unified.variant`, give derived
   rows that aren't VUS the tier `likely_pathogenic` (see Design §3; an inference, flagged for
   Sean to confirm).
5. Synthetic-XML tests that pin the parsing, the no-duplication rule, the tier mapping and the
   mart facts.
6. README Known gaps lists what is still not derived.

## Non-goals

- No derived `fmi.rearrangement` or `fmi.biomarker` rows. Rearrangement, truncation, deletion,
  duplication and fusion names have no reliable partner gene or breakpoints. Biomarker calls are
  left out per the issue comment. Both are listed in README Known gaps.
- No derived rows for a report that has the matching elements. A report with any
  `<short-variant>` gets no `genes_block` short variants, and a report with any
  `<copy-number-alteration>` gets no `genes_block` CNA rows. Nothing is ever duplicated or merged.
- No CNA row for an ambiguous `loss` under a multi-gene `Gene/Name` (`CDKN2A/B`), and none for
  `p16INK4a loss and p14ARF loss exons 1-2`. These go in Known gaps.
- No invented vendor status. `fmi.short_variant.status` stays NULL on derived rows. The tier
  inference lives only in `unified.variant`.
- No change to `fmi.alteration` (it keeps one row per `Alteration`, unsplit) or to `therapy` /
  `trial`.
- No change to `deid.py`, the PHI column lists, id hashing, date shifting or the leak assert.
  `research_id` and `report_id` are unaffected: no key or identity code changes, and the new
  rows hang off existing `report_id`s. The new `source` column is a constant label, not PHI,
  and the existing leak scan covers it like any other VARCHAR.
- No new output path. Derived rows reach the dashboard loader (`MIN_CELL = 5`), the cohort API
  and MCP only through `unified.*` / `mart.fact`, which already apply their small-cell rules.
  No suppression code changes.
- No column change to `mart.fact` or `mart.report`. Their pinned columns stay as they are
  (`test_mart_tables_are_tables_with_pinned_columns`).
- No gene-symbol harmonisation. Older `short-variant` rows keep old symbols (`MLL3`), while
  derived rows take the current symbol before ` (` (`KMT2C`). That mismatch is already there
  between old and new reports; see Risks.
- No new dependency (stdlib `re`).
- Re-running the IRB delivery and comparing it is a follow-up for the orchestrator after the
  daily rebuild, not part of this change.

## Design

### 1. `src/uccc_genomics/fmi.py`

**Imports:** add `import re`.

**DDL:** append `source VARCHAR` as the **last** column of `short_variant` (after `is_vus`)
and of `cna` (after `equivocal`). `bulk_insert` is positional, so every row tuple for these two
tables gains a final element.

**Module-level patterns and two pure functions** (after `b()`):

```python
# Genes-block Alteration/Name parts that are short variants or copy-number calls (#76).
SYMBOL = re.compile(r"[A-Z0-9][A-Za-z0-9-]*")              # a gene symbol, not "Tumor Mutation Burden"
PROTEIN = re.compile(r"[A-Z*][0-9]+\S*")                    # R175H, Q61*, P72fs*9, A100_L104del
CDS_PREFIXED = re.compile(r"(?:splice site|promoter) (\S+)")  # splice site 560-1G>C, promoter -124C>T
P16 = re.compile(r"p16INK4a ([A-Z*][0-9]+\S*)(?: and p14ARF \S+)?")
CNA_NAME = re.compile(r"(amplification|loss)(?: exons? [0-9]+(?:-[0-9]+)?)?")
GENE_LOSS = re.compile(r"([A-Z0-9][A-Za-z0-9-]*) loss")      # "CDKN2B loss" under Gene/Name "CDKN2A/B"


def genes_block_short_variant(gene, part):
    """(gene, cds_effect, protein_effect) for one ", "-separated part of a Genes-block
    Alteration/Name that is a short variant, else None. `gene` is Gene/Name ("KMT2C (MLL3)")."""
    gene = gene.split(" (")[0] if gene else None
    if m := P16.fullmatch(part):
        return ("CDKN2A", None, m[1]) if gene in ("CDKN2A", "CDKN2A/B") else None
    if not (gene and SYMBOL.fullmatch(gene)):
        return None
    if m := CDS_PREFIXED.fullmatch(part):
        return gene, m[1], part
    return (gene, None, part) if PROTEIN.fullmatch(part) else None


def genes_block_cna(gene, part):
    """(gene, type), type 'amplification' or 'loss', for a copy-number part of a Genes-block
    Alteration/Name, else None."""
    gene = gene.split(" (")[0] if gene else None
    if m := GENE_LOSS.fullmatch(part):
        return m[1], "loss"
    if gene and SYMBOL.fullmatch(gene) and (m := CNA_NAME.fullmatch(part)):
        return gene, m[1]
    return None
```

Behaviour these must have (pinned by the unit test, §Test plan):

| `Gene/Name` | part | `genes_block_short_variant` | `genes_block_cna` |
|---|---|---|---|
| `TP53` | `R175H` | `("TP53", None, "R175H")` | None |
| `APC` | `P72fs*9` | `("APC", None, "P72fs*9")` | None |
| `KMT2C (MLL3)` | `R100*` | `("KMT2C", None, "R100*")` | None |
| `RB1` | `splice site 2107-2A>G` | `("RB1", "2107-2A>G", "splice site 2107-2A>G")` | None |
| `TERT` | `promoter -124C>T` | `("TERT", "-124C>T", "promoter -124C>T")` | None |
| `CDKN2A/B` | `p16INK4a R58* and p14ARF P72L` | `("CDKN2A", None, "R58*")` | None |
| `CDKN2A/B` | `CDKN2B loss` | None | `("CDKN2B", "loss")` |
| `CDKN2A/B` | `loss` | None | None |
| `CDKN2A/B` | `p16INK4a loss and p14ARF loss exons 1-2` | None | None |
| `ERBB2` | `amplification` | None | `("ERBB2", "amplification")` |
| `PTEN` | `loss exons 6-9` | None | `("PTEN", "loss")` |
| `STK11` | `loss exon 2` | None | `("STK11", "loss")` |
| `LRP1B` | `deletion exons 15-25` | None | None |
| `WT1` | `rearrangement intron 1` | None | None |
| `TMPRSS2` | `TMPRSS2-ERG fusion` | None | None |
| `KRAS` | `wildtype` | None | None |
| `Tumor Mutation Burden` | `TMB-Low` | None | None |
| `Tumor Mutation Burden` | `01` | None | None |
| `Microsatellite status` | `MS-Stable` | None | None |
| `HRD signature` | `HRDsig Negative` | None | None |
| None | `R175H` | None | None |

**`rows_for(path)`:**

1. Before the `if fr is not None:` block, compute once:
   ```python
   has_sv = vr is not None and vr.find(f".//{NS}short-variant") is not None
   has_cna = vr is not None and vr.find(f".//{NS}copy-number-alteration") is not None
   ```
2. Inside the existing `for al in g.findall("Alterations/Alteration"):` loop, after the
   `t["alteration"]` append and the therapy loop, add:
   ```python
                # Older reports list their variants only here, with no <short-variant> or
                # <copy-number-alteration> elements: derive rows for those reports only (#76).
                # dnaFraction is a percent; each ", "-joined part has its own AlterationProperty.
                for part in (name or "").split(", "):
                    p = props.get(part)
                    eq = b(p.get("isEquivocal")) if p is not None else None
                    if not has_sv and (sv := genes_block_short_variant(gene, part)):
                        sg, cds, prot = sv
                        af = f(p.get("dnaFraction")) if p is not None else None
                        t["short_variant"].append((rid, sg, cds, prot, None, None, None,
                                                   None if af is None else af / 100, None, None, None, None,
                                                   eq, b(p.get("isSubclonal")) if p is not None else None,
                                                   (sg, prot) in vus or (sg, cds) in vus, "genes_block"))
                    elif not has_cna and (cn := genes_block_cna(gene, part)):
                        t["cna"].append((rid, *cn, None, None, None, None, None, eq, "genes_block"))
   ```
   Column order is the DDL's: short_variant `report_id, gene, cds_effect, protein_effect,
   position, transcript, strand, allele_fraction, depth, percent_reads, status,
   functional_effect, equivocal, subclonal, is_vus, source`; cna `report_id, gene, type,
   copy_number, ratio, number_of_exons, position, status, equivocal, source`. `vus` is never None
   here because this loop runs only when a FinalReport exists.
   - The property is looked up only by `props.get(part)`. There is **no** fallback to the first
     property (unlike `fmi.alteration`), so a part without its own property gets NULL
     `allele_fraction` / `equivocal` / `subclonal`.
   - `allele_fraction = dnaFraction / 100` always; NULL when the attribute is missing, empty or
     not numeric (`f()` already returns None for those).
3. The existing `short-variant` and `copy-number-alteration` appends gain a final
   `"variant_report"` element.

`load()` is unchanged (it already prints row counts per table).

### 2. Vendor source fields (PLAN.md mapping, extended)

| column | source for `genes_block` rows |
|---|---|
| `fmi.short_variant.gene` | `Gene/Name` before ` (`; `CDKN2A` for `p16INK4a …` names |
| `fmi.short_variant.protein_effect` | one `", "` part of `Alteration/Name` (the p16INK4a change for CDKN2A) |
| `fmi.short_variant.cds_effect` | the part after `splice site ` / `promoter `; NULL for protein changes |
| `fmi.short_variant.allele_fraction` | `AlterationProperty[@name = part]/@dnaFraction` / 100 |
| `fmi.short_variant.equivocal` / `subclonal` | `AlterationProperty[@name = part]/@isEquivocal` / `@isSubclonal` |
| `fmi.short_variant.is_vus` | `VariantProperties/VariantProperty/@isVUS` keyed by (gene, protein_effect or cds_effect), as today |
| `fmi.short_variant.position, transcript, strand, depth, percent_reads, status, functional_effect` | NULL (not in the Genes block) |
| `fmi.cna.gene` | `Gene/Name` before ` (`, or the symbol in `<SYMBOL> loss` |
| `fmi.cna.type` | `amplification` or `loss` from `Alteration/Name` |
| `fmi.cna.equivocal` | `AlterationProperty[@name = part]/@isEquivocal` |
| `fmi.cna.copy_number, ratio, number_of_exons, position, status` | NULL |
| `source` (both tables) | `'variant_report'` from `variant-report` elements; `'genes_block'` derived |

### 3. `src/uccc_genomics/sql/unified.sql`

`unified.variant`, FMI arm: add `v.source` to the select list, and one branch to the tier
`CASE`, after the `likely` branch and before `ELSE`:

```sql
       CASE WHEN v.is_vus THEN 'vus'
            WHEN lower(v.status) = 'known' THEN 'pathogenic'
            WHEN lower(v.status) = 'likely' THEN 'likely_pathogenic'
            -- Genes-block rows (#76) have no vendor status. On reports with both blocks every
            -- Genes-block short variant is known or likely, so they take the lower of the two.
            -- An inference, not a vendor call: docs/specs/76-older-fmi-reports-variants-only-in-genes.md.
            WHEN v.source = 'genes_block' THEN 'likely_pathogenic'
            ELSE 'unclassified' END AS tier
```

The VUS branch comes first, so a derived row with `is_vus = true` stays `vus`. A NULL `is_vus`
falls through to `likely_pathogenic`, which is the same as `NOT coalesce(is_vus, false)`. The
Caris arm adds `NULL::VARCHAR AS source`. Caris has no Genes-block concept, and the explicit
NULL matches how `is_subclonal` is written there.

`unified.cna`, FMI arm: add `c.source`; Caris arm: `NULL::VARCHAR AS source`.

Update the comment above `unified.variant` (`Vendor value -> tier mapping: docs/specs/32-…`)
to name this spec too.

`mart.sql` needs no change: the `alteration` arms read `unified.variant` / `unified.cna` and
pick up the new rows, `tier` included. `mart.fact` doesn't carry `source`. Provenance is
auditable in `unified.*` and `fmi.*`, which join back on `report_id`.

### 4. Docs (same PR)

- `README.md` Schemas: in `fmi.*`, write `short_variant` and `cna` as having `source`
  (`variant_report`, or `genes_block` for rows derived from the curated Genes block on reports
  without those elements, #76). In `unified.*`, add one sentence: `variant.source` /
  `cna.source` carry it (NULL for Caris), and FMI `genes_block` short variants have tier
  `likely_pathogenic` unless VUS (an inference).
- `README.md` Known gaps: add a paragraph saying that, on FMI reports without `variant-report`
  results, Genes-block rearrangement/truncation/deletion/duplication/fusion names and biomarker
  calls (TMB, MSI, HRD, tumor fraction) aren't derived. Neither is an ambiguous `CDKN2A/B` bare
  `loss` or a `p16INK4a loss and p14ARF loss …` name. Derived protein-change rows have no
  position, depth or cds_effect. Their tier is the inferred `likely_pathogenic`, pending
  confirmation.
- `dashboard/COHORT_DISCOVERY.md` §5 item 1 (Significance tiers): add one sentence. FMI
  Genes-block short variants (#76) carry no vendor status and are `likely_pathogenic` unless VUS,
  inferred from dual-block reports, and that is for Sean to confirm.
- PLAN.md is unchanged. Its line "FMI's `Genes` block turned out to be reported alterations"
  agrees with this design.

## Acceptance criteria

- [ ] `fmi.short_variant` and `fmi.cna` have a last column `source VARCHAR`; every row from
      `variant-report` elements has `source = 'variant_report'`.
- [ ] A report with no `<short-variant>` and no `<copy-number-alteration>` gets `genes_block`
      rows exactly as the table in §1 says, one per `", "` part. `allele_fraction` =
      dnaFraction/100, NULL when missing or empty. Equivocal/subclonal come from the part's own
      property, NULL when it has none. `position`, `depth`, `status`, `functional_effect` are NULL.
- [ ] A report that has `<short-variant>` / `<copy-number-alteration>` elements gets **no**
      `genes_block` rows in the matching table, even when its Genes block lists the same
      alterations.
- [ ] Biomarker pseudo-genes, `wildtype`, rearrangement-type names, bare `loss` under
      `CDKN2A/B` and `p16INK4a loss …` yield no rows in either table.
- [ ] `unified.variant.tier` for `genes_block` rows is `vus` when `is_vus`, else
      `likely_pathogenic`. `variant_report` rows map exactly as before. `unified.variant.source`
      and `unified.cna.source` exist, NULL on Caris rows.
- [ ] `mart.fact` has `alteration`/`mutation` facts for the derived variants (val without `p.`,
      tier as above) and `amplification`/`loss` facts for the derived CNA. Its columns are
      unchanged.
- [ ] `fmi.alteration` row count and content are unchanged for the same input.
- [ ] `deid` passes the leak check on the new fixture; no change to `deid.py`.
- [ ] README (Schemas, Known gaps) and COHORT_DISCOVERY.md §5.1 updated as in §4.
- [ ] `uv run pytest -q` passes. Dashboard and web checks are n/a (no change under
      `dashboard/` code or `web/`).

## Test plan

All in `tests/test_pipeline.py`, synthetic XML under a temp `DATA` via the existing `pipeline()`
helper. No `$DATA/raw`, no PHI file.

1. **Fixture XML `FMI_GENES_ONLY`** (module constant, next to `FMI`): a FinalReport with
   `<ReportId>ORD-0009876-01</ReportId>`, a synthetic PMI (`MRN` `0000555555`, other names and
   DOB distinct from `FMI`'s), `TestType` `FoundationOne`, and this Genes block:
   - `TP53` / `R248Q`, property `name="R248Q" dnaFraction="42.0" isEquivocal="false" isSubclonal="false"`
   - `PIK3CA` / `E545K, H1047R`, properties `E545K` (`dnaFraction="12"`) and `H1047R`
     (`dnaFraction="0.5" isSubclonal="true"`)
   - `KMT2C (MLL3)` / `R100*`, no AlterationProperties
   - `TERT` / `promoter -124C>T`, property `name="promoter -124C>T" dnaFraction=""` (no other attributes)
   - `RB1` / `splice site 2107-2A>G`
   - `CDKN2A/B` with three Alterations: `p16INK4a R58* and p14ARF P72L`, `CDKN2B loss`, `loss`
   - `ERBB2` / `amplification`, property `name="amplification" isEquivocal="true"`
   - `PTEN` / `loss exons 6-9`
   - `WT1` / `rearrangement intron 1`; `KRAS` / `wildtype`
   - `Tumor Mutation Burden` / `TMB-Low`; `Microsatellite status` / `MS-Stable`

   plus `<VariantProperties><VariantProperty geneName="PIK3CA" variantName="H1047R" isVUS="true"/></VariantProperties>`
   and a `variant-report` (namespace `NS`) with a `samples/sample` and an empty
   `<short-variants/>` (no CNA, rearrangement or biomarker elements). Interpretation text, if
   any, has no id-like tokens.
2. **Fixture `genes_db`** (module scope): `pipeline(tmp, {"ORD-0001234-01.xml": FMI,
   "ORD-0009876-01.xml": FMI_GENES_ONLY})`. The existing `db` fixture and its tests are not
   changed.
3. `test_genes_block_parsers`: import `genes_block_short_variant`, `genes_block_cna` from
   `uccc_genomics.fmi` and assert every row of the §1 table.
4. `test_fmi_genes_block_short_variants(genes_db)`: on `phi.fmi.short_variant` joined to
   `phi.fmi.report` for `report_id = 'ORD-0009876-01'`, the set of `(gene, cds_effect,
   protein_effect, round(allele_fraction, 6), equivocal, subclonal, is_vus)` equals the set
   below, and every row has `status` NULL, `depth` NULL and `source = 'genes_block'`:
   ```python
   {("TP53", None, "R248Q", 0.42, False, False, False),
    ("PIK3CA", None, "E545K", 0.12, None, None, False),     # property has only dnaFraction
    ("PIK3CA", None, "H1047R", 0.005, None, True, True),
    ("KMT2C", None, "R100*", None, None, None, False),      # no property: NULLs, alias stripped
    ("TERT", "-124C>T", "promoter -124C>T", None, None, None, False),   # empty dnaFraction
    ("RB1", "2107-2A>G", "splice site 2107-2A>G", None, None, None, False),
    ("CDKN2A", None, "R58*", None, None, None, False)}
   ```
5. `test_fmi_genes_block_cna(genes_db)`: `phi.fmi.cna` for `ORD-0009876-01` is exactly
   `{("ERBB2", "amplification", True, "genes_block"), ("CDKN2B", "loss", None, "genes_block"),
   ("PTEN", "loss", None, "genes_block")}` as `(gene, type, equivocal, source)`.
6. `test_fmi_genes_block_not_duplicated(genes_db)`: for `ORD-0001234-01` (which has elements
   *and* lists `TP53 R175H` / `ERBB2 amplification` in its Genes block), every
   `phi.fmi.short_variant` and `phi.fmi.cna` row has `source = 'variant_report'`. The counts
   stay 4 and 1.
7. `test_fmi_genes_block_tier(genes_db)`: `db.unified.variant WHERE source = 'genes_block'`,
   `(gene, hgvs_p, tier)`, is the expected set: all `likely_pathogenic` except
   `("PIK3CA", "H1047R", "vus")`. `variant_report` rows keep `pathogenic` / `vus` /
   `likely_pathogenic` / `unclassified` for TP53/PIK3CA/BRAF/ARID1A. Caris rows have `source`
   NULL. `db.unified.cna` has `source = 'genes_block'` on the three derived rows.
8. `test_mart_fact_genes_block(genes_db)`: `mart.fact` has `('alteration', 'TP53', 'mutation',
   'R248Q', 'likely_pathogenic')` and `('alteration', 'PIK3CA', 'mutation', 'H1047R', 'vus')`
   for the genes-only report, plus `amplification` for ERBB2 and `loss` for PTEN and CDKN2B.
   There is no fact keyed `Tumor Mutation Burden`, `Microsatellite status`, `WT1` or `KRAS`
   from that report (`kind = 'alteration'`).
9. Existing tests (`test_unified_views`, `test_variant_tier_maps_every_vendor_value`,
   `test_mart_fact_*`, leak tests) pass unchanged on `db`.

Checks to run: `uv run pytest -q`. Dashboard `npm test` n/a (no dashboard code change). Web
check n/a.

## Risks

- **Tier inference.** `likely_pathogenic` for derived rows comes from dual-block reports, not
  from a vendor call. It moves these reports into default ("pathogenic") cohort counts, which is
  the point of the issue, and might understate (known → likely) a few. It's one `CASE` branch in
  `unified.sql`, reversible, and `source` makes every affected row visible. Sean confirms
  (COHORT_DISCOVERY §5.1).
- **Cohort counts go up** for genes and diseases common in older FMI reports (alteration
  questions, dashboard gene tables, "variants without VAF"). This is intended. Real before/after
  counts are checked on the host after the daily rebuild and don't go in GitHub. The dashboard
  and the cohort API apply their small-cell rules unchanged.
- **Name grammar.** The patterns cover the name forms seen. A future FMI form that doesn't match
  is skipped, so the gap stays visible in `fmi.alteration` and no row is invented. A
  protein-looking name under a pseudo-gene that passes `SYMBOL` would be wrongly derived; every
  pseudo-gene seen has a space in its name.
- **Gene symbols.** Derived rows use the current symbol (`KMT2C`), while old `short-variant`
  rows may use the old one (`MLL3`). The split already exists between old and new reports. A
  symbol crosswalk would be a separate issue.
- **Seam.** `fmi.py` feeds every FMI consumer. The no-duplication rule is decided per report
  and per table, and test 6 pins it, so reports that load correctly today are unchanged except
  for the constant `source` column.
