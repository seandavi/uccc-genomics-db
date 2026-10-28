# Spec #79: older FMI reports, VUS from VariantProperties; `source` in the MCP schema; per-table rule test

#76 derives short variants and amplification/loss calls from the Genes block of FMI reports that
have no `variant-report` elements. VUS on those reports aren't in the Genes block: they're listed
only in `FinalReport/VariantProperties/VariantProperty`, which `fmi.py` reads just as a lookup set
for `is_vus`. So these reports have no `vus` rows, and a cohort that opts in to VUS undercounts
them without warning. The issue also carries three review findings on #76 (code-r0-1 MCP schema
text, code-r0-2 README Known gaps, code-r0-3 a test for the per-table rule).

All examples below are synthetic. Facts about the real files are structural only (no counts).

## Findings (checked 2026-10-27)

From the real XML (supervisor, aggregates only), restricted to reports with no `<short-variant>`
element:

- `VariantProperty` has exactly three attributes, `geneName`, `variantName` and `isVUS`, and no
  child elements. There is no VAF, depth, position, transcript or cds attribute.
- `isVUS` is always `"true"` on these reports.
- `variantName` forms: protein changes (most), frameshifts (`P72fs*9`), `splice site …`,
  `promoter …`, copy-number words (`amplification`, `loss`-type), rearrangement/fusion/truncation
  names and `p16INK4a …` / `p14ARF …` names. No `", "` joins, no bare `splice`, no c.-only names.
- `geneName` can carry an alias in parentheses (`KMT2C (MLL3)` style) and one slash form
  (`CDKN2A/B` style), as `Gene/Name` does in the Genes block.
- No VUS `(geneName, variantName)` on these reports is also an `Alteration` in the same report's
  Genes block, and no report repeats a pair within `VariantProperties`.

From the de-identified file (read-only): on reports with both blocks, `is_vus` short variants are
all status `unknown`, their `protein_effect` is a protein change, `splice site …` or `promoter …`,
and none of them is listed in that report's Genes block.

