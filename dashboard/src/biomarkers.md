---
title: Biomarkers
---

# TMB, MSI, PD-L1, LOH and allele fractions

```js
const s = FileAttachment("data/summary.json").json();
```

```js
import {vendorColor, vendorLabel} from "./components/theme.js";
const callColor = {domain: ["high", "intermediate", "low", "stable", "indeterminate"], range: ["#eb6834", "#eda100", "#2a78d6", "#2a78d6", "#9a9a9a"], legend: true};
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Tumor mutational burden</h2>
    <h3>mut/Mb in 2-unit bins, 50+ pooled. Dashed line at 10 mut/Mb.</h3>
    ${resize((width) => Plot.plot({
      width, height: 340, color: vendorColor, fy: {label: null},
      x: {label: "TMB (mut/Mb)"}, y: {grid: true, label: "reports"},
      marks: [
        Plot.rectY(s.tmb_hist, {x1: "bin", x2: (d) => d.bin + 2, y: "n", fill: "vendor", fy: "vendor", insetLeft: 1, tip: true}),
        Plot.ruleX([10], {strokeDasharray: "4 4", stroke: "currentColor", strokeOpacity: 0.5}),
        Plot.ruleY([0])
      ]
    }))}
  </div>
  <div class="card">
    <h2>Allele fraction of pathogenic/likely variants</h2>
    <h3>By assay class. Liquid assays run low, as expected.</h3>
    ${resize((width) => Plot.plot({
      width, height: 340, color: vendorColor, fx: {label: null},
      x: {label: "VAF", percent: true}, y: {grid: true, label: "variants"},
      marks: [
        Plot.rectY(s.vaf_hist, {x1: "bin", x2: (d) => d.bin + 0.05, y: "n", fill: "vendor", fx: "assay_class", insetLeft: 1, tip: true}),
        Plot.ruleY([0])
      ]
    }))}
  </div>
</div>

```js
const vendor = view(Inputs.radio(["caris", "fmi"], {label: "Vendor", value: "caris", format: (v) => vendorLabel[v] ?? v}));
const marker = view(Inputs.radio(["TMB", "MSI"], {label: "Marker", value: "TMB"}));
```

```js
const calls = s.biomarker_call.filter((d) => d.vendor === vendor && d.name === marker && d.disease !== "All diseases");
const diseaseOrder = d3.rollups(calls, (v) => d3.sum(v, (d) => d.n), (d) => d.disease).sort((a, b) => b[1] - a[1]).map((d) => d[0]);
```

<div class="card">
  <h2>${marker} call by disease, ${vendor}</h2>
  <h3>Vendor calls normalised to high / intermediate / low / stable / indeterminate. Diseases ordered by tested reports.</h3>
  ${resize((width) => Plot.plot({
    width, height: 24 * diseaseOrder.length + 70, marginLeft: 260,
    color: {...callColor, domain: callColor.domain.filter((c) => calls.some((d) => d.call_norm === c)), range: callColor.range.filter((_, i) => calls.some((d) => d.call_norm === callColor.domain[i]))},
    x: {percent: true, label: "% of tested reports"},
    y: {domain: diseaseOrder, label: null},
    marks: [Plot.barX(calls, {x: "n", y: "disease", fill: "call_norm", offset: "normalize", order: callColor.domain, tip: true, insetTop: 1, insetBottom: 1}), Plot.ruleX([0])]
  }))}
</div>

```js
// Caris IHC beyond PD-L1. Calls are shown exactly as Caris reports them: HER2 in breast uses
// low / null / ultralow, elsewhere positive / negative / equivocal, and those are not the same scale.
const ihcTotals = d3.rollups(s.ihc.filter((d) => d.disease === "All diseases"), (v) => d3.sum(v, (d) => d.n), (d) => d.name).sort((a, b) => b[1] - a[1]);
const ihcMarker = view(Inputs.select(ihcTotals.map((d) => d[0]), {label: "IHC marker", value: "ERBB2 (Her2/Neu)", format: (m) => `${m} (${ihcTotals.find((d) => d[0] === m)[1].toLocaleString("en-US")})`}));
```

```js
const ihc = s.ihc.filter((d) => d.name === ihcMarker && d.disease !== "All diseases");
const ihcDiseases = d3.rollups(ihc, (v) => d3.sum(v, (d) => d.n), (d) => d.disease).sort((a, b) => b[1] - a[1]).map((d) => d[0]);
const ihcCalls = d3.rollups(s.ihc.filter((d) => d.name === ihcMarker && d.disease === "All diseases"), (v) => d3.sum(v, (d) => d.n), (d) => d.call).sort((a, b) => b[1] - a[1]).map((d) => d[0]);
```

<div class="card">
  <h2>${ihcMarker} immunohistochemistry by disease (Caris)</h2>
  <h3>Calls as reported by Caris, not harmonised across diseases. Foundation Medicine reports carry no IHC. Disease × call cells under ${s.meta.min_cell} reports are omitted, so bars can sum low.</h3>
  ${ihc.length ? resize((width) => Plot.plot({
    width, height: 24 * ihcDiseases.length + 70, marginLeft: 260,
    color: {domain: ihcCalls, scheme: "observable10", legend: true},
    x: {grid: true, label: "reports"},
    y: {domain: ihcDiseases, label: null},
    marks: [Plot.barX(ihc, {x: "n", y: "disease", fill: "call", order: ihcCalls, tip: true, insetTop: 1, insetBottom: 1}), Plot.ruleX([0])]
  })) : html`<div class="muted" style="padding: 2rem 0;">No disease has ${s.meta.min_cell}+ ${ihcMarker} results.</div>`}
</div>

<div class="grid grid-cols-2">
  <div class="card">
    <h2>PD-L1 immunohistochemistry (Caris)</h2>
    <h3>By scoring system reported</h3>
    ${resize((width) => Plot.plot({
      width, height: 220, marginLeft: 90,
      color: {domain: ["Positive", "Negative", "Other", "Insufficient Tumor"], range: ["#eb6834", "#2a78d6", "#9a9a9a", "#c3c2b7"], legend: true},
      x: {grid: true, label: "reports"}, y: {label: null},
      marks: [Plot.barX(s.pdl1, {x: "n", y: "unit", fill: "call", tip: true, insetTop: 1, insetBottom: 1}), Plot.ruleX([0])]
    }))}
  </div>
  <div class="card">
    <h2>Loss of heterozygosity (Caris)</h2>
    <h3>Percent genome LOH in 5-point bins, 50+ pooled</h3>
    ${resize((width) => Plot.plot({
      width, height: 220,
      x: {label: "% LOH"}, y: {grid: true, label: "reports"},
      marks: [Plot.rectY(s.loh_hist, {x1: "bin", x2: (d) => d.bin + 5, y: "n", fill: "#2a78d6", insetLeft: 1, tip: true}), Plot.ruleY([0])]
    }))}
  </div>
</div>
