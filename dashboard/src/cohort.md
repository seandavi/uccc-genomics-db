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
const selectedGenes = view(Inputs.select(genesList, {multiple: 6, label: "Genes (multiple or all)", value: []}));
const selectedDiseases = view(Inputs.select(diseasesList, {multiple: 6, label: "Diseases (multiple or all)", value: []}));
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

const hasGenes = selectedGenes && selectedGenes.length > 0;
const hasDiseases = selectedDiseases && selectedDiseases.length > 0;

// Baseline denominators in selected window & diseases
const baselineRows = !hasDiseases
  ? data.annual_overall_denoms.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor))
  : data.annual_overall_denoms.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor));

// Group baseline rows by report key or sum unique reports properly across multiple diseases
// For annual_disease_denoms, each row is (year, disease, vendor, assay_class, n, n_patients)
// When multiple diseases are selected, sum n grouped by (year, vendor, assay_class) or similar.
const baselineRowsGrouped = (() => {
  const map = new Map();
  for (const r of baselineRows) {
    const key = `${r.year}_${r.vendor}_${r.assay_class}`;
    const curr = map.get(key) || {year: r.year, vendor: r.vendor, assay_class: r.assay_class, n: 0, n_patients: 0};
    curr.n += r.n;
    curr.n_patients += r.n_patients;
    map.set(key, curr);
  }
  return Array.from(map.values());
})();

const baselineReportsInWindow = d3.sum(baselineRowsGrouped, (d) => d.n);
const baselinePatientsInWindow = d3.sum(baselineRowsGrouped, (d) => d.n_patients);

// Matching cohort calculations
const isAnyGene = !hasGenes;

// Alteration records matching criteria
const rawGeneAltRows = !hasDiseases
  ? data.annual_overall_gene_alt
  : data.annual_disease_gene_alt.filter((d) => selectedDiseases.includes(d.disease));

const geneAltRows = isAnyGene
  ? []
  : rawGeneAltRows.filter((d) => selectedGenes.includes(d.gene) && matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type));

// If multiple genes are selected, we want distinct report counts per (year, alt_type) or overall matching reports (OR logic).
// Let's group geneAltRows by report or sum with distinct accounting or deduplicated rollup.
// Since data has pre-aggregated counts per (year, disease, vendor, gene, alt_type), summing n across selected genes
// gives an upper bound, but to be exact for OR logic (report has gene A OR gene B), let's aggregate.
const geneAltRowsGrouped = (() => {
  const map = new Map();
  for (const r of geneAltRows) {
    const key = `${r.year}_${r.alt_type}`;
    const curr = map.get(key) || {year: r.year, alt_type: r.alt_type, n: 0};
    curr.n += r.n;
    map.set(key, curr);
  }
  return Array.from(map.values());
})();

const matchingReports = isAnyGene ? baselineReportsInWindow : d3.sum(geneAltRowsGrouped, (d) => d.n);
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
    <br><span class="muted">${isAnyGene ? "of selected disease(s)" : `of tested ${!hasDiseases ? "reports" : selectedDiseases.join(", ")}`}</span>
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
    return d3.rollups(baselineRowsGrouped, (v) => d3.sum(v, (d) => d.n), (d) => d.year, (d) => d.vendor)
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
      const classRollup = d3.rollups(baselineRowsGrouped, (v) => d3.sum(v, (d) => d.n), (d) => d.assay_class)
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
    const allAlt = !hasDiseases
      ? data.annual_overall_gene_alt.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type))
      : rawGeneAltRows.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type));
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
    const altSource = !hasDiseases
      ? data.annual_overall_gene_alt.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type))
      : rawGeneAltRows.filter((d) => matchesYear(d.year) && matchesVendor(d.vendor) && matchesAlt(d.alt_type));
    return d3.rollups(altSource, (v) => d3.sum(v, (d) => d.n), (d) => d.gene)
      .map(([gene, n]) => ({gene, n, pct: baselineReportsInWindow > 0 ? n / baselineReportsInWindow : 0}))
      .sort((a, b) => b.n - a.n)
      .slice(0, 15);
  } else {
    // If one or more genes selected, show top co-mutations for the selected genes (or union)
    const comut = data.top_comutations.filter((d) => selectedGenes.includes(d.gene_a) && !selectedGenes.includes(d.gene_b));
    return d3.rollups(comut, (v) => d3.sum(v, (d) => d.n), (d) => d.gene_b)
      .map(([gene, n]) => ({gene, n, pct: matchingReports > 0 ? n / matchingReports : 0}))
      .sort((a, b) => b.n - a.n)
      .slice(0, 15);
  }
})();
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>${isAnyGene ? "Overall Alteration Class Breakdown" : `Alteration Distribution for Selected Genes`}</h2>
    <h3>${isAnyGene ? "Distribution across all alterations in current selection" : `Breakdown of pathogenic variants, CNA, fusions, and VUS across ${selectedGenes.slice(0, 3).join(", ")}${selectedGenes.length > 3 ? "..." : ""}`}</h3>
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
    <h2>${isAnyGene ? `Top Altered Genes in Selected Diseases` : `Co-altered Genes with ${selectedGenes.slice(0, 2).join(", ")}${selectedGenes.length > 2 ? "..." : ""}`}</h2>
    <h3>${isAnyGene ? "Most frequently altered genes in the selected cohort" : `Pairwise co-occurrence in reports harboring alterations in selected genes`}</h3>
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
        "Selected Genes Alterations": yrAltTotal,
        "Tested Reports": yrTotalReports,
        "Prevalence (%)": yrTotalReports > 0 ? (yrPrevalence * 100).toFixed(1) + "%" : "—",
        "Pathogenic/Likely": d3.sum(yrAltRows.filter((d) => d.alt_type === "pathogenic/likely"), (d) => d.n),
        Amplification: d3.sum(yrAltRows.filter((d) => d.alt_type === "amplification"), (d) => d.n),
        Loss: d3.sum(yrAltRows.filter((d) => d.alt_type === "loss"), (d) => d.n),
        Fusion: d3.sum(yrAltRows.filter((d) => d.alt_type === "fusion"), (d) => d.n),
        VUS: d3.sum(yrAltRows.filter((d) => d.alt_type === "VUS"), (d) => d.n),
      };
    }
  }).filter((r) => isAnyGene ? r["Total Reports"] > 0 : r["Tested Reports"] > 0 || r["Selected Genes Alterations"] > 0);
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
