// Pure helpers: labels, formatting, vocabulary entry -> action, versions, share hash, combobox keys.
import type { BreakdownDim, CountResult, Criterion, Definition, Leaf, Mode, Option, Population, SeqMember, YearCount } from "./types.ts";

export interface Version { n: number; definition: Definition }
export interface History { versions: Version[]; current: number }   // current indexes versions

export const HISTORY_KEY = "uccc-discover-history";
export const MAX_VERSIONS = 50;

export const EMPTY: Definition = {
  version: 1, name: "", scope: "patient", criteria: [], breakdown: [], pivot: null,
  population: {oncotree: [], organ: [], sex: [], age_band: [], vendor: [], assay_class: [], years: null},
};

export const POP_DIMS = ["oncotree", "organ", "sex", "age_band", "vendor", "assay_class"] as const;
export type PopDim = (typeof POP_DIMS)[number];

export const BREAKDOWN_DIMS: {value: BreakdownDim; label: string}[] = [
  {value: "oncotree", label: "Tumor type (OncoTree)"}, {value: "organ", label: "Organ system"},
  {value: "sex", label: "Sex"}, {value: "age_band", label: "Age band"}, {value: "vendor", label: "Vendor"},
  {value: "assay_class", label: "Assay class"}, {value: "site_type", label: "Specimen site type"},
  {value: "has_wts", label: "Whole-transcriptome sequencing"},
];

// --- numbers -------------------------------------------------------------------------------------

/** null (a suppressed count) as "<5"; everything else with thousands separators. */
export const fmtCount = (n: number | null | undefined, minCell = 5): string =>
  n == null ? `<${minCell}` : n.toLocaleString("en-US");

/** Integer percentage of two shown counts; null when either is suppressed or the denominator is 0. */
export function pct(n: number | null | undefined, of: number | null | undefined): string | null {
  if (n == null || of == null || of === 0) return null;
  return `${Math.round((n / of) * 100)}%`;
}

/** Patients per year over the inclusive year window; null when the count is suppressed. */
export function accrualPerYear(patients: number | null, years: readonly [number, number] | null): number | null {
  if (patients == null || years == null) return null;
  return patients / (Math.abs(years[1] - years[0]) + 1);
}

/** Patients a year for display: one decimal below 10, whole numbers (with separators) from 10. */
export function fmtPerYear(perYear: number): string {
  const tenth = Math.round(perYear * 10) / 10;
  return tenth < 10 ? tenth.toFixed(1) : Math.round(perYear).toLocaleString("en-US");
}

/** True when the definition has no population value, no year window and no criteria. */
export function isEmptyDefinition(d: Definition): boolean {
  return d.criteria.length === 0 && d.population.years == null && POP_DIMS.every((k) => d.population[k].length === 0);
}

/** Synthetic example cohorts for the guided start: generic public terms, shown by name and label only (no counts). */
export const EXAMPLES: Definition[] = [
  {...EMPTY, name: "EGFR-mutant lung cancer", population: {...EMPTY.population, oncotree: ["NSCLC"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "alteration", gene: ["EGFR"], aa: [], class: ["mutation"], tier: []}]},
  {...EMPTY, name: "KRAS-mutant pancreatic cancer", population: {...EMPTY.population, oncotree: ["PAAD"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "alteration", gene: ["KRAS"], aa: [], class: ["mutation"], tier: []}]},
  {...EMPTY, name: "MSI-high colorectal cancer", population: {...EMPTY.population, oncotree: ["COADREAD"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "biomarker", name: "MSI", call: ["high"], at_least: null}]},
  {...EMPTY, name: "BRAF-mutant melanoma", population: {...EMPTY.population, oncotree: ["MEL"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "alteration", gene: ["BRAF"], aa: [], class: ["mutation"], tier: []}]},
];

/** Bar length in percent of `max` (the largest shown count, 0 if none is shown). A suppressed count is
 *  drawn as if it were `minCell`, so it is never longer than a shown bar of `minCell` or more; 0 is no
 *  bar. With nothing shown there is no scale, so a suppressed bar is the 2% stub. */
export function barPct(n: number | null, max: number, minCell: number): number {
  if (n === 0) return 0;
  if (max <= 0) return 2;
  return Math.min(100, Math.max(2, ((n ?? minCell) / max) * 100));
}

