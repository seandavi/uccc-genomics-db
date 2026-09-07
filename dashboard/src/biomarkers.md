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
