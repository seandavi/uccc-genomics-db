---
title: Overview
---

# UCCC vendor genomics

```js
const s = FileAttachment("data/summary.json").json();
```

```js
import {vendorColor, fmt} from "./components/theme.js";
```

Caris and Foundation Medicine NGS reports as one de-identified database. Site built ${s.meta.built_at.replace("T", " ")} from the latest daily load.

<div class="grid grid-cols-4">
  <div class="card"><h2>Reports</h2><span class="big">${fmt(s.meta.n_reports)}</span></div>
  <div class="card"><h2>Patients</h2><span class="big">${fmt(s.meta.n_patients)}</span><br><span class="muted">${fmt(s.meta.n_multi_vendor)} tested by both vendors</span></div>
  <div class="card"><h2>Short variants</h2><span class="big">${fmt(s.meta.n_variants)}</span><br><span class="muted">incl. VUS</span></div>
  <div class="card"><h2>Copy number · fusions</h2><span class="big">${fmt(s.meta.n_cna)}</span> · <span class="big">${fmt(s.meta.n_fusions)}</span></div>
</div>

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Reports by collection year</h2>
    <h3>Dates are shifted per patient by up to ±6 months, so the last bar runs past today and edge years are partial</h3>
    ${resize((width) => Plot.plot({
      width, height: 320, color: vendorColor,
      x: {tickFormat: String, tickRotate: -45, label: null},
      y: {grid: true, label: "reports"},
      marks: [Plot.barY(s.reports_by_year, {x: "year", y: "n", fill: "vendor", tip: true}), Plot.ruleY([0])]
    }))}
  </div>
  <div class="card">
    <h2>Assays</h2>
    <h3>Tissue, liquid and heme panels across both vendors</h3>
    ${resize((width) => Plot.plot({
      width, height: 320, marginLeft: 230, color: vendorColor,
      x: {grid: true, label: "reports"},
      y: {label: null},
      marks: [Plot.barX(s.assays, {x: "n", y: "assay_name", fill: "vendor", sort: {y: "-x"}, tip: true}), Plot.ruleX([0])]
    }))}
  </div>
</div>

```js
function diseaseBars(vendor, i) {
  return resize((width) => Plot.plot({
    width, height: 560, marginLeft: 260,
    x: {grid: true, label: "reports"},
    y: {label: null},
    marks: [
      Plot.barX(s.disease.filter((d) => d.vendor === vendor), {x: "n", y: "disease", fill: vendorColor.range[i], sort: {y: "-x"}, tip: true}),
      Plot.ruleX([0])
    ]
  }));
}
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Caris: top diseases</h2>
    <h3>OncoTree name where the crosswalk maps the Caris lineage, otherwise the lineage as reported</h3>
    ${diseaseBars("caris", 0)}
  </div>
  <div class="card">
    <h2>Foundation Medicine: top diseases</h2>
    <h3>OncoTree name where the crosswalk maps the FMI disease term, otherwise the term as reported</h3>
    ${diseaseBars("fmi", 1)}
  </div>
</div>
