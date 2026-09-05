---
title: Cohort exploration
---

# Cohort & Feasibility Exploration

```js
const data = FileAttachment("data/cohort.json").json();
```

```js
const vendorColor = {domain: ["caris", "fmi"], range: ["#2a78d6", "#eb6834"], legend: true};
const altColor = {
  domain: ["pathogenic/likely", "amplification", "loss", "fusion", "VUS"],
  range: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
  legend: true
};
const assayColor = {domain: ["tissue", "liquid", "heme"], range: ["#2a78d6", "#1baf7a", "#9c59b6"], legend: true};
const fmt = (n) => (n != null ? Number(n).toLocaleString("en-US") : "0");
```

<div class="card" style="background: var(--theme-background-alt); padding: 1rem 1.5rem; margin-bottom: 1.5rem; border-left: 4px solid #2a78d6;">
  <div style="font-weight: 600; font-size: 1.05rem; margin-bottom: 0.25rem;">Governance & De-Identification Protocol</div>
  <div style="font-size: 0.9rem; color: var(--theme-foreground-muted); line-height: 1.5;">
    Institutional privacy rules strictly enforced: <strong>Counts below 5 are suppressed</strong> across all stratifications.
    Collection and accession dates have been deterministically perturbed per patient by up to <strong>±6 months</strong> (±182 days) with longitudinal intervals preserved.
    Cohort metrics use calendar-year aggregates to prevent date triangulation. Zero row-level records or identifiers are emitted.
  </div>
</div>

```js
const genesList = data.genes.map((d) => d.gene);
const diseasesList = data.diseases.map((d) => d.disease);
```

```js
const selectedGene = view(Inputs.select(["(Any gene)", ...genesList], {label: "Gene", value: "(Any gene)"}));
const selectedDisease = view(Inputs.select(["(All diseases)", ...diseasesList], {label: "Disease", value: "(All diseases)"}));
```

```js
const startYear = view(Inputs.range([data.meta.min_year, data.meta.max_year], {step: 1, value: 2018, label: "Start year"}));
const endYear = view(Inputs.range([data.meta.min_year, data.meta.max_year], {step: 1, value: 2025, label: "End year"}));
const selectedVendor = view(Inputs.radio(["All", "caris", "fmi"], {label: "Vendor", value: "All"}));
const includeVus = view(Inputs.toggle({label: "Include VUS", value: false}));
```

```js
// Normalise year bounds
const minSelYear = Math.min(startYear, endYear);
const maxSelYear = Math.max(startYear, endYear);
const spanYears = maxSelYear - minSelYear + 1;

const matchesVendor = (v) => selectedVendor === "All" || v === selectedVendor;
const matchesYear = (y) => y >= minSelYear && y <= maxSelYear;
const matchesAlt = (t) => includeVus || t !== "VUS";

// Baseline denominators in selected window & disease
const baselineRows = selectedDisease === "(All diseases)"
  ? data.annual_overall_denoms.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor))
  : data.annual_disease_denoms.filter((d) => d.disease === selectedDisease && matchesYear(d.year) && matchesVendor(d.vendor));

const baselineReportsInWindow = d3.sum(baselineRows, (d) => d.n);
const baselinePatientsInWindow = d3.sum(baselineRows, (d) => d.n_patients);

// Matching cohort calculations
const isAnyGene = selectedGene === "(Any gene)";

// Alteration records matching criteria
const geneAltRows = isAnyGene
  ? []
  : (selectedDisease === "(All diseases)"
      ? data.annual_overall_gene_alt.filter((d) => d.gene === selectedGene && matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type))
      : data.annual_disease_gene_alt.filter((d) => d.disease === selectedDisease && d.gene === selectedGene && matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type)));

const matchingReports = isAnyGene ? baselineReportsInWindow : d3.sum(geneAltRows, (d) => d.n);
const ptRatio = baselineReportsInWindow > 0 ? baselinePatientsInWindow / baselineReportsInWindow : 0.92;
const matchingPatients = isAnyGene ? baselinePatientsInWindow : Math.min(matchingReports, Math.round(matchingReports * ptRatio));

const avgReportsPerYear = spanYears > 0 ? (matchingReports / spanYears) : 0;
const prevalence = baselineReportsInWindow > 0 ? (matchingReports / baselineReportsInWindow) : 0;

// Feasibility tier calculation
const tier = avgReportsPerYear >= 50
  ? {name: "High Feasibility", desc: "≥ 50 reports/yr — robust accrual for observational, biomarker, or trial cohorts", bg: "#e6f4ea", text: "#137333", border: "#ceead6"}
  : avgReportsPerYear >= 10
  ? {name: "Moderate Feasibility", desc: "10–49 reports/yr — viable for multi-year retrospective or targeted cohorts", bg: "#e8f0fe", text: "#1a73e8", border: "#d2e3fc"}
  : {name: "Low / Pilot Feasibility", desc: "< 10 reports/yr — rare alteration or small disease subset; pilot accrual only", bg: "#fce8e6", text: "#c5221f", border: "#fad2cf"};
```

