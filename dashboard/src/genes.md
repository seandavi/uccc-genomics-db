---
title: Genes
---

# Gene alteration frequency

```js
const s = FileAttachment("data/summary.json").json();
```

```js
import {altColor, vendorLabel} from "./components/theme.js";
const sumBy = (rows, key) => d3.rollups(rows, (v) => d3.sum(v, (d) => d.n), (d) => d[key]).sort((a, b) => b[1] - a[1]).map((d) => d[0]);
```

```js
const vendor = view(Inputs.radio(["caris", "fmi"], {label: "Vendor", value: "caris", format: (v) => vendorLabel[v] ?? v}));
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
// Exact protein changes (pathogenic only) for the chosen gene, in the disease chosen at the top.
// The loader pools changes under the floor into one "other" bucket, which sorts last.
const OTHER = `other (each < ${s.meta.min_cell})`;
const variants = s.gene_variant
  .filter((d) => d.vendor === vendor && d.gene === gene && d.disease === disease)
  .map((d) => ({...d, pct: d.n / denom}))
  .sort((a, b) => (a.aa === OTHER) - (b.aa === OTHER) || b.n - a.n);
const aaChoices = ["All alterations", ...s.gene_variant
  .filter((d) => d.vendor === vendor && d.gene === gene && d.disease === "All diseases" && d.aa !== OTHER)
  .sort((a, b) => b.n - a.n).map((d) => d.aa)];
```

<div class="card">
  <h2>${gene} exact alterations: ${disease}, ${vendor}</h2>
  <h3>Reports with each pathogenic/likely protein change (VUS excluded). Changes with fewer than ${s.meta.min_cell} reports are pooled into "other". Amplifications and fusions are not shown here.</h3>
  ${variants.length ? resize((width) => Plot.plot({
    width, height: 22 * variants.length + 70, marginLeft: 120,
    x: {grid: true, label: "reports", domain: [0, Math.max(...variants.map((d) => d.n)) * 1.2]},
    y: {label: null, domain: variants.map((d) => d.aa)},
    marks: [
      Plot.barX(variants, {x: "n", y: "aa", fill: (d) => d.aa === OTHER ? "#bbb" : altColor.range[0], tip: true}),
      Plot.text(variants, {x: "n", y: "aa", text: (d) => `${d.n} (${(d.pct * 100).toFixed(1)}%)`, dx: 6, textAnchor: "start", fill: "currentColor", fontSize: 11}),
      Plot.ruleX([0])
    ]
  })) : html`<div class="muted" style="padding: 2rem 0;">No ${gene} protein change reaches ${s.meta.min_cell} reports in ${disease}.</div>`}
</div>

```js
const aa = view(Inputs.select(aaChoices, {label: "Alteration"}));
```

```js
const byDisease = (() => {
  const den = new Map(s.denom.filter((d) => d.vendor === vendor).map((d) => [d.disease, d.n]));
  const rows = aa === "All alterations"
    ? s.gene_alt.filter((d) => d.vendor === vendor && d.gene === gene && (showVus || d.alt_type !== "VUS"))
    : s.gene_variant.filter((d) => d.vendor === vendor && d.gene === gene && d.aa === aa).map((d) => ({...d, alt_type: "pathogenic/likely"}));
  return rows.filter((d) => d.disease !== "All diseases").map((d) => ({...d, pct: d.n / den.get(d.disease)}));
})();
const across = aa === "All alterations" ? `a ${gene} alteration` : `${gene} ${aa}`;
```

<div class="card">
  <h2>${across} across diseases, ${vendor}</h2>
  <h3>Share of each disease's reports carrying ${across}. Diseases under ${s.meta.min_cell} reports are omitted.</h3>
  ${byDisease.length ? resize((width) => Plot.plot({
    width, height: 24 * new Set(byDisease.map((d) => d.disease)).size + 70, marginLeft: 260, color: altColor,
    x: {percent: true, grid: true, label: "% of reports"},
    y: {label: null},
    marks: [Plot.barX(byDisease, {x: "pct", y: "disease", fill: "alt_type", sort: {y: "-x"}, tip: true}), Plot.ruleX([0])]
  })) : html`<div class="muted" style="padding: 2rem 0;">No disease has ${s.meta.min_cell}+ reports with ${across}.</div>`}
</div>
