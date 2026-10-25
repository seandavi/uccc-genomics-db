# Cohort discovery and feasibility: questions and UI

Written 2026-10-01. It moves the cohort page away from "pick filters, get a
count" toward the questions a clinical researcher has when writing a grant or
defining a study population. It builds on `COHORT_TOOL.md` (the phase 1 API
and its privacy controls) and does not replace it. All numbers in this document
are synthetic and illustrative. Real answers are computed on the pipeline host
and never committed; this repository is public. Counts are distinct patients. Any count from 1 to 4 is
shown as "<5", the same floor the API applies.

## 1. What the data can and cannot say

The answer to every question below is bounded by this table, so the UI has to
show it.

| Present | Coverage |
|---|---|
| Disease (OncoTree code, organ system, vendor text) | every report (4,800 reports, 4,300 patients) |
| Sex | every report |
| Age at collection | Caris tissue only. FMI age is not derived; on Caris liquid reports the value is a sentinel. |
| Collection year | Earliest to latest collection year. Some reports are dated after today because of date-shift spillover, so the last two years are partial. |
| Assay class (tissue, liquid, heme), vendor, assay name | every report |
| Variants, CNAs, fusions with vendor significance | both vendors |
| TMB, MSI | both vendors |
| LOH, IHC (PD-L1 CPS/TPS by clone, HER2, ER/PR, MMR, CLDN18, FOLR1, …) | Caris only |
| RNA expression | Caris only: whole-transcriptome TPM for 1,400 patients (1,200 tissue RNA), and percentiles for 300 target genes for 1,100 patients |
| Specimen site and type (primary, metastatic, recurrence) | Caris only |
| Tumor purity | both vendors |
| Viral reads (HPV, EBV, HHV-8) | FMI only |
| Therapy associations, trial matches | Caris (evidence level), FMI (FDA flag, NCT trials) |
| Genes tested negative | Caris wild-type list; FMI pertinent negatives only, so FMI under-reports this |

| Absent | Consequence for the UI |
|---|---|
| Stage, line of therapy, treatment received, outcomes, vital status | No survival or response endpoints. Any eligibility rule based on these has to be stated as "not checkable here". |
| Race, ethnicity | No diversity breakdown, which NIH grants usually ask for. Say so in the feasibility statement. |
| FMI age | An age filter drops most FMI patients into "unknown". |

### Data issues that change counts today

These came up while answering the questions. Each one makes a phase 1 API
count wrong or ambiguous, so they have to be fixed before the new page goes out
(phase 0 below).

1. **Variant significance is not normalised.** The API's "pathogenic" class is
   `NOT coalesce(is_vus, false)`. Caris leaves `is_vus` NULL on 200 "Likely
   Benign Variant" and 300 "Mutated, Unclassified" rows, so both currently
   count as pathogenic. FMI has 5,000 rows with status `unknown` and
   `is_vus = false`, which is ambiguous. `unified.variant` needs one tier
   column (pathogenic, likely pathogenic, VUS, likely benign or benign,
   unclassified) that every filter uses.