<div class="grid grid-cols-5" style="gap: 1rem; margin-top: 1.5rem; margin-bottom: 1.5rem;">
  <div class="card">
    <h2>Matching Reports</h2>
    <span class="big">${fmt(matchingReports)}</span>
    <br><span class="muted">${isAnyGene ? "Total tested in window" : `${fmt(baselineReportsInWindow)} total tested`}</span>
  </div>
  <div class="card">
    <h2>Estimated Patients</h2>
    <span class="big">${fmt(matchingPatients)}</span>
    <br><span class="muted">~${(ptRatio * 100).toFixed(0)}% patient:report ratio</span>
  </div>
  <div class="card">
    <h2>Accrual Rate</h2>
    <span class="big">${avgReportsPerYear.toFixed(1)}</span>
    <br><span class="muted">reports / year (${minSelYear}–${maxSelYear})</span>
  </div>
  <div class="card">
    <h2>Cohort Share</h2>
    <span class="big">${isAnyGene ? "100%" : (prevalence * 100).toFixed(1) + "%"}</span>
    <br><span class="muted">${isAnyGene ? "of selected disease" : `of tested ${selectedDisease === "(All diseases)" ? "reports" : selectedDisease}`}</span>
  </div>
  <div class="card" style="background: ${tier.bg}; border: 1px solid ${tier.border};">
    <h2 style="color: ${tier.text};">Feasibility Tier</h2>
    <div style="font-weight: 700; font-size: 1.25rem; color: ${tier.text}; margin-top: 0.25rem;">${tier.name}</div>
    <div style="font-size: 0.78rem; color: ${tier.text}; margin-top: 0.35rem; line-height: 1.3;">${tier.desc}</div>
  </div>
</div>

```js
// Trend chart data: build annual breakdown
const trendData = (() => {
  if (isAnyGene) {
    return d3.rollups(baselineRows, (v) => d3.sum(v, (d) => d.n), (d) => d.year, (d) => d.vendor)
      .flatMap(([year, vMap]) => vMap.map(([vendor, n]) => ({year, vendor, n})));
  } else {
    return d3.rollups(geneAltRows, (v) => d3.sum(v, (d) => d.n), (d) => d.year, (d) => d.alt_type)
      .flatMap(([year, vMap]) => vMap.map(([alt_type, n]) => ({year, alt_type, n})));
  }
})();
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Accrual Trend Over Time (${minSelYear}–${maxSelYear})</h2>
    <h3>${isAnyGene ? "Reports per year stacked by sequencing vendor" : `${selectedGene} alterations per year stacked by alteration class`}</h3>
    ${resize((width) => Plot.plot({
      width,
      height: 320,
      color: isAnyGene ? vendorColor : altColor,
      x: {type: "band", domain: d3.range(minSelYear, maxSelYear + 1), label: "Collection year (perturbed ±6mo)", tickRotate: -45},
      y: {grid: true, label: "reports"},
      marks: [
        isAnyGene
          ? Plot.barY(trendData, {x: "year", y: "n", fill: "vendor", tip: true})
          : Plot.barY(trendData, {x: "year", y: "n", fill: "alt_type", tip: true}),
        Plot.ruleY([0])
      ]
    }))}
  </div>

  <div class="card">
    <h2>Assay & Specimen Modality</h2>
    <h3>Distribution of tissue vs. liquid vs. heme assays in this selection</h3>
    ${(() => {
      const classRollup = d3.rollups(baselineRows, (v) => d3.sum(v, (d) => d.n), (d) => d.assay_class)
        .map(([assay_class, n]) => ({assay_class, n, pct: baselineReportsInWindow > 0 ? n / baselineReportsInWindow : 0}))
        .sort((a, b) => b.n - a.n);

      if (classRollup.length === 0) {
        return html`<div style="padding: 2rem; color: var(--theme-foreground-muted);">No reports matching criteria.</div>`;
      }

      return resize((width) => Plot.plot({
        width,
        height: 320,
        marginLeft: 90,
        color: assayColor,
        x: {grid: true, label: "reports", domain: [0, d3.max(classRollup, (d) => d.n) * 1.15 || 10]},
        y: {label: null, domain: classRollup.map((d) => d.assay_class)},
        marks: [
          Plot.barX(classRollup, {x: "n", y: "assay_class", fill: "assay_class", tip: true}),
          Plot.text(classRollup, {
            x: "n",
            y: "assay_class",
            text: (d) => `${fmt(d.n)} (${(d.pct * 100).toFixed(1)}%)`,
            dx: 6,
            textAnchor: "start",
            fill: "currentColor",
            fontSize: 12
          }),
          Plot.ruleX([0])
        ]
      }));
    })()}
  </div>
</div>

```js
// Alteration Type Breakdown
const altTypeSummary = (() => {
  if (isAnyGene) {
    const allAlt = selectedDisease === "(All diseases)"
      ? data.annual_overall_gene_alt.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type))
      : data.annual_disease_gene_alt.filter((d) => d.disease === selectedDisease && matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type));
    return d3.rollups(allAlt, (v) => d3.sum(v, (d) => d.n), (d) => d.alt_type)
      .map(([alt_type, n]) => ({alt_type, n}))
      .sort((a, b) => b.n - a.n);
  } else {
    return d3.rollups(geneAltRows, (v) => d3.sum(v, (d) => d.n), (d) => d.alt_type)
      .map(([alt_type, n]) => ({alt_type, n, pct: matchingReports > 0 ? n / matchingReports : 0}))
      .sort((a, b) => b.n - a.n);
  }
})();

