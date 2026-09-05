// Cohort arithmetic for cohort.md, kept free of DOM and d3 so `npm test` can run it under node.
//
// Every input section is pre-aggregated with small cells (< min_cell) already removed, and
// "All diseases" rows are the rollup across diseases. Year x disease x gene cells are sparse
// after suppression, so the headline numbers use all-years totals and the annual sections
// only supply denominators and whatever survived.

const sum = (rows, k = "n") => rows.reduce((s, r) => s + (r[k] ?? 0), 0);

/** Group rows by `key`, summing `n`, sorted descending. */
export function rollup(rows, key, k = "n") {
  const m = new Map();
  for (const r of rows) m.set(r[key], (m.get(r[key]) ?? 0) + r[k]);
  return [...m].map(([v, n]) => ({[key]: v, n})).sort((a, b) => b.n - a.n);
}

export const TIERS = [
  {min: 50, name: "High", desc: "≥ 50 reports/yr: observational cohorts, outcomes linkage, biomarker-stratified trials", bg: "#e6f4ea", fg: "#137333"},
  {min: 10, name: "Moderate", desc: "10–49 reports/yr: multi-year retrospective cohorts; prospective accrual takes 2–4 years", bg: "#e8f0fe", fg: "#1a73e8"},
  {min: 0, name: "Low / pilot", desc: "< 10 reports/yr: case series or pilot work; consider multi-site", bg: "#fce8e6", fg: "#c5221f"},
];

export const tierFor = (accrual) => TIERS.find((t) => accrual >= t.min);

/**
 * @param data      the cohort.json loader output
 * @param genes     selected genes (empty = any)
 * @param diseases  selected diseases (empty = all)
 * @param vendor    "All" | "caris" | "fmi"
 * @param years     [start, end] inclusive, any order
 * @param includeVus count VUS calls as alterations
 */
export function cohort(data, {genes = [], diseases = [], vendor = "All", years, includeVus = false}) {
  const [y0, y1] = [Math.min(...years), Math.max(...years)];
  const span = y1 - y0 + 1;
  const hasGenes = genes.length > 0;
  const inDisease = diseases.length ? (d) => diseases.includes(d.disease) : (d) => d.disease === "All diseases";
  const inVendor = (d) => vendor === "All" || d.vendor === vendor;
  const inYear = (d) => d.year >= y0 && d.year <= y1;
  const inGene = (d) => genes.includes(d.gene) && (includeVus || !d.vus);
  const base = (d) => inDisease(d) && inVendor(d);

  const denoms = data.denoms.filter(base);
  const testedAll = sum(denoms);
  const patientsAll = sum(denoms, "n_patients");
  const annualDenoms = data.annual_denoms.filter((d) => base(d) && inYear(d));
  const testedWindow = sum(annualDenoms);

  // Reports with >= 1 alteration in a selected gene, all years. Across several genes this
  // counts a report once per gene it matches, so it is an upper bound for OR.
  const matching = hasGenes ? sum(data.gene_totals.filter((d) => base(d) && inGene(d))) : testedAll;
  const prevalence = testedAll ? matching / testedAll : 0;
  // Expected accrual: all-years prevalence applied to the window's testing volume. This
  // survives suppression where the per-year cells do not.
  const accrual = (hasGenes ? prevalence * testedWindow : testedWindow) / span;

  const annualGene = data.annual_gene.filter((d) => base(d) && inYear(d) && inGene(d));
  const altTypes = rollup(
    data.gene_alt_types.filter((d) => base(d) && (!hasGenes || genes.includes(d.gene)) && (includeVus || d.alt_type !== "VUS")),
    "alt_type");
  const topGenes = rollup(data.gene_totals.filter((d) => base(d) && (includeVus || !d.vus)), "gene")
    .slice(0, 15).map((d) => ({...d, pct: testedAll ? d.n / testedAll : 0}));
  const coAltered = rollup(data.top_comutations.filter((d) => genes.includes(d.gene_a) && !genes.includes(d.gene_b)), "gene_b")
    .slice(0, 15).map(({gene_b, n}) => ({gene: gene_b, n}));
  const modality = rollup(annualDenoms, "assay_class").map((d) => ({...d, pct: testedWindow ? d.n / testedWindow : 0}));

  const table = [];
  for (let year = y1; year >= y0; year--) {
    const den = annualDenoms.filter((d) => d.year === year);
    const tested = sum(den);
    if (!tested) continue;
    const by = (k, v) => sum(den.filter((d) => d[k] === v));
    const row = {year, tested, caris: by("vendor", "caris"), fmi: by("vendor", "fmi"),
                 tissue: by("assay_class", "tissue"), liquid: by("assay_class", "liquid"), heme: by("assay_class", "heme")};
    if (hasGenes) {
      const observed = sum(annualGene.filter((d) => d.year === year));
      Object.assign(row, {observed, share: tested ? observed / tested : 0});
    }
    table.push(row);
  }

  return {y0, y1, span, hasGenes, testedAll, patientsAll, testedWindow, matching, prevalence, accrual,
          tier: tierFor(accrual), annualDenoms, annualGene, altTypes, topGenes, coAltered, modality, table};
}