/** Every year from the first listed to the last: `row` is null for a year the API did not list (no patients). */
export function yearSlots(byYear: readonly YearCount[]): {year: number; row: YearCount | null}[] {
  if (byYear.length === 0) return [];
  const at = new Map(byYear.map((y) => [y.year, y]));
  const years = byYear.map((y) => y.year);
  const first = Math.min(...years);
  return Array.from({length: Math.max(...years) - first + 1}, (_, i) => ({year: first + i, row: at.get(first + i) ?? null}));
}

export const TIERS = [
  {min: 50, name: "High", desc: "≥ 50 patients/yr: observational cohorts, outcomes linkage, biomarker-stratified trials"},
  {min: 10, name: "Moderate", desc: "10–49 patients/yr: multi-year retrospective cohorts; prospective accrual takes 2–4 years"},
  {min: 0, name: "Low / pilot", desc: "< 10 patients/yr: case series or pilot work; consider multi-site"},
];

export const tierFor = (perYear: number): (typeof TIERS)[number] => TIERS.find((t) => perYear >= t.min) ?? TIERS[2];

// --- labels --------------------------------------------------------------------------------------

export const EVIDENCE: Record<string, string> = {
  caris_level1: "Caris level 1 therapy",
  fmi_fda_any_indication: "FMI FDA-approved therapy (any indication)",
  fmi_trial: "FMI trial match",
};
const TIER_NAMES: Record<string, string> = {
  pathogenic: "pathogenic", likely_pathogenic: "likely pathogenic", vus: "VUS", unclassified: "unclassified",
};
const DEFAULT_TIERS = ["likely_pathogenic", "pathogenic"];

export function populationLabel(p: Population): string {
  const parts: string[] = POP_DIMS.flatMap((d) => (p[d].length ? [p[d].join(", ")] : []));
  if (p.years) parts.push(`${p.years[0]}–${p.years[1]}`);
  return parts.length ? parts.join(" · ") : "All patients";
}

function tierSuffix(tier: string[]): string {
  const have = new Set(tier);
  if (have.size === 0 || (have.size === 2 && DEFAULT_TIERS.every((t) => have.has(t)))) return "";
  if (DEFAULT_TIERS.every((t) => have.has(t))) return ` + ${tier.filter((t) => !DEFAULT_TIERS.includes(t)).map((t) => TIER_NAMES[t]).join(" + ")}`;
  return ` (${tier.map((t) => TIER_NAMES[t]).join(", ")} only)`;
}

export const DATA_LABELS: Record<string, string> = {
  wts: "whole-transcriptome sequencing", liquid: "liquid biopsy", tissue: "tissue testing",
  both_vendors: "testing by both Caris and FMI", serial: "serial reports (two or more)",
};
/** `data` has values that are per report; the other two are per patient. */
export const REPORT_DATA = ["wts", "liquid", "tissue"];

export const DATA_ENTRIES: Option[] = Object.keys(DATA_LABELS).map((value) => ({field: "data.has", parent: null, value}));
export const dataEntries = (q: string): Option[] =>
  q.trim() === "" ? [] : DATA_ENTRIES.filter((e) => DATA_LABELS[e.value].toLowerCase().includes(q.trim().toLowerCase()));

/** s with its first letter upper-cased, for a label that stands alone (a card heading). */
export const capitalise = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** Vocabulary entries a definition of this scope can add: report scope drops per-patient data. */
export function forScope(entries: Option[], scope: Definition["scope"]): Option[] {
  return scope === "report" ? entries.filter((e) => e.field !== "data.has" || REPORT_DATA.includes(e.value)) : entries;
}

const VENDOR_NAMES = {caris: "Caris", fmi: "FMI"} as const;

export function criterionLabel(c: Criterion | Leaf | SeqMember): string {
  const mode = "mode" in c ? c.mode : "include";
  if (mode === "tested_negative" && c.kind === "alteration") return `${c.gene.join(" and ")} tested negative${vendorSuffix(c)}`;
  const label = criterionBody(c);
  return mode === "exclude" ? `no ${label}` : label;
}

const vendorSuffix = (c: Criterion | Leaf | SeqMember): string => "vendor" in c && c.vendor ? ` (${VENDOR_NAMES[c.vendor]})` : "";