**Legacy rows.** The IRB delivery of 2026-10-27 carried forward VUS rows (legacy status `unknown`)
for these reports with gene, protein_effect, cds_effect, allele_fraction, depth, position,
transcript and percent_reads all populated. The current XML has nothing for these reports beyond
gene and variant name, so those extra fields came from an input the current files don't contain
(unexplained; possibly an earlier version of the files). "Reproduced" therefore means a match on
`report_id` + `gene` + `protein_effect`. The derived rows keep allele_fraction, depth, position and
cds_effect NULL (cds_effect is set only for splice/promoter names, as in #76), and the delivery
will keep showing NULL VAF for them.

## Goal

1. For a report with **no** `<short-variant>` element, derive one `fmi.short_variant` row per
   `VariantProperty` with `isVUS = "true"` whose name parses as a short variant, with
   `is_vus = true` and `source = 'variant_properties'`.
2. They reach `unified.variant` with tier `vus` (existing `is_vus`-first `CASE` branch) and
   `mart.fact` as `alteration` / `mutation` facts with tier `vus`.
3. MCP schema text documents `source` on `unified.variant` and `unified.cna` (code-r0-1).
4. README Known gaps: VUS are no longer a gap on these reports; rearrangements, biomarkers and the
   VUS name forms not derived stay listed (code-r0-2).
5. A test pins the per-table no-duplication rule on a report with `<short-variant>` elements and
   no `<copy-number-alteration>` (code-r0-3).

### Why `source = 'variant_properties'` and not `'genes_block'`

The rows come from a different XML block with different content (gene and name only, never a
VAF or equivocal/subclonal flag), and the #76 tier rule `WHEN v.source = 'genes_block' THEN
'likely_pathogenic'` is about Genes-block rows. A distinct value keeps `genes_block` meaning
"from the Genes block", lets MCP/assistant users filter or audit these rows on their own, and
needs no `unified.sql` change: the `is_vus` branch comes first, so tier is `vus`.

## Non-goals

- No VUS rows for a report with any `<short-variant>` element. Its VUS already come through
  `variant-report` with `is_vus` from the lookup set, as today. Same per-report rule as #76.
- No VUS copy-number rows: a VUS named `amplification` / `loss …` is **not** written to `fmi.cna`.
  No VUS rearrangement, fusion or truncation rows. Both go in Known gaps.
- No VUS row for a `p16INK4a … loss …` name, or for a plain protein change under a slash gene
  name (`CDKN2A/B` + `P114L`), since `genes_block_short_variant` returns None for them. A
  `p16INK4a <change>` name under `CDKN2A/B` gives gene `CDKN2A`, as the Genes-block path and the
  `variant-report` rows name it, so all three paths agree. Known gaps lists the skipped forms.
- No VUS row for a `VariantProperty` whose `isVUS` isn't `true` (never seen on these reports;
  non-VUS alterations are in the Genes block).
- No guessed values. `position`, `transcript`, `strand`, `allele_fraction`, `depth`,
  `percent_reads`, `status`, `functional_effect`, `equivocal`, `subclonal` are NULL. No
  pathogenicity inference: the tier is `vus` because FMI flags them VUS.
- No change to `genes_block_short_variant`, `genes_block_cna`, the Genes-block derivation,
  `fmi.alteration`, `fmi.cna`, `unified.sql`, `mart.sql`, the DDL, or the `vus` lookup set.
- No change to `deid.py`, the PHI column lists, id hashing, date shifting or the leak assert.
  `research_id` and `report_id` are unaffected: the new rows hang off existing `report_id`s and
  no key or identity code changes. `'variant_properties'` is a constant label, not PHI, and the
  existing leak scan covers it like any other VARCHAR.
- No new output path and no suppression change. The rows reach the dashboard loader
  (`MIN_CELL = 5`), the cohort API (floored counts, secondary suppression, whole-cohort rule) and
  MCP only through `unified.variant` / `mart.fact`, which already apply their small-cell rules.
  VUS are opt-in in the cohort API (`tier[]` default is pathogenic + likely_pathogenic), so default
  counts don't move.
- No new dependency. No change under `dashboard/` code or `web/`.
- Re-checking the IRB delivery is the orchestrator's job on the host after the daily rebuild.

## Design

### 1. `src/uccc_genomics/fmi.py`, `rows_for(path)`

One block, inside the existing `if fr is not None:` block, **after** the `for g in
fr.findall(".//Genes/Gene"):` loop and before the `Trials` loop:

```python
        # Older reports list their VUS only in VariantProperties (#79). Same per-report rule as the
        # Genes block; a VariantProperty carries only gene and name, so everything else is NULL.
        if not has_sv:
            derived = {(r[1], r[3]) for r in t["short_variant"]}  # (gene, protein_effect) from the Genes block
            for vp in fr.findall(".//VariantProperties/VariantProperty"):
                sv = genes_block_short_variant(vp.get("geneName"), vp.get("variantName") or "") if b(vp.get("isVUS")) else None
                if sv and (sv[0], sv[2]) not in derived:
                    derived.add((sv[0], sv[2]))
                    t["short_variant"].append((rid, *sv, *[None] * 10, True, "variant_properties"))
```

- `sv` is `(gene, cds_effect, protein_effect)` from the existing `genes_block_short_variant`, so
  alias stripping (`KMT2C (MLL3)` → `KMT2C`), `splice site` / `promoter` cds extraction and the
  `p16INK4a` → `CDKN2A` rule are the same as for Genes-block rows. Copy-number, rearrangement and
  biomarker names return None and are skipped.
- `*[None] * 10` fills `position, transcript, strand, allele_fraction, depth, percent_reads,
  status, functional_effect, equivocal, subclonal`, then `is_vus = True`, `source`. That's the
  DDL's 16 columns: `report_id, gene, cds_effect, protein_effect, position, transcript, strand,
  allele_fraction, depth, percent_reads, status, functional_effect, equivocal, subclonal, is_vus,
  source`.
- At this point `t["short_variant"]` holds only this report's `genes_block` rows (the
  `variant-report` rows are appended later, and there are none when `not has_sv`), so `derived`
  is the Genes-block set. A VUS that the Genes block already listed (as `PIK3CA H1047R` in the
  #76 fixture) keeps its single `genes_block` row, whose `is_vus` is already true from the lookup
  set. `derived.add` also stops a repeated pair (never seen) from duplicating.
- `has_sv` is the existing variable (#76). `vp.get("variantName") or ""` keeps a missing name from
  reaching `re.fullmatch(None)`; `""` parses to None.

The module docstring's block list doesn't change. `load()` is unchanged.

### 2. Vendor source fields (PLAN.md mapping, extended)

| `fmi.short_variant` column | source for `variant_properties` rows |
|---|---|
| `gene` | `VariantProperty/@geneName` before ` (`; `CDKN2A` for `p16INK4a …` names |
| `protein_effect` | `VariantProperty/@variantName` (the p16INK4a change for CDKN2A) |
| `cds_effect` | `@variantName` after `splice site ` / `promoter `; NULL for protein changes |
| `is_vus` | `true` (`@isVUS = "true"`; other values give no row) |
| `source` | `'variant_properties'` |
| all other columns | NULL (not in `VariantProperty`) |

`unified.variant` (no SQL change): `hgvs_p` = protein_effect, `hgvs_c` = cds_effect, `vaf`,
`depth`, `chrom`, `pos`, `consequence`, `is_subclonal`, `vendor_call` NULL, `source =
'variant_properties'`, `tier = 'vus'`. `mart.fact` (no SQL change): `kind = 'alteration'`, `key` =
gene, `sub = 'mutation'`, `val` = protein_effect, `tier = 'vus'`.

### 3. `mcp/src/uccc_genomics_mcp/server.py` (code-r0-1)

In `DOCS["unified"]`:

- `unified.variant` Columns line: add `source` after `vendor_call` (before `tier`), and add this
  bullet after the `tier` bullet:
  ```
     - `source` (FMI only; NULL for Caris): `variant_report` (FMI's variant-report elements), `genes_block` (derived from the curated Genes block on older reports without those elements, #76: no vendor_call, inferred tier `likely_pathogenic` unless VUS) or `variant_properties` (VUS listed only in VariantProperties on those reports, #79: tier `vus`, gene and protein change only, no VAF, depth or position).
  ```
- `unified.cna` Columns line: add `source` after `vendor_call`, and a bullet:
  ```
     - `source` (FMI only; NULL for Caris): `variant_report`, or `genes_block` for amplification/loss calls derived from the Genes block on older reports (#76).
  ```

Text only; the query guard and connection are untouched.

### 4. `README.md` (code-r0-2)

- Schemas, `fmi.*`: extend the `source` sentence: "`source` is `variant_report`, or
  `genes_block` for rows derived from the curated Genes block on reports without
  `<short-variant>` / `<copy-number-alteration>` elements (older reports, #76), or (short_variant
  only) `variant_properties` for VUS listed only in `VariantProperties` on reports without
  `<short-variant>` elements (#79)."
- Schemas, `unified.*`: after "…an inference rather than a vendor call." add "FMI
  `variant_properties` rows are VUS (tier `vus`)."
- Known gaps, the #76 paragraph: append "VUS on these reports come from `VariantProperties` (#79)
  with gene and protein change only (no VAF, depth or position; cds_effect only for splice/promoter
  names). VUS named as copy-number, rearrangement, fusion or truncation calls, `p16INK4a … loss`
  names, and plain protein changes under a slash gene name (`CDKN2A/B` style) are not derived."
  The paragraph keeps saying rearrangements and biomarker calls aren't derived.

`dashboard/COHORT_DISCOVERY.md`, `docs/ARCHITECTURE.md` and `PLAN.md` don't change: §5.1's
inference sentence is about Genes-block rows, and these rows carry FMI's own VUS flag.

## Acceptance criteria

- [ ] A report with no `<short-variant>` element gets one `fmi.short_variant` row per
      `VariantProperty` with `isVUS="true"` whose name parses as a short variant, with
      `source = 'variant_properties'`, `is_vus = true`, gene/cds/protein as in §2 and the other
      ten columns NULL.
- [ ] A VUS already derived from that report's Genes block keeps its single `genes_block` row;
      no `variant_properties` duplicate.
- [ ] `VariantProperty` entries with `isVUS` false or missing, copy-number names
      (`amplification`), rearrangement names, `p16INK4a … loss …` names and plain protein changes
      under `CDKN2A/B` give no row in `fmi.short_variant` or `fmi.cna`.
- [ ] A report with any `<short-variant>` element gets no `variant_properties` rows.
- [ ] A report with `<short-variant>` elements and no `<copy-number-alteration>` gets
      `genes_block` CNA rows and only `variant_report` short variants (code-r0-3).
- [ ] `unified.variant` rows with `source = 'variant_properties'` have tier `vus`; `mart.fact` has
      `alteration` / `mutation` facts with tier `vus` for them. Existing `genes_block` and
      `variant_report` tiers unchanged.
- [ ] MCP `DOCS["unified"]` lists `source` on `unified.variant` and `unified.cna` with the §3
      bullets.
- [ ] README Schemas and Known gaps updated as in §4.
- [ ] No change to `deid.py`, `unified.sql`, `mart.sql`, the DDL or `genes_block_*`; `deid`
      passes its leak check on the fixtures.
- [ ] `uv run pytest -q` passes. Dashboard and web checks n/a.

## Test plan

All in `tests/test_pipeline.py`, synthetic XML only: the `genes_db` fixture (temp `DATA` via
`pipeline()`) and one `rows_for` call on a file in `tmp_path`. No `$DATA/raw`, no PHI file.

1. **Fixture `FMI_GENES_ONLY`**: replace its `VariantProperties` with:
   ```xml
   <VariantProperties>
    <VariantProperty geneName="PIK3CA" variantName="H1047R" isVUS="true"/>   <!-- also in the Genes block -->
    <VariantProperty geneName="ARID1A" variantName="Q200*" isVUS="true"/>
    <VariantProperty geneName="KMT2D (MLL2)" variantName="R50fs*3" isVUS="true"/>
    <VariantProperty geneName="NF1" variantName="splice site 100+1G>A" isVUS="true"/>
    <VariantProperty geneName="TERT" variantName="promoter -146C>T" isVUS="true"/>
    <VariantProperty geneName="CDKN2A/B" variantName="p16INK4a A57V" isVUS="true"/>
    <VariantProperty geneName="CDKN2A/B" variantName="P114L" isVUS="true"/>
    <VariantProperty geneName="CDKN2A/B" variantName="p16INK4a loss and p14ARF loss exons 1-2" isVUS="true"/>
    <VariantProperty geneName="MYC" variantName="amplification" isVUS="true"/>
    <VariantProperty geneName="NOTCH1" variantName="rearrangement intron 2" isVUS="true"/>
    <VariantProperty geneName="BRCA2" variantName="E100K" isVUS="false"/>
    <VariantProperty geneName="BRCA1" variantName="D20N"/>
   </VariantProperties>
   ```
   (`>` inside attribute values is valid XML; the existing fixture already writes `cds-effect="524G>A"`.)
2. `test_fmi_genes_block_short_variants`: add `AND source = 'genes_block'` to its query. Its
   expected set and `len(rows) == 7` stay as they are.
3. New `test_fmi_variant_properties_vus(genes_db)`: on `phi.fmi.short_variant WHERE report_id =
   GENES_ONLY AND source = 'variant_properties'`:
   - `{(gene, cds_effect, protein_effect)}` equals
     `{("ARID1A", None, "Q200*"), ("KMT2D", None, "R50fs*3"), ("NF1", "100+1G>A", "splice site 100+1G>A"),
     ("TERT", "-146C>T", "promoter -146C>T"), ("CDKN2A", None, "A57V")}`, and the row count is 5.
   - every row has `is_vus = true` and `position, transcript, strand, allele_fraction, depth,
     percent_reads, status, functional_effect, equivocal, subclonal` all NULL.
   - `count(*)` for `gene = 'PIK3CA' AND protein_effect = 'H1047R'` on that report is 1, with
     `source = 'genes_block'`.
   - no row on that report has gene `BRCA1`, `BRCA2`, `MYC` or `NOTCH1`, or protein_effect `P114L`;
     `phi.fmi.cna` for that report has no `MYC` row (the existing `test_fmi_genes_block_cna` exact
     set also pins this).
   - `phi.fmi.short_variant WHERE report_id = 'ORD-0001234-01' AND source = 'variant_properties'`
     is empty (that report has `<short-variant>` elements and a VUS in `VariantProperties`).
4. `test_fmi_genes_block_tier`: add an assert that
   `SELECT DISTINCT tier FROM db.unified.variant WHERE source = 'variant_properties'` is
   `[("vus",)]`. Its existing asserts are unchanged.
5. `test_mart_fact_genes_block`: add `("ARID1A", "mutation", "Q200*", "vus") in fact` and
   `("KMT2D", "mutation", "R50fs*3", "vus") in fact`. The existing amplification assert
   (`== {"ERBB2"}`) also pins that the MYC VUS made no CNA fact.
6. New `test_fmi_genes_block_rule_is_per_table(tmp_path)` (code-r0-3): write `tmp_path /
   "ORD-0007777-01.xml"` with a FinalReport (`ReportId` `ORD-0007777-01`, no PMI needed) whose
   Genes block is `_gene("TP53", ("R175H", []))` + `_gene("ERBB2", ("amplification", []))`,
   `VariantProperties` with `ARID1A` / `Q200*` / `isVUS="true"`, and a `variant-report`
   (namespace `NS`) with one `<short-variant gene="TP53" cds-effect="524G>A" protein-effect="R175H"
   status="known"/>` and no CNA elements. Call `uccc_genomics.fmi.rows_for(str(path))` and assert:
   - `t["cna"] == [("ORD-0007777-01", "ERBB2", "amplification", None, None, None, None, None, None, "genes_block")]`
   - `[r[-1] for r in t["short_variant"]] == ["variant_report"]` (no `genes_block`, no
     `variant_properties` row).
7. Existing tests pass unchanged otherwise (`test_fmi_genes_block_not_duplicated`'s alteration
   count of 14 stays: `VariantProperties` adds no `fmi.alteration` rows).

Checks: `uv run pytest -q`. Dashboard `npm test` n/a (no dashboard code change). Web check n/a.

## Risks

- **VUS counts go up** for older FMI reports when a cohort opts in to VUS. That is the point.
  Default (pathogenic + likely_pathogenic) counts don't move. The dashboard and cohort API apply
  their small-cell rules unchanged; real before/after counts are checked on the host and don't go
  in GitHub.
- **No VAF on these rows.** VAF filters and "variants without VAF" checks see NULL. The legacy
  rows had values from an input the current XML lacks; documented above and in Known gaps.
- **Seam.** `fmi.py` feeds every FMI consumer. The block runs only when `not has_sv` and only
  appends rows with a new `source` value, so reports with `<short-variant>` elements are byte-for-
  byte unchanged, and Genes-block rows are unchanged (the block runs after them and skips pairs
  they already cover). Test 3 pins the no-duplication case, test 6 the per-table rule.
- **Name grammar.** VUS names that don't parse are skipped, never invented. A future name form
  stays out until the parser learns it; the reused parser keeps the Genes-block and VUS paths
  consistent.
