---
title: Cohort exploration
---

# Cohort exploration

```js
import {vendorLabel, pct} from "./components/theme.js";
import {ORGAN_PRESETS, accrual, cohortQuery, fmtCount, organPreset, readQuery, tierFor} from "./components/cohort.js";
// Live counts from the cohort API on this host (dashboard/COHORT_TOOL.md), behind the same Access login.
const options = fetch("/api/options").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`options: HTTP ${r.status}`))));
```

```js
const init = readQuery(location.search, options);
const n = (d) => fmtCount(d, options.min_cell);
const preset = view(Inputs.radio(ORGAN_PRESETS, {label: "Organ group", value: null}));
```

```js
const organ = view(Inputs.select(options.organ, {multiple: 8, label: "Organ system", value: preset ? organPreset(preset, options.organ) : init.organ}));
const disease = view(Inputs.select(options.disease, {multiple: 8, label: "Disease", value: init.disease}));
```

<p class="muted small">Leave a list empty for any; select several for OR. Organ and disease combine with AND. The presets fill the organ list: solid tumors is every organ system except Blood/Bone Marrow; GI is esophagus/stomach, bowel, pancreas, biliary tract and liver.</p>

```js
const gene = view(Inputs.select(options.gene, {multiple: 6, label: "Genes", value: init.gene}));
```

```js
const aa = gene.length === 1 && options.aa[gene[0]]
  ? view(Inputs.select(options.aa[gene[0]], {multiple: 6, label: `${gene[0]} protein change`, value: init.aa}))
  : [];
const alt_class = gene.length ? view(Inputs.checkbox(options.alt_class, {label: "Alteration class", value: init.alt_class})) : [];
```

```js
const sex = view(Inputs.checkbox(options.sex, {label: "Sex", value: init.sex}));
const age = view(Inputs.checkbox(options.age, {label: "Age band", value: init.age}));
const vendor = view(Inputs.checkbox(options.vendor, {label: "Vendor", value: init.vendor, format: (v) => vendorLabel[v] ?? v}));
const assay_class = view(Inputs.checkbox(options.assay_class, {label: "Assay class", value: init.assay_class}));
const yearFrom = view(Inputs.range([options.year_min, options.year_max], {step: 1, value: init.years[0], label: "From year"}));
const yearTo = view(Inputs.range([options.year_min, options.year_max], {step: 1, value: init.years[1], label: "To year"}));
```

```js
const years = [Math.min(yearFrom, yearTo), Math.max(yearFrom, yearTo)];
const qs = cohortQuery({organ, disease, gene, aa, alt_class, sex, age, vendor, assay_class, years}, options);
// An empty checkbox group matches nobody; say so without asking the API.
const NONE = {patients: 0, reports: 0, tested: 0, by_year: [], by_disease: [], by_vendor_class: [], by_alt_class: [], by_sex: [], by_age: []};
const result = qs == null ? NONE : fetch(`/api/cohort?${qs}`).then(async (r) => {
  const body = await r.json();
  if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
  return body;
});
const link = `${location.origin}${location.pathname}${qs ? `?${qs}` : ""}`;
```

```js
const label = [
  gene.length ? `${gene.join(" or ")}${aa.length ? ` ${aa.join(" or ")}` : ""}` : "any alteration",
  organ.length ? organ.join(", ") : "", disease.length ? disease.join(", ") : "",
].filter(Boolean).join(" in ") || "all tested patients";
const yearsLabel = years[0] === options.year_min && years[1] === options.year_max ? "all years" : `${years[0]}–${years[1]}`;
const empty = (msg) => html`<div class="muted" style="padding: 2rem 0;">${msg}</div>`;
display(html`<p><a href="${link}">Link to this cohort</a> ${Inputs.button("Copy link", {reduce: () => navigator.clipboard.writeText(link)})}</p>`);
```

```js
if (qs == null) display(html`<div class="card">A checkbox group is empty, so no patient can match. Tick at least one value in each group.</div>`);
```

```js
const c = result;
const prevalence = c && c.patients != null && c.tested ? c.patients / c.tested : null;
const perYear = c && accrual(c.patients, years);
const tier = perYear == null ? null : tierFor(perYear);
```

<div class="grid grid-cols-4">
  <div class="card">
    <h2>Matching patients</h2>
    <span class="big">${n(c.patients)}</span>
    <br><span class="muted">${label}, ${yearsLabel}</span>
  </div>
  <div class="card">
    <h2>Prevalence</h2>
    <span class="big">${prevalence == null ? "–" : pct(prevalence)}</span>
    <br><span class="muted">of ${n(c.tested)} tested patients with the same non-gene filters</span>
  </div>
  <div class="card">
    <h2>Matching reports</h2>
    <span class="big">${n(c.reports)}</span>
    <br><span class="muted">a patient tested twice has two reports</span>
  </div>
  <div class="card" style="${tier ? `background: ${tier.bg}; color: ${tier.fg};` : ""}">
    <h2 style="color: inherit;">Accrual, ${perYear == null ? "–" : perYear.toFixed(1)} patients / yr</h2>
    <span class="big">${tier ? tier.name : "–"}</span>
    <br><span style="font-size: 0.85em;">${tier ? tier.desc : "Too few patients to publish."}</span>
  </div>