/** What the criterion matches, without the mode word ("no", "tested negative"): the funnel row supplies its own prefix. */
export const criterionBody = (c: Criterion | Leaf | SeqMember): string => baseLabel(c) + vendorSuffix(c);

/** An example card's second line: its population, then each criterion, e.g. "NSCLC + EGFR mutation". */
export const exampleLabel = (d: Definition): string =>
  [populationLabel(d.population), ...d.criteria.map(criterionLabel)].join(" + ");

function baseLabel(c: Criterion | Leaf | SeqMember): string {
  switch (c.kind) {
    case "alteration": {
      // every listed gene must be negative (AND); for include/exclude any one gene is enough (OR)
      const genes = c.gene.join("mode" in c && c.mode === "tested_negative" ? " and " : " or ");
      const what = c.aa.length ? c.aa.join("/") : c.class.length ? c.class.join("/") : "alteration";
      return `${genes} ${what}${tierSuffix(c.tier)}`;
    }
    case "biomarker":
      if (c.at_least != null) return `${c.name} ≥ ${c.at_least}`;
      return c.call.length ? `${c.name} ${c.call.join("/")}` : `${c.name} tested`;
    case "ihc": {
      const m = c.clone ? `${c.marker} (${c.clone})` : c.marker;
      if (c.call.length) return `${m} ${c.call.join("/")}`;
      if (c.measure) return c.at_least != null ? `${m} ${c.measure} ≥ ${c.at_least}` : `${m} ${c.measure} measured`;
      return `${m} tested`;
    }
    case "expression": {
      const g = c.gene.join(" or ");
      return c.percentile_at_least != null ? `${g} ≥ ${c.percentile_at_least}th percentile` : `${g} expression measured`;
    }
    case "specimen": {
      const parts = [c.site_type.join("/"), c.site.join("/")].filter(Boolean);
      if (c.purity_at_least != null) parts.push(`purity ≥ ${c.purity_at_least}%`);
      return parts.join(" · ");
    }
    case "actionability":
      return c.evidence.map((e) => EVIDENCE[e] ?? e).join(" or ");
    case "any_of":
      return c.of.map(criterionLabel).join(" or ");
    case "data":
      return DATA_LABELS[c.has] ?? c.has;
    case "sequence":
      return `${c.first.map(criterionLabel).join(" and ")}, then later ${c.then.map(criterionLabel).join(" and ")}`;
  }
}

/** The modes a criterion may take: tested negative needs an alteration without a protein change, of class mutation or any. */
export function modesFor(c: Criterion): Mode[] {
  if (c.kind === "sequence") return ["include"];
  if (c.kind === "alteration" && c.aa.length === 0 && (c.class.length === 0 || (c.class.length === 1 && c.class[0] === "mutation"))) {
    return ["include", "exclude", "tested_negative"];
  }
  return ["include", "exclude"];
}

const FIELD_LABELS: Record<string, string> = {
  "population.oncotree": "Tumor type (OncoTree)", "population.organ": "Organ system", "population.sex": "Sex",
  "population.age_band": "Age band", "population.vendor": "Vendor", "population.assay_class": "Assay class",
  "data.has": "Data available",
  "biomarker.name": "Biomarker", "alteration.gene": "Gene", "ihc.marker": "IHC marker", "ihc.clone": "IHC clone", "expression.gene": "Expression (gene)",
  "specimen.site_type": "Specimen site type", "specimen.site": "Specimen site", "actionability.evidence": "Actionability",
};

/** The field label shown beside a vocabulary option, e.g. "KRAS protein change". */
export function fieldLabel(e: Option): string {
  if (e.field === "alteration.aa") return `${e.parent ?? ""} protein change`.trim();
  if (e.field === "biomarker.call") return `${e.parent ?? "Biomarker"} call`;
  if (e.field === "ihc.call") return `${e.parent ?? "IHC"} call`;
  if (e.field === "ihc.clone") return `${e.parent ?? "IHC"} clone`;
  return FIELD_LABELS[e.field] ?? e.field;
}

/** The plain-language kind badge that leads a typeahead option row. */
export const KIND_LABELS: Record<string, string> = {
  "population.oncotree": "Tumor type", "population.organ": "Organ system", "population.sex": "Sex",
  "population.age_band": "Age band", "population.vendor": "Vendor", "population.assay_class": "Assay",
  "data.has": "Data available", "biomarker.name": "Biomarker", "biomarker.call": "Biomarker",
  "alteration.gene": "Gene alteration", "alteration.aa": "Gene alteration",
  "ihc.marker": "IHC", "ihc.call": "IHC", "ihc.clone": "IHC", "expression.gene": "RNA expression",
  "specimen.site_type": "Specimen", "specimen.site": "Specimen", "actionability.evidence": "Actionability",
};

