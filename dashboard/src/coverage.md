---
title: Coverage & quality
---

# What was tested, and data quality

```js
const s = FileAttachment("data/summary.json").json();
```

```js
const vendorColor = {domain: ["caris", "fmi"], range: ["#2a78d6", "#eb6834"], legend: true};
const genesPerPanel = new Map(d3.rollups(s.coverage, (v) => v.length, (d) => d.panel));
const panels = s.panels.map((d) => ({...d, genes_with_evidence: genesPerPanel.get(d.panel) ?? 0}));
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Panels</h2>
    <h3>Caris panel from its wild-type records; FMI panel gene lists are not loaded, so the assay name stands in and "genes with evidence" counts only genes ever reported altered or pertinent-negative.</h3>
    ${Inputs.table(panels, {columns: ["vendor", "panel", "n", "genes_with_evidence"], header: {n: "reports", genes_with_evidence: "genes with evidence"}, sort: "n", reverse: true})}
  </div>
  <div class="card">
    <h2>Report status</h2>
    ${resize((width) => Plot.plot({
      width, height: 260, marginLeft: 90, color: vendorColor,
      x: {grid: true, label: "reports"}, y: {label: null},
      marks: [Plot.barX(s.status, {x: "n", y: "status", fill: "vendor", sort: {y: "-x"}, tip: true}), Plot.ruleX([0])]
    }))}
  </div>
</div>

```js
const search = view(Inputs.search(s.coverage, {placeholder: "Search a gene, e.g. KRAS", columns: ["gene", "panel"]}));
```

<div class="card">
  <h2>Gene coverage</h2>
  <h3>Reports on which the gene was called wild-type, pertinent-negative, or altered. Absence from a panel means no evidence either way, not "not tested".</h3>
  ${Inputs.table(search, {columns: ["vendor", "panel", "gene", "n"], header: {n: "reports with evidence"}, sort: "n", reverse: true, rows: 20})}
</div>

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Tumor purity</h2>
    <h3>Percent tumor nuclei or vendor purity estimate, 10-point bins</h3>
    ${resize((width) => Plot.plot({
      width, height: 260, color: vendorColor, fy: {label: null},
      x: {label: "% tumor"}, y: {grid: true, label: "reports"},
      marks: [Plot.rectY(s.purity_hist, {x1: "bin", x2: (d) => d.bin + 10, y: "n", fill: "vendor", fy: "vendor", insetLeft: 1, tip: true}), Plot.ruleY([0])]
    }))}
  </div>
  <div class="card">
    <h2>Known gaps</h2>
    ${Inputs.table(s.quality, {columns: ["item", "n"], header: {item: "", n: "count"}, sort: "n", reverse: true})}
  </div>
</div>