2. **HER2 calls use several spellings for the same result.** "her2-low" and
   "low" are separate values, and the composite "ER/PR/Her2/Neu" calls ("hr-positive her2-low",
   "triple negative") sit next to the single-marker calls (#22).
3. **`consequence` mixes case.** "missense" and "Missense" are separate values.
4. **Viral calls need review.** FMI marks HHV-4 (EBV) as "likely" in 40
   prostate patients and HPV-16 in 30. That is more than in cervical (8) or
   head and neck (6) cancer. These calls should not be offered as a filter
   until someone with domain knowledge has looked at them.
5. **FMI `fda_approved` means approved in any indication**, not in the
   patient's tumor type. An "actionable" filter has to label it that way.

## 2. Questions a researcher would ask

Twenty questions, grouped by why someone asks them. "Operations" lists what
the question needs from the tool. "Today" is whether the phase 1 API
(`/api/cohort`) can answer it.

Operation tags: **F** filter, **OR** union within a criterion, **AND**
co-occurrence across criteria, **NOT** exclusion or tested-negative, **≥**
numeric threshold, **P** pivot (two dimensions), **T** accrual over time,
**SEQ** order of reports, **SPEC** specimen attribute, **MOD** availability of
a data type, **XV** cross-vendor.

### A. Sizing and accrual (the feasibility paragraph)

| # | Question | Ops | Illustrative answer | Today |
|---|---|---|---|---|
| 1 | How many KRAS G12C non-small cell lung cancer patients have we sequenced since 2023, and how many a year, compared with all NSCLC tested? | F, T | 10 all years, 8 since 2023; out of 200 and 120 NSCLC tested. Each year is under 5. | yes |
| 2 | How has testing volume changed by year in our six biggest tumor types? I need to project screening for a five-year grant. | P (disease × year), T | Melanoma 70 → 110 a year (first → latest year); pancreas 25 → 90; breast 30 → 85 | partial: one disease at a time |
| 3 | How many early-onset (<50) colorectal cancer patients do we have? | F, demographics | 30 of the 150 COADREAD patients with a known age; 400 COADREAD patients in total, most with unknown age | yes, with the age caveat |

### B. Biomarker-defined populations (basket and umbrella trials)

| # | Question | Ops | Answer | Today |
|---|---|---|---|---|
| 4 | Tumor-agnostic immunotherapy: which tumor types have MSI-high or TMB ≥ 10 patients, and what fraction of those tested? | OR, ≥, P (disease × call) | Melanoma 400 of 800, endometrial 50 of 200, bladder 40 of 160, colorectal 30 of 400 | no |
| 5 | Fusion basket: how many solid-tumor patients carry NTRK, RET, ALK, ROS1, FGFR2/3, NRG1, BRAF or MET fusions, by gene? | OR, F, P (gene × disease) | 120 in total; FGFR2 30, BRAF 25, ALK 20, ROS1 10, RET 10; NTRK1/2/3 together 15 | partial: no breakdown by gene |
| 6 | HER2-directed ADC: HER2-low or ultralow breast cancer by IHC, plus ERBB2 amplification or mutation in any tumor type | OR across modalities, P | Breast IHC: her2-low 25 (+5 recorded as "low"), ultralow 6. ERBB2 amplified or mutated: breast 30, ovary 20, colorectal 20, bladder 15, cholangiocarcinoma 15 | no |
| 7 | PARP or HRD study: HRR gene pathogenic variant or LOH-high in ovarian, prostate and pancreatic cancer | OR across modalities, P | Ovary 180 of 540 (HRR 110, LOH-high 120); prostate 120 of 530; pancreas 40 of 350 | no |
| 8 | ADC targets by expression: TROP2 (TACSTD2) or B7-H3 (CD276) in the top quartile, by tumor type | ≥ (percentile), MOD, P | TROP2 ≥ 75th percentile: ovary 80 of 250, colorectal 40 of 150, melanoma 30 of 100 | no |
| 9 | Gastric, GEJ or esophageal cancer: how do CLDN18 positivity and PD-L1 CPS ≥ 10 overlap? (Zolbetuximab versus checkpoint inhibitors.) | AND, ≥, P (2×2) | 80 patients with both stains: CLDN18+ and CPS ≥ 10, 10; CLDN18+ only, 30; CPS ≥ 10 only, 10; neither, 30 | no |

### C. Combinations of genes

| # | Question | Ops | Answer | Today |
|---|---|---|---|---|
| 10 | KRAS-mutant NSCLC: how many have a co-alteration in STK11 or KEAP1? | AND, P (2×2) | 50 KRAS-mutant; 20 with STK11 or KEAP1, 30 without | no: genes are OR-only |
| 11 | Anti-EGFR study: RAS and BRAF V600E wild-type colorectal cancer on tissue testing | NOT, tested-negative | 400 tested; 210 have a KRAS, NRAS or BRAF V600E alteration; 190 do not, and 170 of those have KRAS explicitly reported wild-type | no |
| 12 | What does the alteration landscape of cholangiocarcinoma look like, so I can pick a target? | P (gene × alteration class) | 170 patients: TP53 60, KRAS 35, ARID1A 25, CDKN2A 35 (20 loss), BAP1 15, IDH1 15, ERBB2 amplified 10 | partial: the static Genes page |
| 13 | PIK3CA hotspot (H1047R, E545K, E542K) in ER-positive breast cancer | AND across modalities | 50 ER+ breast patients (Caris IHC); 15 with a hotspot | no |

### D. Specimens, sequences and available data (correlative science)

| # | Question | Ops | Answer | Today |
|---|---|---|---|---|
| 14 | Resistance study: who had tissue testing and then a later liquid biopsy? How many breast patients have ESR1 on liquid? | SEQ, F | 150 patients with tissue then liquid: skin 30, pancreas 20, breast 20, bowel 15. ESR1 on liquid in breast: 30 | no |
| 15 | Metastasis biology: how many liver metastasis biopsies, by primary tumor? | SPEC, P | Colorectal 40, pancreas 35, breast 20, ovary 15, CUP 15, NET 10 | no |
| 16 | KRAS G12D pancreatic cancer with RNA-seq, and with tumor purity ≥ 30%, for a correlative aim | MOD, ≥, AND | 120 G12D; 50 with Caris WTS; 60 with purity ≥ 30% | no |
| 17 | Assay concordance: who was tested by both vendors, and do their TMB calls agree? | XV, P (vendor × vendor) | 60 patients tested by both; low/low 30, Caris intermediate with FMI low 10, every other cell under 5 | no |

### E. Confounders and actionability (preliminary data, unmet need)

| # | Question | Ops | Answer | Today |
|---|---|---|---|---|
| 18 | In liquid biopsies, how many patients carry clonal hematopoiesis genes (DNMT3A, TET2, ASXL1, PPM1D) that could be mistaken for tumor variants? | F, MOD, NOT (to exclude) | 400 of 900 liquid-biopsy patients; Caris flags CH explicitly in 200 | partial: no exclusion |
| 19 | Viral-associated tumors: HPV-16/18 or EBV by tumor type | F, P | Held: see data issue 4 | no |
| 20 | What fraction of each tumor type has a Level 1 or FDA-labelled therapy association, and how many matched a trial? | F, P | Melanoma 600 of 850; breast 220 of 380; pancreas 20 of 350; CUP 5 of 200 | no |

### What the questions show

- The phase 1 API fully answers 3 of 20 (1, 3, and part of 5). The blockers
  are the same few missing capabilities again and again: biomarkers and IHC
  (4, 6, 7, 9, 13), AND across genes (10), NOT and tested-negative (11, 18),
  pivots (2, 4, 5, 12, 15, 17), specimen, sequence and data-type facts (14 to
  17), and numeric thresholds (4, 8, 9, 16).
- Researchers ask in **criteria**, not in filter columns. "HRR pathogenic
  variant or LOH-high" is one eligibility criterion that spans two tables.
- Most answers are **fractions of a denominator** ("40 of 160 tested"). The
  denominator has to be "patients who could have had this result", which
  differs by modality: IHC exists only on Caris and WTS only on Caris RNA.
- Rare cohorts land under 5 quickly (NTRK, KRAS G12C by year). The UI has to
  make "<5" look like an answer and offer the next coarser grouping, not show
  a blank.

## 3. Design

### 3.1 One idea: the cohort definition

Everything the user does, whether clicking or chatting, edits one
**cohort definition**: a small JSON document. The filter view renders it as
criterion cards and the assistant proposes edits to it. The URL, the saved
cohort, the feasibility statement and the "request this cohort" email all
serialise it. Neither the browser nor the LLM ever sends SQL.

```json
{
  "name": "KRAS G12C NSCLC, no STK11/KEAP1, PD-L1 high, 2023+",
  "population": {
    "oncotree": ["NSCLC"], "sex": [], "age_band": [], "vendor": [],
    "assay_class": [], "years": [2023, 2026]
  },
  "criteria": [
    {"id": "c1", "kind": "alteration", "gene": ["KRAS"], "aa": ["G12C"], "tier": ["pathogenic", "likely_pathogenic"]},
    {"id": "c2", "kind": "alteration", "gene": ["STK11", "KEAP1"], "mode": "exclude"},   // phase 2
    {"id": "c3", "kind": "ihc", "marker": "PD-L1", "measure": "TPS", "at_least": 50}
  ],
  "scope": "patient",
  "breakdown": ["oncotree", "has_wts"],
  "pivot": {"rows": "oncotree", "cols": "year"}
}
```

Rules:

- Criteria combine with AND; values inside a criterion combine with OR.
- `mode` is `include` (default), `exclude`, or `tested_negative`. `exclude`
  means no matching finding on any report; `tested_negative` additionally
  requires that the gene was reported wild-type or as a pertinent negative.
  These are different populations: 190 versus 170 in question 11.
- `scope: "report"` makes every criterion match on the same report (same
  specimen); `"patient"` lets them match on any of the patient's reports.
  This matters for co-mutation (question 10) and for tissue/liquid pairs.
- `kind: "sequence"` (phase 2) holds two sub-criteria and an order: "A on a
  tissue report, then B on a later liquid report" (question 14).
- Numeric criteria accept only fixed cut points from the vocabulary (TMB 10,
  16, 20; CPS 1, 10, 20; TPS 1, 50; expression percentile 50, 75, 90; purity
  20, 30, 50). Free numbers would allow probing by sliding a threshold one
  patient at a time.

**Phase 1 (#34)** implements the definition in `mcp/src/uccc_genomics_mcp/cohort/`
(`docs/specs/34-cohort-module-definition-operations.md`). It differs from the text above in
these ways:

- `any_of` is a new kind: OR across modalities (2–8 leaf criteria, one funnel step), for
  questions 4, 6 and 7.
- `age` is `age_band` (the `mart.report` column), and `organ` is a population field.
- `ihc.measure` is `TPS` or `CPS`, the mart's `unit` spelling. `% stained` has no cut points, so it is not a measure.
- `expression.gene` is a list (values OR), like `alteration.gene`.
- Breakdown dimensions are `oncotree`, `organ`, `sex`, `age_band`, `vendor`, `assay_class`,
  `site_type` and `has_wts`. `by_year` is always returned, so `year` is not a breakdown, and
  there is no `vendor_class` (pivot `vendor` × `assay_class`).
- Pivot axes are a dimension (or `year`), or `c<n>.key|sub|val`: the matched fact's column.
  There is no yes/no criterion axis; its "no" side is exclusion (phase 2).
- Question 16's RNA part comes from the `has_wts` breakdown, because `data` is phase 2.
- A criterion with no value filter means "has any result of this kind" (an `ihc` without
  `call`, a `biomarker` without `call`), which restricts the cohort to tested patients.
- `cohort_id` covers `version`, `population`, `scope` and the criteria, not the name,
  breakdown, pivot, criterion ids or order.
- "Any of the patient's reports" means any of the patient's *in-population* reports. The accrual
  year is the latest, over the criteria, of the earliest matching year.
- Pivot suppression runs on both axes to a fixed point, and also hides a row or column total when
  its one hidden cell would otherwise equal it (the rest of the line being zeros).
- Phase 2 and rejected with a clear error: `exclude`, `tested_negative`, `scope: "report"`, `sequence`, `data`.

Criterion kinds and the questions they serve:

| kind | fields | questions |
|---|---|---|
| `alteration` | gene[], class (mutation, amplification, loss, fusion), aa[], tier[] | 1, 5, 6, 7, 10–13, 16, 18 |
| `biomarker` | name (TMB, MSI, LOH), call[] or at_least | 4, 7, 17 |
| `ihc` | marker, clone?, call[] or measure + at_least | 6, 9, 13 |
| `expression` | gene, percentile_at_least | 8 |
| `specimen` | site_type[], site[], purity_at_least | 15, 16 |
| `data` | has (wts, liquid, tissue, both_vendors, serial) | 14, 16, 17, 18 |
| `actionability` | evidence (caris_level1, fmi_fda_any_indication, fmi_trial) | 20 |
| `any_of` | of[] (2–8 leaf criteria above, OR) | 4, 6, 7 |
| `sequence` (phase 2) | first, then, min_gap_days? | 14 |

### 3.2 The mart behind it

The phase 1 SQL is one hand-built query for one shape of question. Twenty
questions over eight criterion kinds would turn it into eight hand-built
queries. Instead, the daily `genomics deid` builds two tables in a new
`mart` schema (`sql/mart.sql`, next to `unified.sql`), and every criterion
kind compiles to the same template over them.

```
mart.report        one row per report: research_id, vendor, report_id, year,
                   year_complete, sex, age, age_band, oncotree, organ, disease, assay_class, assay_name,
                   purity, site_type, site, has_wts
mart.fact          one row per finding: research_id, vendor, report_id,
                   kind, key, sub, val, num, unit, tier
                   e.g. ('alteration', 'KRAS', 'mutation', 'G12C', NULL, NULL, 'pathogenic')
                        ('ihc', 'PD-L1', '22c3', 'positive', 55.0, 'TPS', NULL)
                        ('expression', 'TACSTD2', NULL, NULL, 81.0, 'percentile', NULL)
                        ('tested_negative', 'KRAS', 'wildtype', NULL, NULL, NULL, NULL)
```

`unit` says which measure `num` is (`TPS`, `CPS`, `% stained`, `mut/Mb`, `%`,
`percentile`), so `TPS >= 10` cannot match a record whose only score is a
CPS. It is NULL whenever `num` is. Built by #33 (spec
`docs/specs/33-mart-schema-mart-report-and-mart-fact.md`).

Compiler, in the API:

```
criterion  →  EXISTS (SELECT 1 FROM mart.fact f
                      WHERE f.research_id = r.research_id      -- or report_id, by scope
                        AND f.kind = ? AND list_contains(?, f.key) ... AND f.num >= ?)
exclude    →  NOT EXISTS (same)
funnel     →  the population, then population ∧ c1, then ∧ c2, … ; one statement, one count per step
pivot      →  GROUP BY two dimensions of mart.report, or by a criterion's key
```

The phase 0 normalisation (significance tier, HER2 calls, `consequence`
case, partial-year flag) happens once in `unified.sql` (#32), and `mart.sql`
reads it. Every count then agrees with every other.

### 3.3 The page: Discover

One page (`dashboard/src/discover.md`) that replaces `cohort.md`. It is still
Observable Framework: the definition lives in a `Mutable`, and both the
builder and the assistant write to it. Three columns on a wide screen; the
assistant collapses into a drawer below 1,200 px.

```
┌ KRAS G12C NSCLC, no STK11/KEAP1, PD-L1 high, 2023+  v4 ▾  [Compare] [Share link] [Feasibility statement] [Request data] ┐
├──────────────────────────────┬────────────────────────────────────────────────────┬─────────────────────────────┤
│ POPULATION                   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │ ASSISTANT                   │
│ [NSCLC ×] [2023–2026 ×]      │  │ <5       │ │ –        │ │ –        │ │ –      │ │                             │
│ + sex  + age  + assay        │  │ patients │ │ accrual  │ │ of 120   │ │        │ │ > How many KRAS G12C lung   │
│                              │  └──────────┘ └──────────┘ │ tested   │ └────────┘ │   patients could we screen  │
│ CRITERIA            (AND)    │                            └──────────┘            │   for a sotorasib combo?    │
│ ┌──────────────────────────┐ │  FUNNEL                                            │                             │
│ │ ● KRAS G12C  pathogenic  │ │  NSCLC 2023+            120 ████████████████████   │ I set: NSCLC, KRAS G12C,    │
│ │   mutation · any report  │ │  ∧ KRAS G12C              8 ██                     │ 2023 onward. 8 patients,    │
│ └──────────────────────────┘ │  ∧ no STK11/KEAP1         6 █                      │ about 2 a year...           │
│ ┌──────────────────────────┐ │  ∧ PD-L1 TPS ≥ 50        <5 ▒                      │                             │
│ │ ⊘ STK11 or KEAP1         │ │                                                    │ [Apply] [Show me why]       │
│ │   exclude                │ │  [ Accrual ] [ Breakdown ] [ Pivot ] [ Data notes ]│                             │
│ └──────────────────────────┘ │  ▁▃▅▂  2023 <5  2024 <5  2025 <5  2026 <5          │ Suggestions:                │
│ + Add criterion  ⌕ gene, IHC,│                                                    │  • drop TPS ≥ 50 → 6        │
│   biomarker, expression…     │  Coverage: PD-L1 TPS exists on Caris only          │  • TPS is Caris-only        │
└──────────────────────────────┴────────────────────────────────────────────────────┴─────────────────────────────┘
```

**Left: builder.** The population sits at the top as chips. Below it, each
criterion is a card with an include, exclude or tested-negative toggle and a
"same report" lock. "Add criterion" is a typeahead over the whole
vocabulary: typing "her2" offers *IHC HER2 call*, *ERBB2 amplification* and
*ERBB2 mutation*, each with its patient count. Genes show their common
protein changes ("KRAS: G12D 240, G12V 180, G12C 60 …"). Dragging a card
reorders the funnel.

**Centre: answer.**

- Cards: patients, accrual a year over the window, percentage of the right
  denominator, and the existing tier badge. Under the percentage the card
  names the denominator ("of 120 NSCLC patients tested since 2023").
- **Funnel**, an attrition table that reads like a CONSORT diagram: one row
  for each criterion as it is added, with the count after it. This view is
  what makes the work iterative: the user sees which criterion costs the
  most patients.
- Tabs:
  - *Accrual*: patients by year of first qualifying report. Years under 5
    are drawn as a hatched "<5" bar, not left blank. Partial years (the
    current year and date-shift spillover) are shaded.
  - *Breakdown*: the phase 1 bars (disease, vendor and class, sex, age,
    alteration class).
  - *Pivot*: choose rows and columns from population dimensions or
    criteria. This answers 2, 4, 5, 9, 12, 15 and 17 directly. Cells are
    floored and secondarily suppressed by row and by column, and the
    marginal totals are shown floored.
  - *Data notes*: the coverage caveats that apply to this definition, built
    from the criterion kinds (an IHC criterion adds "Caris only, n tested";
    an age criterion adds "FMI age unknown"), plus the absent fields from
    section 1.
- **When the count is under 5**, the card does not stop at "<5". It lists
  the cheapest way to loosen the cohort, computed from the funnel: which
  single criterion, if dropped or widened, brings the count back above the
  floor (for example "drop PD-L1 TPS ≥ 50 → 6"). These are ordinary cohort
  queries, so they need no new privacy review. A suggestion is shown only if
  its count is at least 5, at least 5 above the current cohort's raw count,
  and not 1 to 4 away from a shown funnel step or equal to a hidden one;
  otherwise it could reveal a count the funnel's delta rule hid.
  Phase 1 offers "drop" only.

**Top bar.**

- *Versions*: every change makes a new version (v1, v2, …) in local storage.
- *Compare*: two to four saved definitions side by side, with the same
  cards and accrual on one axis. For example, KRAS G12C alone compared with
  G12C plus PD-L1-high.
- *Feasibility statement*: generates the grant paragraph from the definition
  and the floored counts, including the data notes. Example:
  "Between 2023 and 2026 the UCCC sequenced 120 NSCLC patients, of whom 8
  carried KRAS G12C (about 2 a year). Counts are de-identified patients from
  Caris and FMI reports; demographics beyond sex are not available, and
  treatment and outcome data are not linked."
- *Request data* (phase 2 of `COHORT_TOOL.md`): an email to the data
  steward with the definition JSON, as the entry point to the PHI path
  (#16).

### 3.4 The assistant

The chat is a guide, not a second query engine. Its only tools are the same
endpoints the page uses, so it cannot see more than a user clicking could.

| Tool | Endpoint | Purpose |
|---|---|---|
| `search_vocabulary(text)` | `GET /api/options?q=` | map "HER2-low", "dMMR", "TROP2" to vocabulary values; returns floored counts |
| `count(definition)` | `POST /api/cohort` | the funnel, cards and breakdowns |
| `pivot(definition, rows, cols)` | `POST /api/pivot` | cross-tabs |
| `data_notes(definition)` | part of the `/api/cohort` response | coverage and caveats to quote |
| `propose(definition)` | client-side | sends a definition to the page; the user clicks Apply |

How a conversation goes (question 9):

```
User:  I'm planning a zolbetuximab + pembrolizumab study in upper GI.
       How many patients would be both CLDN18-positive and PD-L1 CPS ≥ 10?
Asst:  Upper GI here means gastric, GEJ and esophageal cancer (OncoTree STAD, GEJ, ESCA).
       CLDN18 and PD-L1 CPS come from Caris IHC only, so FMI patients cannot qualify.
       Should I restrict to Caris-tested patients so the percentage is honest?   [Yes] [No]
User:  Yes.
Asst:  Of 80 patients with both stains: 10 are CLDN18+ and CPS ≥ 10, 30 CLDN18+ only,
       10 CPS ≥ 10 only. The overlap is small; a CLDN18+ arm alone would have 40.
       [Apply definition] [Show the 2×2 pivot] [Write feasibility paragraph]
```

Behaviour:

- It **asks before assuming** whenever the vocabulary is ambiguous (several
  OncoTree codes, HER2 spellings, "pathogenic" tiers) or a criterion's
  coverage is partial. It tells the user what got dropped.
- It **never states a number the API did not return.** Numbers in its
  replies are filled in from tool results. A test pins that every number
  in a reply appears in that turn's tool output.
- It ends each turn with a proposed definition the user can apply, so the
  builder stays the source of truth and the chat stays optional.
- It refuses questions the data cannot answer (survival, response, stage,
  race) and says which field is missing, instead of approximating.

Where it runs: an `/api/chat` route in `cohort_api.py`. Tool calls run
server-side, so the model key stays on the host (GCP Secret Manager). The
model provider receives the user's prompt and floored aggregate counts, never
row-level data. Each turn goes into the existing audit log with the user's
email. Whether sending floored counts to a model provider fits the DUAs is
open question 2.

### 3.5 API changes

| Endpoint | Change |
|---|---|
| `POST /api/cohort` | Body is the cohort definition. Response: `funnel[]`, `patients`, `reports`, `denominator`, `by_year`, the breakdowns, `notes[]`, `loosen[]`. All counts pass through the existing `suppress()`. `GET` with the phase 1 parameters is kept until `cohort.md` is removed, then deleted. |
| `POST /api/pivot` | Definition plus `rows` and `cols`. Two-way secondary suppression. |
| `GET /api/options` | Adds the vocabularies for the new kinds, each floored as today, with `?q=` typeahead. |
| `POST /api/chat` | Phase 3. Streams; tool calls run in-process. |

### 3.6 Privacy additions

The phase 1 controls in `COHORT_TOOL.md` stay as they are. New exposure:

| New capability | Risk | Control |
|---|---|---|
| `exclude` / `tested_negative` | A ∧ ¬B is the difference of two allowed queries, A and A ∧ B. Shown exactly, it reveals A ∧ B even when that is under 5. | Compute A ∧ ¬B, then return it only if A ∧ B is 0 or at least 5. Otherwise return "<5" for A ∧ B and suppress A ∧ ¬B as well. |
| Funnel | Consecutive steps difference to the patients removed at each step. | Apply the floor to the step deltas as well as to the step counts. |
| Pivot | A cell can be recovered from row and column totals. | Secondary suppression along both axes (iterate until no row or column has exactly one hidden cell). |
| Numeric thresholds | A sliding cut point can isolate one patient. | Fixed cut points only. |
| Multi-select population (OR) | Adding one tumor type to a list exposes that type's own small count by subtraction. In the prototype, KRAS G12C since 2023 is 8 in NSCLC and 9 in NSCLC or pancreas, so pancreas contributes about 1. The phase 1 API has the same exposure through repeated `disease`. The vocabulary floor only removes tumor types with fewer than 5 patients overall, not ones whose count inside a cohort is small. | Open: apply the A ∧ ¬B rule to unions (show {A, B} only if {B} alone is 0 or at least 5 in the same cohort), or accept the risk under the audit log, as `COHORT_TOOL.md` does for differencing today. |
| Breakdown cell against its denominator | The cell is nested in the population count, so both shown give the patients with that value who miss the criteria (questions 4 and 20 are this ratio). | Accepted under the audit log, like differencing across queries. Everything else in one result is closed under subtraction. |
| Pivot labels from `sub`/`val` axes | They are vendor free text (protein change, fusion partner, therapy name) that the vocabulary floor keeps out. | A label held by fewer than 5 cohort patients becomes `other`; `key` axes are vocabulary values the caller chose. |
| Vocabulary counts | Any shown count lets a nested list (a parent and its children, organ and OncoTree code) give back a floored-out value by subtraction. | No counts are returned; the floor decides which values appear and counts only rank search. |
| `loosen[]` suggestions | Each suggestion is itself a count. | Each one is an ordinary floored cohort query and is logged like any other. |
| Chat | Prompts and counts leave the host. | Only floored counts; audit log; open question 2. |

## 4. Phases

| Phase | Scope | Unlocks |
|---|---|---|
| 0, data readiness | Significance tier in `unified.variant`; HER2 call normalisation (#22); `consequence` case; flag partial years; hold viral calls | correct counts for every question |
| 1, mart and builder | `sql/mart.sql`; `POST /api/cohort` with include criteria of every kind except sequence; funnel; pivot; Discover page with builder, cards, accrual, breakdown, pivot and data notes; versions and share link | questions 1–9, 12, 13, 15, 16, 20 |
| 2, exclusion and order | `exclude`, `tested_negative`, report scope, `sequence`, `data` kind, the privacy additions in 3.6, compare, feasibility statement, request data | questions 10, 11, 14, 17, 18 |
| 3, assistant | `/api/chat`, the tool set, behaviour tests | the guided path for every question |

The twenty questions are the acceptance suite. Each phase is done when its
questions can be answered on the page in a few clicks. For phase 3 they
become a scripted evaluation: each question goes to the assistant, and the
definition it proposes must match a hand-written one.

## 5. Open questions for Sean

1. **Significance tiers.** Decided in #32: Caris "Mutated, Unclassified" and
   FMI status `unknown` with `is_vus = false` are `unclassified`, outside the
   default pathogenic filter and opt-in. This changes counts on every
   alteration question.
2. **Assistant and the DUAs.** May floored aggregate counts and researchers'
   prompts go to an external model provider? If not, the assistant needs a
   model hosted on campus, or it waits.
3. **Exclusion.** Ship `exclude` and `tested_negative` with the
   differencing rule in 3.6, or keep the tool include-only as
   `COHORT_TOOL.md` phase 3 proposed?
4. **Cut points.** Are TMB 10/16/20, CPS 1/10/20, TPS 1/50, expression
   percentile 50/75/90 and purity 20/30/50 the right fixed thresholds?
5. **Viral calls.** Who can review the FMI HHV-4 and HPV-16 calls in prostate
   before a viral criterion is offered?
