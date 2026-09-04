---
title: Genes
---

# Gene alteration frequency

```js
const s = FileAttachment("data/summary.json").json();
```

```js
const altColor = {
  domain: ["pathogenic/likely", "amplification", "loss", "fusion", "VUS"],
  range: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
  legend: true
};
const sumBy = (rows, key) => d3.rollups(rows, (v) => d3.sum(v, (d) => d.n), (d) => d[key]).sort((a, b) => b[1] - a[1]).map((d) => d[0]);
```

```js
const vendor = view(Inputs.radio(["caris", "fmi"], {label: "Vendor", value: "caris"}));
```

```js
const diseases = ["All diseases", ...s.disease.filter((d) => d.vendor === vendor).map((d) => d.disease)];
const disease = view(Inputs.select(diseases, {label: "Disease"}));
const showVus = view(Inputs.toggle({label: "Include VUS", value: false}));
```

```js
const denom = s.denom.find((d) => d.vendor === vendor && d.disease === disease)?.n ?? 0;
const sel = s.gene_alt
  .filter((d) => d.vendor === vendor && d.disease === disease && (showVus || d.alt_type !== "VUS"))
  .map((d) => ({...d, pct: d.n / denom}));
const geneOrder = sumBy(sel, "gene").slice(0, 40);
const overallOrder = sumBy(s.gene_alt.filter((d) => d.vendor === vendor && d.disease === "All diseases" && d.alt_type !== "VUS"), "gene");
```

<div class="card">
  <h2>Top ${geneOrder.length} genes: ${disease}, ${vendor}</h2>
  <h3>Share of ${denom.toLocaleString("en-US")} reports with each alteration type. A report with two types in one gene counts once per type. Cells under ${s.meta.min_cell} reports are omitted.</h3>
  ${resize((width) => Plot.plot({
    width, height: 22 * geneOrder.length + 70, marginLeft: 80, color: altColor,
    x: {percent: true, grid: true, label: "% of reports"},
    y: {domain: geneOrder, label: null},
    marks: [
      Plot.barX(sel.filter((d) => geneOrder.includes(d.gene)), {x: "pct", y: "gene", fill: "alt_type", tip: true, insetTop: 1, insetBottom: 1}),
      Plot.ruleX([0])
    ]
  }))}
</div>

```js
const heat = (() => {
  const genes = overallOrder.slice(0, 20);
  const dis = s.disease.filter((d) => d.vendor === vendor).slice(0, 15).map((d) => d.disease);
  const den = new Map(s.denom.filter((d) => d.vendor === vendor).map((d) => [d.disease, d.n]));
  const rows = s.gene_alt.filter((d) => d.vendor === vendor && d.alt_type !== "VUS" && genes.includes(d.gene) && dis.includes(d.disease));
  return d3.rollups(rows, (v) => d3.sum(v, (d) => d.n), (d) => d.gene, (d) => d.disease)
    .flatMap(([gene, arr]) => arr.map(([disease, n]) => ({gene, disease, n, pct: n / den.get(disease)})));
})();
```

<div class="card">
  <h2>Pathogenic/likely alterations by disease, ${vendor}</h2>
  <h3>Top 20 genes by top 15 diseases. Blank means fewer than ${s.meta.min_cell} reports.</h3>
  ${resize((width) => Plot.plot({
    width, height: 560, marginLeft: 130, marginBottom: 150,
    x: {label: null, tickRotate: -35, tickFormat: (d) => d.length > 22 ? d.slice(0, 20) + "…" : d, domain: s.disease.filter((d) => d.vendor === vendor).slice(0, 15).map((d) => d.disease)},
    y: {label: null, domain: overallOrder.slice(0, 20)},
    color: {scheme: "blues", percent: true, label: "% of reports", legend: true},
    marks: [
      Plot.cell(heat, {x: "disease", y: "gene", fill: "pct", inset: 1, tip: true}),
      Plot.text(heat, {x: "disease", y: "gene", text: (d) => Math.round(d.pct * 100), fill: (d) => d.pct > 0.35 ? "white" : "black"})
    ]
  }))}
</div>

```js
const gene = view(Inputs.select(overallOrder, {label: "Gene"}));
```

```js
const byDisease = (() => {
  const den = new Map(s.denom.filter((d) => d.vendor === vendor).map((d) => [d.disease, d.n]));
  return s.gene_alt
    .filter((d) => d.vendor === vendor && d.gene === gene && d.disease !== "All diseases" && (showVus || d.alt_type !== "VUS"))
    .map((d) => ({...d, pct: d.n / den.get(d.disease)}));
})();
```

<div class="card">
  <h2>${gene} across diseases, ${vendor}</h2>
  <h3>Share of each disease's reports carrying a ${gene} alteration</h3>
  ${resize((width) => Plot.plot({
    width, height: 24 * new Set(byDisease.map((d) => d.disease)).size + 70, marginLeft: 260, color: altColor,
    x: {percent: true, grid: true, label: "% of reports"},
    y: {label: null},
    marks: [Plot.barX(byDisease, {x: "pct", y: "disease", fill: "alt_type", sort: {y: "-x"}, tip: true}), Plot.ruleX([0])]
  }))}
</div>
