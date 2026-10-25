// Display helpers for cohort.md, kept free of DOM so `npm test` can run them under node.
// Counts come from /api/cohort already floored: a count under min_cell arrives as null.

export const TIERS = [
  {min: 50, name: "High", desc: "≥ 50 patients/yr: observational cohorts, outcomes linkage, biomarker-stratified trials", bg: "#e6f4ea", fg: "#137333"},
  {min: 10, name: "Moderate", desc: "10–49 patients/yr: multi-year retrospective cohorts; prospective accrual takes 2–4 years", bg: "#e8f0fe", fg: "#1a73e8"},
  {min: 0, name: "Low / pilot", desc: "< 10 patients/yr: case series or pilot work; consider multi-site", bg: "#fce8e6", fg: "#c5221f"},
];

export const tierFor = (accrual) => TIERS.find((t) => accrual >= t.min);

export const GI_ORGANS = ["Esophagus/Stomach", "Bowel", "Pancreas", "Biliary Tract", "Liver"];
export const ORGAN_PRESETS = ["Solid tumors", "GI tumors"];

/** Organ systems for a preset, restricted to what the API offers. */
export function organPreset(name, organs) {
  if (name === "Solid tumors") return organs.filter((o) => o !== "Blood/Bone Marrow");
  if (name === "GI tumors") return organs.filter((o) => GI_ORGANS.includes(o));
  return [];
}

/** null (a suppressed count) as "<5"; everything else with thousands separators. */
export const fmtCount = (n, minCell = 5) => (n == null ? `<${minCell}` : n.toLocaleString("en-US"));

// Checkbox groups start fully checked; all checked means no filter, so it is left out of the query.
export const OPT_IN_CLASSES = ["vus", "unclassified"];
const GROUPS = ["sex", "age", "vendor", "assay_class"];

/**
 * Filter state -> the query string shared by /api/cohort and the page's own URL, or null when a
 * checkbox group is empty (no patients can match; the API would read an empty list as "any").
 */
export function cohortQuery(f, options) {
  const q = new URLSearchParams();
  const add = (k, vals) => vals.forEach((v) => q.append(k, v));
  add("organ", f.organ ?? []);
  add("disease", f.disease ?? []);
  for (const g of GROUPS) {
    const vals = f[g] ?? options[g];
    if (!vals.length) return null;
    if (vals.length < options[g].length) add(g, vals);
  }
  const genes = f.gene ?? [];
  add("gene", genes);
  if (genes.length) {
    if (!f.alt_class?.length) return null;
    // The API's default is every class except VUS and unclassified; only send a different choice.
    const dflt = options.alt_class.filter((c) => !OPT_IN_CLASSES.includes(c));
    if (f.alt_class.join() !== dflt.join()) add("alt_class", f.alt_class);
  }
  if (genes.length === 1) add("aa", f.aa ?? []);
  const [y0, y1] = [Math.min(...f.years), Math.max(...f.years)];
  if (y0 > options.year_min) q.set("year_from", y0);
  if (y1 < options.year_max) q.set("year_to", y1);
  return q.toString();
}

/** Page URL -> initial filter state, the inverse of cohortQuery. */
export function readQuery(search, options) {
  const q = new URLSearchParams(search);
  const f = {};
  for (const k of ["organ", "disease", "gene", "aa", ...GROUPS]) f[k] = q.getAll(k);
  for (const g of GROUPS) if (!f[g].length) f[g] = options[g];
  f.alt_class = q.getAll("alt_class");
  if (!f.alt_class.length) f.alt_class = options.alt_class.filter((c) => !OPT_IN_CLASSES.includes(c));
  f.years = [+(q.get("year_from") ?? options.year_min), +(q.get("year_to") ?? options.year_max)];
  return f;
}

/** Patients per year over the window; null when the cohort itself is suppressed. */
export const accrual = (patients, years) => (patients == null ? null : patients / (Math.abs(years[1] - years[0]) + 1));
