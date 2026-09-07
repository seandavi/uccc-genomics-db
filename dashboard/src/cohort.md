---
title: Cohort exploration
---

# Cohort exploration and feasibility

```js
import {vendorColor, altColor, assayColor, fmt, pct, vendorLabel} from "./components/theme.js";
import {cohort} from "./components/cohort.js";
const data = FileAttachment("data/cohort.json").json();
```

```js
const {min_year, max_year} = data.meta;
const defaultEnd = max_year - 2;  // the last two years are still accruing, and dates are shifted forward up to 6 months
const selectedGenes = view(Inputs.select(data.genes.map((d) => d.gene), {multiple: 6, label: "Genes", value: []}));
const selectedDiseases = view(Inputs.select(data.diseases.map((d) => d.disease), {multiple: 6, label: "Diseases", value: []}));
```

<p class="muted small">Both lists are sorted by report count. Leave a list empty for any gene / all diseases; select several for OR.</p>

```js
const startYear = view(Inputs.range([min_year, max_year], {step: 1, value: defaultEnd - 7, label: "Start year"}));
const endYear = view(Inputs.range([min_year, max_year], {step: 1, value: defaultEnd, label: "End year"}));
const selectedVendor = view(Inputs.radio(["All", "caris", "fmi"], {label: "Vendor", value: "All", format: (v) => vendorLabel[v] ?? v}));
const includeVus = view(Inputs.toggle({label: "Include VUS", value: false}));
```

```js
const c = cohort(data, {genes: selectedGenes, diseases: selectedDiseases, vendor: selectedVendor, years: [startYear, endYear], includeVus});
const geneLabel = selectedGenes.length ? selectedGenes.join(", ") : "any gene";
const diseaseLabel = selectedDiseases.length ? selectedDiseases.join(", ") : "all diseases";
const yearsLabel = `${c.y0}–${c.y1}`;
const empty = (msg) => html`<div class="muted" style="padding: 2rem 0;">${msg}</div>`;
```

<div class="grid grid-cols-4">
  <div class="card">
    <h2>Matching reports, all years</h2>
    <span class="big">${fmt(c.matching)}</span>
    <br><span class="muted">${c.hasGenes ? `${pct(c.prevalence)} of ${fmt(c.testedAll)} tested` : `${fmt(c.patientsAll)} patients`}, ${diseaseLabel}</span>
  </div>
  <div class="card">
    <h2>Tested in window</h2>
    <span class="big">${fmt(c.testedWindow)}</span>
    <br><span class="muted">${fmt(Math.round(c.testedWindow / c.span))} reports / yr, ${yearsLabel}</span>
  </div>
  <div class="card">
    <h2>Expected accrual</h2>
    <span class="big">${c.accrual.toFixed(1)}</span>
    <br><span class="muted">${c.hasGenes ? "matching reports / yr: prevalence × tested / yr" : "reports / yr in window"}</span>
  </div>
  <div class="card" style="background: ${c.tier.bg}; color: ${c.tier.fg};">
    <h2 style="color: inherit;">Feasibility</h2>
    <span class="big">${c.tier.name}</span>
    <br><span style="font-size: 0.85em;">${c.tier.desc}</span>
  </div>
</div>

${c.hasGenes && selectedGenes.length > 1 ? html`<p class="muted small">A report altered in more than one selected gene is counted once per gene, so the matching count is an upper bound for OR.</p>` : ""}

<div class="grid grid-cols-2">
  <div class="card">
    <h2>${c.hasGenes ? `Observed ${geneLabel} alterations by year` : "Tested reports by year"}</h2>
    <h3>${c.hasGenes ? `Only year × vendor cells with ${data.meta.min_cell}+ reports survive suppression, so rare alterations show low or empty here; the all-years count above is the reliable number.` : `Stacked by vendor, ${diseaseLabel}. Collection year, shifted per patient by up to ±6 months.`}</h3>
    ${(() => {
      const rows = c.hasGenes ? c.annualGene : c.annualDenoms;
      if (!rows.length) return empty(c.hasGenes ? "No year has enough matching reports to show." : "No tested reports in this window.");
      return resize((width) => Plot.plot({
        width, height: 300, color: vendorColor,
        x: {type: "band", domain: Array.from({length: c.span}, (_, i) => c.y0 + i), tickFormat: String, tickRotate: -45, label: null},
        y: {grid: true, label: "reports"},
        marks: [Plot.barY(rows, {x: "year", y: "n", fill: "vendor", tip: true}), Plot.ruleY([0])]
      }));
    })()}
  </div>
  <div class="card">
    <h2>Assay class in window</h2>
    <h3>Tissue, liquid and heme reports, ${diseaseLabel}, ${yearsLabel}</h3>
    ${c.modality.length === 0 ? empty("No tested reports in this window.") : resize((width) => Plot.plot({
      width, height: 300, marginLeft: 60, color: assayColor,
      x: {grid: true, label: "reports", domain: [0, Math.max(...c.modality.map((d) => d.n)) * 1.2]},
      y: {label: null, domain: c.modality.map((d) => d.assay_class)},
      marks: [
        Plot.barX(c.modality, {x: "n", y: "assay_class", fill: "assay_class", tip: true}),
        Plot.text(c.modality, {x: "n", y: "assay_class", text: (d) => `${fmt(d.n)} (${pct(d.pct)})`, dx: 6, textAnchor: "start", fill: "currentColor"}),
        Plot.ruleX([0])
      ]
    }))}
  </div>