// Gene landscape or Co-alterations
const landscapeData = (() => {
  if (isAnyGene) {
    const altSource = selectedDisease === "(All diseases)"
      ? data.annual_overall_gene_alt.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type))
      : data.annual_disease_gene_alt.filter((d) => d.disease === selectedDisease && matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type));
    return d3.rollups(altSource, (v) => d3.sum(v, (d) => d.n), (d) => d.gene)
      .map(([gene, n]) => ({gene, n, pct: baselineReportsInWindow > 0 ? n / baselineReportsInWindow : 0}))
      .sort((a, b) => b.n - a.n)
      .slice(0, 15);
  } else {
    return data.top_comutations
      .filter((d) => d.gene_a === selectedGene)
      .sort((a, b) => b.n - a.n)
      .slice(0, 15)
      .map((d) => ({gene: d.gene_b, n: d.n, pct: matchingReports > 0 ? d.n / matchingReports : 0}));
  }
})();
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>${isAnyGene ? "Overall Alteration Class Breakdown" : `${selectedGene} Alteration Distribution`}</h2>
    <h3>${isAnyGene ? "Distribution across all alterations in current selection" : `Breakdown of pathogenic variants, CNA, fusions, and VUS in ${selectedGene}`}</h3>
    ${(() => {
      if (altTypeSummary.length === 0) {
        return html`<div style="padding: 2rem; color: var(--theme-foreground-muted);">No alterations recorded for this selection (cells < 5 suppressed).</div>`;
      }
      return resize((width) => Plot.plot({
        width,
        height: 280,
        marginLeft: 130,
        color: altColor,
        x: {grid: true, label: "alterations", domain: [0, d3.max(altTypeSummary, (d) => d.n) * 1.18 || 10]},
        y: {label: null, domain: altTypeSummary.map((d) => d.alt_type)},
        marks: [
          Plot.barX(altTypeSummary, {x: "n", y: "alt_type", fill: "alt_type", tip: true}),
          Plot.text(altTypeSummary, {
            x: "n",
            y: "alt_type",
            text: (d) => `${fmt(d.n)}`,
            dx: 6,
            textAnchor: "start",
            fill: "currentColor",
            fontSize: 12
          }),
          Plot.ruleX([0])
        ]
      }));
    })()}
  </div>

  <div class="card">
    <h2>${isAnyGene ? `Top Altered Genes in ${selectedDisease}` : `Co-altered Genes with ${selectedGene}`}</h2>
    <h3>${isAnyGene ? "Most frequently altered genes in the selected cohort" : `Pairwise co-occurrence in reports harboring a pathogenic ${selectedGene} alteration`}</h3>
    ${(() => {
      if (landscapeData.length === 0) {
        return html`<div style="padding: 2rem; color: var(--theme-foreground-muted);">No co-alterations meet the privacy cell threshold (≥ 5 reports).</div>`;
      }
      return resize((width) => Plot.plot({
        width,
        height: 280,
        marginLeft: 90,
        x: {grid: true, label: isAnyGene ? "alterations" : "co-mutated reports", domain: [0, d3.max(landscapeData, (d) => d.n) * 1.15 || 10]},
        y: {label: null, domain: landscapeData.map((d) => d.gene)},
        marks: [
          Plot.barX(landscapeData, {x: "n", y: "gene", fill: "#2a78d6", tip: true}),
          Plot.text(landscapeData, {
            x: "n",
            y: "gene",
            text: (d) => `${fmt(d.n)}`,
            dx: 6,
            textAnchor: "start",
            fill: "currentColor",
            fontSize: 11
          }),
          Plot.ruleX([0])
        ]
      }));
    })()}
  </div>
</div>

