// `npm test` — node's built-in runner; no framework.
import test from "node:test";
import assert from "node:assert/strict";
import {cohort, rollup, tierFor} from "../src/components/cohort.js";

// A tiny loader output: two diseases, two vendors, two years, one rare gene.
const data = {
  meta: {min_year: 2020, max_year: 2021, min_cell: 5},
  denoms: [
    {disease: "All diseases", vendor: "caris", n: 100, n_patients: 90},
    {disease: "All diseases", vendor: "fmi", n: 200, n_patients: 190},
    {disease: "Melanoma", vendor: "caris", n: 20, n_patients: 20},
    {disease: "Melanoma", vendor: "fmi", n: 80, n_patients: 78},
    {disease: "Breast Cancer", vendor: "fmi", n: 50, n_patients: 50},
  ],
  annual_denoms: [
    {year: 2020, disease: "All diseases", vendor: "caris", assay_class: "tissue", n: 40, n_patients: 40},
    {year: 2021, disease: "All diseases", vendor: "caris", assay_class: "tissue", n: 60, n_patients: 55},
    {year: 2020, disease: "All diseases", vendor: "fmi", assay_class: "tissue", n: 90, n_patients: 90},
    {year: 2021, disease: "All diseases", vendor: "fmi", assay_class: "liquid", n: 110, n_patients: 100},
    {year: 2020, disease: "Melanoma", vendor: "fmi", assay_class: "tissue", n: 30, n_patients: 30},
    {year: 2021, disease: "Melanoma", vendor: "fmi", assay_class: "tissue", n: 50, n_patients: 48},
    {year: 2021, disease: "Melanoma", vendor: "caris", assay_class: "tissue", n: 20, n_patients: 20},
  ],
  gene_totals: [
    {disease: "All diseases", vendor: "fmi", gene: "KRAS", vus: false, n: 40},
    {disease: "All diseases", vendor: "caris", gene: "KRAS", vus: false, n: 10},
    {disease: "All diseases", vendor: "fmi", gene: "KRAS", vus: true, n: 6},
    {disease: "Melanoma", vendor: "fmi", gene: "KRAS", vus: false, n: 8},   // rare: never >= 5 in one year
    {disease: "All diseases", vendor: "fmi", gene: "TP53", vus: false, n: 120},
    {disease: "Melanoma", vendor: "fmi", gene: "TP53", vus: false, n: 30},
  ],
  gene_alt_types: [
    {disease: "Melanoma", vendor: "fmi", gene: "KRAS", alt_type: "pathogenic/likely", n: 7},
    {disease: "Melanoma", vendor: "fmi", gene: "KRAS", alt_type: "amplification", n: 5},
    {disease: "All diseases", vendor: "fmi", gene: "KRAS", alt_type: "VUS", n: 6},
  ],
  annual_gene: [
    {year: 2020, disease: "All diseases", vendor: "fmi", gene: "KRAS", vus: false, n: 18},
    {year: 2021, disease: "All diseases", vendor: "fmi", gene: "KRAS", vus: false, n: 22},
  ],
  top_comutations: [
    {gene_a: "KRAS", gene_b: "TP53", n: 25},
    {gene_a: "KRAS", gene_b: "CDKN2A", n: 9},
    {gene_a: "TP53", gene_b: "KRAS", n: 25},
  ],
};

test("no genes: everything tested in window, all diseases", () => {
  const c = cohort(data, {years: [2020, 2021]});
  assert.equal(c.testedAll, 300);
  assert.equal(c.testedWindow, 300);
  assert.equal(c.matching, 300);
  assert.equal(c.accrual, 150);
  assert.equal(c.tier.name, "High");
  assert.deepEqual(c.table.map((r) => r.year), [2021, 2020]);
  assert.equal(c.table[0].caris + c.table[0].fmi, c.table[0].tested);
});

test("rare gene in a disease: headline comes from all-years totals, not the empty annual cells", () => {
  const c = cohort(data, {genes: ["KRAS"], diseases: ["Melanoma"], years: [2020, 2021]});
  assert.equal(c.testedAll, 100);
  assert.equal(c.matching, 8);
  assert.equal(c.prevalence, 0.08);
  assert.equal(c.annualGene.length, 0);           // suppressed at year grain
  assert.equal(c.accrual, 0.08 * 100 / 2);         // still a usable estimate
  assert.equal(c.tier.name, "Low / pilot");
  assert.deepEqual(c.altTypes.map((d) => d.alt_type), ["pathogenic/likely", "amplification"]);
  assert.deepEqual(c.coAltered.map((d) => d.gene), ["TP53", "CDKN2A"]);
  assert.equal(c.table[0].observed, 0);
});

test("vendor and VUS filters", () => {
  const all = cohort(data, {genes: ["KRAS"], years: [2020, 2021]});
  assert.equal(all.matching, 50);
  const vus = cohort(data, {genes: ["KRAS"], years: [2020, 2021], includeVus: true});
  assert.equal(vus.matching, 56);
  const fmi = cohort(data, {genes: ["KRAS"], vendor: "fmi", years: [2020, 2021]});
  assert.equal(fmi.matching, 40);
  assert.equal(fmi.testedAll, 200);
});

test("year window in either order, and years outside the data", () => {
  const a = cohort(data, {years: [2021, 2020]});
  const b = cohort(data, {years: [2020, 2021]});
  assert.equal(a.testedWindow, b.testedWindow);
  const c = cohort(data, {years: [2015, 2016]});
  assert.equal(c.testedWindow, 0);
  assert.equal(c.accrual, 0);
  assert.equal(c.table.length, 0);
});

test("multiple diseases sum their rows (a report has one disease)", () => {
  const c = cohort(data, {diseases: ["Melanoma", "Breast Cancer"], years: [2020, 2021]});
  assert.equal(c.testedAll, 150);
  assert.deepEqual(c.topGenes.map((d) => d.gene), ["TP53", "KRAS"]);
});

test("rollup and tiers", () => {
  assert.deepEqual(rollup([{k: "a", n: 1}, {k: "b", n: 5}, {k: "a", n: 2}], "k"), [{k: "b", n: 5}, {k: "a", n: 3}]);
  assert.equal(tierFor(50).name, "High");
  assert.equal(tierFor(49.9).name, "Moderate");
  assert.equal(tierFor(0).name, "Low / pilot");
});
