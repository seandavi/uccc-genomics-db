// `npm test` — node's built-in runner; no framework.
import test from "node:test";
import assert from "node:assert/strict";
import {accrual, cohortQuery, fmtCount, organPreset, readQuery, tierFor} from "../src/components/cohort.js";

// The shape of /api/options.
const options = {
  organ: ["Blood/Bone Marrow", "Bowel", "Lung", "Pancreas"], disease: ["Melanoma"], gene: ["KRAS", "TP53"],
  aa: {TP53: ["R175H"]}, sex: ["female", "male"], age: ["<50", "50-64", "65-74", "75+", "unknown"],
  vendor: ["caris", "fmi"], assay_class: ["tissue", "liquid", "heme"],
  alt_class: ["pathogenic", "vus", "unclassified", "amplification", "loss", "fusion"], year_min: 2010, year_max: 2026, min_cell: 5,
};
const all = readQuery("", options);

test("suppressed counts read <5", () => {
  assert.equal(fmtCount(null), "<5");
  assert.equal(fmtCount(0), "0");
  assert.equal(fmtCount(5445), "5,445");
});

test("presets keep to the offered organs", () => {
  assert.deepEqual(organPreset("Solid tumors", options.organ), ["Bowel", "Lung", "Pancreas"]);
  assert.deepEqual(organPreset("GI tumors", options.organ), ["Bowel", "Pancreas"]);
});

test("defaults send no filters", () => {
  assert.equal(cohortQuery(all, options), "");
});

test("the R175H question as a query, and back", () => {
  const f = {...all, organ: ["Bowel", "Pancreas"], gene: ["TP53"], aa: ["R175H"]};
  const qs = cohortQuery(f, options);
  assert.equal(qs, "organ=Bowel&organ=Pancreas&gene=TP53&aa=R175H");
  assert.equal(cohortQuery(readQuery("?" + qs, options), options), qs);
});

test("partial groups, VUS and year window are sent; aa only with one gene", () => {
  const f = {...all, sex: ["female"], gene: ["TP53", "KRAS"], aa: ["R175H"], alt_class: ["pathogenic", "vus"], years: [2026, 2020]};
  assert.equal(cohortQuery(f, options),
    "sex=female&gene=TP53&gene=KRAS&alt_class=pathogenic&alt_class=vus&year_from=2020");
});

test("VUS and unclassified are opt-in", () => {
  assert.deepEqual(readQuery("", options).alt_class, ["pathogenic", "amplification", "loss", "fusion"]);
  assert.equal(cohortQuery({...all, gene: ["TP53"]}, options), "gene=TP53");
});

test("an empty checkbox group matches nothing, so there is no query", () => {
  assert.equal(cohortQuery({...all, vendor: []}, options), null);
  assert.equal(cohortQuery({...all, gene: ["TP53"], alt_class: []}, options), null);
});

test("accrual and tiers", () => {
  assert.equal(accrual(63, [2017, 2025]), 7);
  assert.equal(accrual(null, [2017, 2025]), null);
  assert.equal(tierFor(7).name, "Low / pilot");
  assert.equal(tierFor(10).name, "Moderate");
  assert.equal(tierFor(50).name, "High");
});