</div>

```js
const bars = (rows, {height, format = (d) => d, marginLeft = 160} = {}) => {
  if (!rows.length) return empty(c.patients == null ? "Hidden: the cohort is under the small-cell floor." : "Nothing to show.");
  const shown = rows.map((d) => ({...d, label: format(d), value: d.patients ?? 0}));
  return resize((width) => Plot.plot({
    width, height: height ?? 24 * rows.length + 40, marginLeft,
    x: {grid: true, label: "patients", domain: [0, Math.max(5, ...shown.map((d) => d.value)) * 1.2]},
    y: {label: null, domain: shown.map((d) => d.label)},
    marks: [
      Plot.barX(shown, {x: "value", y: "label", fill: "#2a78d6", tip: true}),
      Plot.text(shown, {x: "value", y: "label", text: (d) => n(d.patients), dx: 6, textAnchor: "start", fill: "currentColor"}),
      Plot.ruleX([0]),
    ],
  }));
};
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Patients by first qualifying year</h2>
    <h3>Each patient counts once, in the collection year of their first matching report. Years under ${options.min_cell} show "<${options.min_cell}"; if only one year would be hidden, the next-smallest is hidden too so it cannot be worked out from the total.</h3>
    ${c.by_year.length === 0 ? empty(c.patients == null ? "Hidden: the cohort is under the small-cell floor." : "No dated reports.") : resize((width) => Plot.plot({
      width, height: 280,
      x: {type: "band", domain: c.by_year.map((d) => d.year), tickFormat: String, tickRotate: -45, label: null},
      y: {grid: true, label: "patients"},
      marks: [
        Plot.barY(c.by_year.filter((d) => d.patients != null), {x: "year", y: "patients", fill: "#2a78d6", tip: true}),
        Plot.text(c.by_year.filter((d) => d.patients == null), {x: "year", y: 0, text: () => `<${options.min_cell}`, dy: -8, fill: "currentColor"}),
        Plot.ruleY([0]),
      ],
    }))}
  </div>
  <div class="card">
    <h2>By disease</h2>
    <h3>Matching patients per disease. A patient with reports in two diseases counts in both.</h3>
    ${bars(c.by_disease, {format: (d) => d.disease, marginLeft: 220})}
  </div>
</div>

<div class="grid grid-cols-4">
  <div class="card">
    <h2>Vendor and assay</h2>
    ${bars(c.by_vendor_class, {format: (d) => `${d.vendor === "fmi" ? "FMI" : "Caris"} ${d.assay_class}`, marginLeft: 100})}
  </div>
  <div class="card">
    <h2>Alteration class</h2>
    ${bars(c.by_alt_class, {format: (d) => d.alt_class, marginLeft: 100})}
  </div>
  <div class="card">
    <h2>Sex</h2>
    ${bars(c.by_sex, {format: (d) => d.sex, marginLeft: 70})}
  </div>
  <div class="card">
    <h2>Age band</h2>
    ${bars(c.by_age, {format: (d) => d.age, marginLeft: 70})}
  </div>
</div>

<div class="card">
  <h2>How to read this page</h2>
  <ul>
    <li><strong>Patients, not reports.</strong> A patient matches if any of their reports passes every filter and carries a qualifying alteration in a selected gene. Filters combine with AND across lists and OR within one list.</li>
    <li><strong>Prevalence</strong> is matching patients over patients tested under the same organ, disease, demographic, assay and year filters, whether or not the gene was altered. Every vendor panel covers TP53, KRAS and the other common drivers, but not every rare gene; check Coverage & quality before reading a rare gene's prevalence.</li>
    <li><strong>Protein change</strong> appears when exactly one gene is selected. It lists changes seen in at least ${options.min_cell} patients; rarer ones could only ever read "<${options.min_cell}".</li>
    <li><strong>Accrual</strong> is matching patients divided by the number of years in the window. With the full range selected it averages over the whole history, including early years with little testing, so narrow the window to recent years for a forward estimate. The tiers are a rule of thumb for single-site material, not a feasibility verdict.</li>
    <li><strong>Small cells.</strong> Every count under ${options.min_cell} shows as "<${options.min_cell}", including each bar. Bars can sum to less than the total. Every query is logged with your email.</li>
    <li><strong>Age is known for Caris tissue reports only</strong>; every other report is in the "unknown" band, so an age filter that leaves out "unknown" drops all FMI and liquid-biopsy patients. Dates are shifted per patient by up to ±6 months, so years near the edges of the window can move by one.</li>
  </ul>
</div>