export const kindLabel = (e: Option): string => KIND_LABELS[e.field] ?? e.field;

/** An option's value as its row reads it: with its parent where the value alone is ambiguous, and plain words for codes. */
export function optionText(e: Option): string {
  const p = e.parent ? `${e.parent} ` : "";
  switch (e.field) {
    case "alteration.aa": case "biomarker.call": case "ihc.call": return `${p}${e.value}`;
    case "ihc.clone": return `${p}clone ${e.value}`;
    case "actionability.evidence": return EVIDENCE[e.value] ?? e.value;
    case "data.has": return capitalise(DATA_LABELS[e.value] ?? e.value);
    default: return e.value;
  }
}

/** A card's heading: criterionLabel without the "no" of an exclusion (the mode badge says Exclude), capitalised. */
export const cardLabel = (c: Criterion): string =>
  capitalise(criterionLabel(c.mode === "exclude" ? ({...c, mode: "include"} as Criterion) : c));

/** Static "Biomarker TMB/MSI/LOH" typeahead entries: the vocabulary holds calls, not biomarker names. */
export const BIOMARKERS = ["TMB", "MSI", "LOH"] as const;
export const biomarkerEntries = (q: string): Option[] =>
  BIOMARKERS.filter((b) => q.trim() !== "" && b.toLowerCase().startsWith(q.trim().toLowerCase()))
    .map((b) => ({field: "biomarker.name", parent: null, value: b}));

// --- pivot axes ----------------------------------------------------------------------------------

const DIM_AXES = [...BREAKDOWN_DIMS, {value: "year", label: "Year of first qualifying report"}];

// Labels of a criterion's key / sub / val columns in mart.fact; "" = the kind has no such column.
const AXIS_COLUMNS: Record<string, [string, string, string]> = {
  alteration: ["gene", "alteration class", "protein change or fusion partner"],
  biomarker: ["biomarker", "", "call"],
  ihc: ["marker", "clone", "call"],
  expression: ["gene", "", ""],
  actionability: ["evidence", "gene", "therapy or trial"],
  any_of: ["finding", "detail", "value"],
};

export function pivotAxes(d: Definition): {value: string; label: string}[] {
  const axes: {value: string; label: string}[] = DIM_AXES.map((a) => ({...a}));
  for (const c of d.criteria) {
    if (!c.id || c.mode !== "include" || c.kind === "data" || c.kind === "sequence" || c.kind === "specimen" || (c.kind === "any_of" && c.of.some((m) => m.kind === "specimen"))) continue;
    AXIS_COLUMNS[c.kind].forEach((col, i) => {
      if (col) axes.push({value: `${c.id}.${["key", "sub", "val"][i]}`, label: `${c.id} · ${criterionLabel(c)} · ${col}`});
    });
  }
  return axes;
}

// --- vocabulary entry -> action --------------------------------------------------------------------

/** A vocabulary entry as a new criterion (id left to add_criterion); null for population values. */
export function newCriterion(e: Option): Criterion | null {
  const base = {id: null, mode: "include", vendor: null} as const;
  const parent = e.parent ?? "";
  switch (e.field) {
    case "data.has":
      return {...base, kind: "data", has: e.value as Extract<Criterion, {kind: "data"}>["has"]};
    case "alteration.gene":
      return {...base, kind: "alteration", gene: [e.value], aa: [], class: [], tier: []};
    case "alteration.aa":
      return {...base, kind: "alteration", gene: [parent], aa: [e.value], class: ["mutation"], tier: []};
    case "biomarker.name":
      return {...base, kind: "biomarker", name: e.value as "TMB" | "MSI" | "LOH", call: [], at_least: null};
    case "biomarker.call":
      return {...base, kind: "biomarker", name: parent as "TMB" | "MSI" | "LOH", call: [e.value], at_least: null};
    case "ihc.marker":
      return {...base, kind: "ihc", marker: e.value, clone: null, call: [], measure: null, at_least: null};
    case "ihc.call":
      return {...base, kind: "ihc", marker: parent, clone: null, call: [e.value], measure: null, at_least: null};
    case "ihc.clone":
      return {...base, kind: "ihc", marker: parent, clone: e.value, call: [], measure: null, at_least: null};
    case "expression.gene":
      return {...base, kind: "expression", gene: [e.value], percentile_at_least: null};
    case "specimen.site_type":
      return {...base, kind: "specimen", site_type: [e.value], site: [], purity_at_least: null};
    case "specimen.site":
      return {...base, kind: "specimen", site_type: [], site: [e.value], purity_at_least: null};
    case "actionability.evidence":
      return {...base, kind: "actionability", evidence: [e.value as "caris_level1" | "fmi_fda_any_indication" | "fmi_trial"]};
    default:
      return null;
  }
}