</div>

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Alteration classes, ${geneLabel}</h2>
    <h3>Reports per class, all years, ${diseaseLabel}. A report with two classes in one gene counts once per class.</h3>
    ${c.altTypes.length === 0 ? empty("No class has enough reports to show.") : resize((width) => Plot.plot({
      width, height: 260, marginLeft: 120, color: altColor,
      x: {grid: true, label: "reports", domain: [0, Math.max(...c.altTypes.map((d) => d.n)) * 1.2]},
      y: {label: null, domain: c.altTypes.map((d) => d.alt_type)},
      marks: [
        Plot.barX(c.altTypes, {x: "n", y: "alt_type", fill: "alt_type", tip: true}),
        Plot.text(c.altTypes, {x: "n", y: "alt_type", text: (d) => fmt(d.n), dx: 6, textAnchor: "start", fill: "currentColor"}),
        Plot.ruleX([0])
      ]
    }))}
  </div>
  <div class="card">
    <h2>${c.hasGenes ? `Co-altered with ${geneLabel}` : `Most altered genes, ${diseaseLabel}`}</h2>
    <h3>${c.hasGenes ? "Reports carrying both genes, all diseases and years (per-disease pairs are too sparse to publish)." : "Reports with ≥ 1 alteration in the gene, all years."}</h3>
    ${(() => {
      const rows = c.hasGenes ? c.coAltered : c.topGenes;
      if (!rows.length) return empty("Nothing meets the small-cell floor.");
      return resize((width) => Plot.plot({
        width, height: 22 * rows.length + 60, marginLeft: 80,
        x: {grid: true, label: c.hasGenes ? "co-altered reports" : "reports", domain: [0, Math.max(...rows.map((d) => d.n)) * 1.2]},
        y: {label: null, domain: rows.map((d) => d.gene)},
        marks: [
          Plot.barX(rows, {x: "n", y: "gene", fill: vendorColor.range[0], tip: true}),
          Plot.text(rows, {x: "n", y: "gene", text: (d) => c.hasGenes ? fmt(d.n) : `${fmt(d.n)} (${pct(d.pct)})`, dx: 6, textAnchor: "start", fill: "currentColor", fontSize: 11}),
          Plot.ruleX([0])
        ]
      }));
    })()}
  </div>
</div>

<div class="card">
  <h2>By year, ${yearsLabel}</h2>
  <h3>Tested reports by vendor and assay class${c.hasGenes ? `, and observed ${geneLabel} alterations where the year × vendor cell survives suppression` : ""}. Cells under ${data.meta.min_cell} are omitted, so rows can sum low.</h3>
  ${Inputs.table(c.table, {
    columns: c.hasGenes ? ["year", "tested", "observed", "share", "caris", "fmi", "tissue", "liquid", "heme"] : ["year", "tested", "caris", "fmi", "tissue", "liquid", "heme"],
    header: {year: "Year", tested: "Tested", observed: "Observed", share: "Share", caris: "Caris", fmi: "FMI", tissue: "Tissue", liquid: "Liquid", heme: "Heme"},
    format: {year: String, share: (d) => pct(d)},
    sort: "year", reverse: true, rows: 25
  })}
</div>

<div class="card">
  <h2>How to read this page</h2>
  <ul>
    <li><strong>Matching reports</strong> counts reports with at least one qualifying alteration in a selected gene, across all years, because year-level cells for rare alterations fall under the small-cell floor.</li>
    <li><strong>Expected accrual</strong> applies that all-years prevalence to the testing volume in the selected window. It is an estimate, not a count.</li>
    <li><strong>Feasibility tiers</strong>: ≥ 50 matching reports/yr high, 10–49 moderate, under 10 pilot. Thresholds are a rule of thumb for institutional single-site accrual.</li>
    <li>Reports, not patients: a patient tested twice counts twice. Patient counts are shown where they are exact.</li>
  </ul>
</div>