```js
// Build annual breakdown table
const tableRows = (() => {
  const years = d3.range(minSelYear, maxSelYear + 1);
  return years.map((yr) => {
    const yrDenomRows = baselineRows.filter((d) => d.year === yr);
    const yrTotalReports = d3.sum(yrDenomRows, (d) => d.n);
    const yrPatients = d3.sum(yrDenomRows, (d) => d.n_patients);
    const carisReports = d3.sum(yrDenomRows.filter((d) => d.vendor === "caris"), (d) => d.n);
    const fmiReports = d3.sum(yrDenomRows.filter((d) => d.vendor === "fmi"), (d) => d.n);

    if (isAnyGene) {
      return {
        Year: yr,
        "Total Reports": yrTotalReports,
        "Est. Patients": yrPatients,
        Caris: carisReports,
        FMI: fmiReports,
        "Tissue Assays": d3.sum(yrDenomRows.filter((d) => d.assay_class === "tissue"), (d) => d.n),
        "Liquid Assays": d3.sum(yrDenomRows.filter((d) => d.assay_class === "liquid"), (d) => d.n),
        "Heme Assays": d3.sum(yrDenomRows.filter((d) => d.assay_class === "heme"), (d) => d.n),
      };
    } else {
      const yrAltRows = geneAltRows.filter((d) => d.year === yr);
      const yrAltTotal = d3.sum(yrAltRows, (d) => d.n);
      const yrPrevalence = yrTotalReports > 0 ? (yrAltTotal / yrTotalReports) : 0;
      return {
        Year: yr,
        [`${selectedGene} Alterations`]: yrAltTotal,
        "Tested Reports": yrTotalReports,
        "Prevalence (%)": yrTotalReports > 0 ? (yrPrevalence * 100).toFixed(1) + "%" : "—",
        "Pathogenic/Likely": d3.sum(yrAltRows.filter((d) => d.alt_type === "pathogenic/likely"), (d) => d.n),
        Amplification: d3.sum(yrAltRows.filter((d) => d.alt_type === "amplification"), (d) => d.n),
        Loss: d3.sum(yrAltRows.filter((d) => d.alt_type === "loss"), (d) => d.n),
        Fusion: d3.sum(yrAltRows.filter((d) => d.alt_type === "fusion"), (d) => d.n),
        VUS: d3.sum(yrAltRows.filter((d) => d.alt_type === "VUS"), (d) => d.n),
      };
    }
  }).filter((r) => isAnyGene ? r["Total Reports"] > 0 : r["Tested Reports"] > 0 || r[`${selectedGene} Alterations`] > 0);
})();
```

<div class="card" style="margin-top: 1.5rem;">
  <h2>Annual Cohort Breakdown (${minSelYear}–${maxSelYear})</h2>
  <h3>Annual accrual and alteration counts for selected criteria. Stratified cells with fewer than ${data.meta.min_cell} records are omitted per institutional governance rules.</h3>
  ${Inputs.table(tableRows, {
    sort: "Year",
    reverse: true,
    rows: 15
  })}
</div>

<div class="grid grid-cols-2" style="margin-top: 1.5rem; gap: 1rem;">
  <div class="card">
    <h2>Feasibility & Power Guidelines</h2>
    <div style="font-size: 0.9rem; line-height: 1.6; color: var(--theme-foreground);">
      <p><strong>Accrual Feasibility</strong> is estimated using historical annual testing volume at University of Colorado Cancer Center across Caris and Foundation Medicine tests.</p>
      <ul>
        <li><strong>High Feasibility (≥ 50/year):</strong> Suitable for observational cohorts, retrospective clinical outcomes linkage, and biomarker stratified prospective trials.</li>
        <li><strong>Moderate Feasibility (10–49/year):</strong> Well-suited for multi-year retrospective studies or synthetic control arms; prospective accrual may require 2–4 years.</li>
        <li><strong>Low / Pilot Feasibility (&lt; 10/year):</strong> Best suited for case series, pilot exploration, or rare variant functional genomics. Multi-site collaboration advised.</li>
      </ul>
    </div>
  </div>

  <div class="card">
    <h2>Data Provenance & Privacy Floor</h2>
    <div style="font-size: 0.9rem; line-height: 1.6; color: var(--theme-foreground);">
      <p><strong>De-identification Safeguards:</strong></p>
      <ul>
        <li><strong>Cell suppression:</strong> Any sub-cohort stratification with fewer than 5 records is omitted at data generation time (loader floor: <code>MIN_CELL = 5</code>).</li>
        <li><strong>Temporal shifting:</strong> Specimen collection dates are perturbed per-patient by ±182 days. All intra-patient event timing and longitudinal sequences remain exact.</li>
        <li><strong>Cross-vendor deduplication:</strong> Patients tested across both Caris and Foundation Medicine are linked via deterministic keyed hashing.</li>
      </ul>
    </div>
  </div>
</div>