/** The population with a population.* entry's value added; null for any other entry. */
export function addToPopulation(p: Population, e: Option): Population | null {
  const dim = e.field.replace(/^population\./, "") as PopDim;
  if (!e.field.startsWith("population.") || !POP_DIMS.includes(dim)) return null;
  return p[dim].includes(e.value) ? p : {...p, [dim]: [...p[dim], e.value]};
}

// --- versions and share link -----------------------------------------------------------------------

/** Append d as the newest version (numbers keep counting past MAX_VERSIONS) and make it current. */
export function pushVersion(h: History, d: Definition): History {
  const n = (h.versions.at(-1)?.n ?? 0) + 1;
  const versions = [...h.versions, {n, definition: d}].slice(-MAX_VERSIONS);
  return {versions, current: versions.length - 1};
}

export function shareHash(d: Definition): string {
  const bin = String.fromCharCode(...new TextEncoder().encode(JSON.stringify(d)));
  return `#d=${btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "")}`;
}

/** The JSON a share hash holds, or null; the server validates it. */
export function readShareHash(hash: string): unknown | null {
  if (!hash.startsWith("#d=")) return null;
  try {
    const b64 = hash.slice(3).replaceAll("-", "+").replaceAll("_", "/");
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
  } catch {
    return null;
  }
}

// --- combobox keys ---------------------------------------------------------------------------------

export interface ComboState { open: boolean; active: number }

export function comboKey(state: ComboState, key: string, count: number): ComboState & {pick: boolean} {
  const s = {...state, pick: false};
  if (count === 0 && key !== "Escape") return s;
  switch (key) {
    case "ArrowDown": return {open: true, active: state.open ? (state.active + 1) % count : 0, pick: false};
    case "ArrowUp": return {open: true, active: state.open ? (state.active - 1 + count) % count : count - 1, pick: false};
    case "Home": return {open: true, active: 0, pick: false};
    case "End": return {open: true, active: count - 1, pick: false};
    case "Enter": return state.open ? {open: false, active: state.active, pick: true} : s;
    case "Escape": return {open: false, active: 0, pick: false};
    default: return s;
  }
}

// --- feasibility statement -----------------------------------------------------------------------

/** One paragraph for a grant's feasibility section. Every number comes from the result, the window or the definition. */
export function feasibility(d: Definition, r: CountResult, years: readonly [number, number] | null): string {
  // A null count says nothing about its size: it is under min_cell or could be worked out by subtraction.
  const n = (x: number | null | undefined, suppressed: string) => (x == null ? suppressed : fmtCount(x));
  const window = years ? `Between ${years[0]} and ${years[1]},` : "To date,";
  const pop = populationLabel(d.population);
  const perYear = accrualPerYear(r.patients, years);
  let text = `${window} the UCCC sequenced ${n(r.denominator, "a suppressed number of")} patients${pop === "All patients" ? "" : ` in ${pop}`}`;
  if (d.criteria.length) text += `, of whom ${n(r.patients, "a suppressed number")} met: ${d.criteria.map(criterionLabel).join("; ")}`;
  if (perYear != null) text += ` (about ${perYear.toFixed(1)} a year)`;
  text += ".";
  if (d.scope === "report") text += " Every criterion was met on the same report.";
  if (years) text += " Collection dates are shifted for de-identification, so the last years are partial.";
  text += ` Counts are distinct de-identified patients from Caris and FMI reports; counts under ${r.min_cell}, and counts that would let one be worked out by subtraction, are not shown. ${r.notes.join(" ")}`;
  return text;
}
