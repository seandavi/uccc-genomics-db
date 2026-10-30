import { describe, expect, test } from "bun:test";
import {
  DATA_ENTRIES, EMPTY, KIND_LABELS, MAX_VERSIONS, accrualPerYear, addToPopulation, barPct, capitalise, cardLabel, comboKey, criterionLabel, dataEntries,
  feasibility, fmtCount, fmtPerYear, forScope, isEmptyDefinition, kindLabel, modesFor, newCriterion, optionText, pct, pivotAxes, populationLabel, pushVersion, readShareHash, shareHash, tierFor, yearSlots,
  type History,
} from "./cohort.ts";
import type { CountResult, Criterion, Definition, Option, Population } from "./types.ts";

const opt = (field: string, value: string, parent: string | null = null): Option => ({field, parent, value});
const alt = (over: object = {}) => ({kind: "alteration", id: "c1", mode: "include", gene: ["KRAS"], aa: [], class: [], tier: ["likely_pathogenic", "pathogenic"], ...over}) as Criterion;
const bio = (over: object = {}) => ({kind: "biomarker", id: "c1", mode: "include", name: "MSI", call: [], at_least: null, ...over}) as Criterion;
const ihc = (over: object = {}) => ({kind: "ihc", id: "c1", mode: "include", marker: "ER", clone: null, call: [], measure: null, at_least: null, ...over}) as Criterion;
const defn = (criteria: Criterion[]): Definition => ({...EMPTY, criteria});

describe("numbers", () => {
  test("barPct: a suppressed bar is never longer than a shown bar of min_cell or more", () => {
    for (const max of [5, 10, 400, 10000])
      for (const m of [5, 10])
        for (let n = m; n <= Math.max(max, m); n += Math.max(1, Math.floor(max / 50))) {
          expect(barPct(null, max, m)).toBeLessThanOrEqual(barPct(n, max, m));
          expect(barPct(n, max, m)).toBeLessThanOrEqual(100);
        }
    expect(barPct(null, 50, 5)).toBe(10);
    expect(barPct(0, 50, 5)).toBe(0);
    expect(barPct(3, 10000, 5)).toBe(2);
  });
  test("yearSlots fills the gaps between the first and last year only", () => {
    const y = (year: number) => ({year, patients: 6, complete: true});
    expect(yearSlots([])).toEqual([]);
    const slots = yearSlots([y(2020), y(2022)]);
    expect(slots.map((s) => s.year)).toEqual([2020, 2021, 2022]);
    expect(slots.map((s) => s.row === null)).toEqual([false, true, false]);
    expect(yearSlots([y(2022), y(2020)])).toEqual(slots);
    expect(yearSlots([y(2021)]).length).toBe(1);
  });
  test("fmtCount", () => {
    expect(fmtCount(null)).toBe("<5");
    expect(fmtCount(undefined)).toBe("<5");
    expect(fmtCount(0)).toBe("0");
    expect(fmtCount(1234)).toBe("1,234");
    expect(fmtCount(null, 10)).toBe("<10");
  });
  test("pct", () => {
    expect(pct(null, 10)).toBeNull();
    expect(pct(4, null)).toBeNull();
    expect(pct(4, 0)).toBeNull();
    expect(pct(4, 10)).toBe("40%");
    expect(pct(1, 3)).toBe("33%");
    expect(pct(0, 10)).toBe("0%");
  });
  test("fmtPerYear", () => {
    expect([2, 9.94, 9.96, 30, 1234.4].map(fmtPerYear)).toEqual(["2.0", "9.9", "10", "30", "1,234"]);
  });
  test("isEmptyDefinition", () => {
    expect(isEmptyDefinition(EMPTY)).toBe(true);
    for (const same of [{name: "x"}, {scope: "report"}, {breakdown: ["sex"]}, {pivot: {rows: "year", cols: "sex"}}])
      expect(isEmptyDefinition({...EMPTY, ...same} as Definition)).toBe(true);
    expect(isEmptyDefinition({...EMPTY, population: {...EMPTY.population, oncotree: ["NSCLC"]}})).toBe(false);
    expect(isEmptyDefinition({...EMPTY, population: {...EMPTY.population, years: [2024, 2025]}})).toBe(false);
    expect(isEmptyDefinition(defn([alt()]))).toBe(false);
  });
  test("accrualPerYear and tierFor", () => {
    expect(accrualPerYear(null, [2023, 2026])).toBeNull();
    expect(accrualPerYear(120, [2023, 2026])).toBe(30);
    expect(accrualPerYear(120, null)).toBeNull();
    expect(tierFor(60).name).toBe("High");
    expect(tierFor(10).name).toBe("Moderate");
    expect(tierFor(0).name).toBe("Low / pilot");
  });
});

describe("labels", () => {
  test("populationLabel", () => {
    expect(populationLabel(EMPTY.population)).toBe("All patients");
    const p: Population = {...EMPTY.population, oncotree: ["NSCLC"], sex: ["female"], years: [2023, 2026]};
    expect(populationLabel(p)).toBe("NSCLC · female · 2023–2026");
  });
  test("criterionLabel by kind", () => {
    expect(criterionLabel(alt({aa: ["G12C"], class: ["mutation"]}))).toBe("KRAS G12C");
    expect(criterionLabel(alt({gene: ["KRAS", "NRAS"], class: ["mutation"]}))).toBe("KRAS or NRAS mutation");
    expect(criterionLabel(alt({gene: ["ERBB2"], class: ["amplification"]}))).toBe("ERBB2 amplification");
    expect(criterionLabel(alt({gene: ["ALK"], class: ["fusion"], tier: ["likely_pathogenic", "pathogenic", "vus"]}))).toBe("ALK fusion + VUS");
    expect(criterionLabel(bio({call: ["high"]}))).toBe("MSI high");
    expect(criterionLabel(bio({name: "TMB", at_least: 10}))).toBe("TMB ≥ 10");
    expect(criterionLabel(bio({name: "LOH"}))).toBe("LOH tested");
    expect(criterionLabel(ihc({marker: "PD-L1", clone: "22c3", measure: "TPS", at_least: 50}))).toBe("PD-L1 (22c3) TPS ≥ 50");
    expect(criterionLabel(ihc({call: ["positive"]}))).toBe("ER positive");
    expect(criterionLabel(ihc({marker: "CLDN18"}))).toBe("CLDN18 tested");
    expect(criterionLabel({kind: "expression", gene: ["TACSTD2"], percentile_at_least: 75, mode: "include"} as Criterion)).toBe("TACSTD2 ≥ 75th percentile");
    expect(criterionLabel({kind: "expression", gene: ["TACSTD2"], percentile_at_least: null, mode: "include"} as Criterion)).toBe("TACSTD2 expression measured");
    expect(criterionLabel({kind: "specimen", site_type: ["metastatic"], site: ["liver"], purity_at_least: 30, mode: "include"} as Criterion)).toBe("metastatic · liver · purity ≥ 30%");
    expect(criterionLabel({kind: "actionability", evidence: ["caris_level1"], mode: "include"} as Criterion)).toBe("Caris level 1 therapy");
    expect(criterionLabel({kind: "actionability", evidence: ["fmi_fda_any_indication"], mode: "include"} as Criterion)).toBe("FMI FDA-approved therapy (any indication)");
    expect(criterionLabel({kind: "actionability", evidence: ["fmi_trial"], mode: "include"} as Criterion)).toBe("FMI trial match");
  });
  test("criterionLabel any_of joins members", () => {
    const c = {kind: "any_of", id: "c2", mode: "include", of: [bio({call: ["high"]}), alt({gene: ["ERBB2"], class: ["amplification"]})]} as Criterion;
    expect(criterionLabel(c)).toBe("MSI high or ERBB2 amplification");
  });
  test("criterionLabel for modes, data, sequence and vendor", () => {
    expect(criterionLabel(alt({mode: "exclude", gene: ["STK11", "KEAP1"]}))).toBe("no STK11 or KEAP1 alteration");
    expect(criterionLabel(alt({mode: "tested_negative", gene: ["KRAS", "NRAS"]}))).toBe("KRAS and NRAS tested negative");
    expect(criterionLabel(alt({mode: "tested_negative", gene: ["KRAS"], vendor: "fmi"}))).toBe("KRAS tested negative (FMI)");
    expect(criterionLabel(alt({vendor: "caris", class: ["mutation"]}))).toBe("KRAS mutation (Caris)");
    expect(criterionLabel(bio({name: "TMB", vendor: "fmi", mode: "exclude"}))).toBe("no TMB tested (FMI)");
    expect(criterionLabel({kind: "data", id: "c1", mode: "include", has: "liquid", vendor: null} as Criterion)).toBe("liquid biopsy");
    expect(criterionLabel({kind: "data", id: "c1", mode: "exclude", has: "both_vendors", vendor: null} as Criterion)).toBe("no testing by both Caris and FMI");
    const seq = {kind: "sequence", id: "c1", mode: "include",
      first: [{kind: "data", mode: "include", has: "tissue", vendor: null}],
      then: [{kind: "data", mode: "include", has: "liquid", vendor: "caris"}, alt({id: null, class: ["mutation"]})]} as Criterion;
    expect(criterionLabel(seq)).toBe("tissue testing, then later liquid biopsy (Caris) and KRAS mutation");
  });
});

describe("modes and data entries", () => {
  test("modesFor", () => {
    expect(modesFor(alt())).toEqual(["include", "exclude", "tested_negative"]);
    expect(modesFor(alt({class: ["mutation"]}))).toEqual(["include", "exclude", "tested_negative"]);
    expect(modesFor(alt({aa: ["G12C"], class: ["mutation"]}))).toEqual(["include", "exclude"]);
    expect(modesFor(alt({class: ["fusion"]}))).toEqual(["include", "exclude"]);
    expect(modesFor(ihc())).toEqual(["include", "exclude"]);
    expect(modesFor({kind: "sequence", id: "c1", mode: "include", first: [], then: []} as unknown as Criterion)).toEqual(["include"]);
  });
  test("dataEntries", () => {
    expect(DATA_ENTRIES.map((e) => e.value)).toEqual(["wts", "liquid", "tissue", "both_vendors", "serial"]);
    expect(dataEntries("liquid").map((e) => e.value)).toEqual(["liquid"]);
    expect(dataEntries("TRANSCRIPTOME").map((e) => e.value)).toEqual(["wts"]);
    expect(dataEntries("  ")).toEqual([]);
    expect(dataEntries("zzz")).toEqual([]);
  });
  test("capitalise", () => {
    expect(capitalise("liquid biopsy")).toBe("Liquid biopsy");
    expect(capitalise("")).toBe("");
  });
  test("forScope drops per-patient data entries at report scope only", () => {
    const entries = [...DATA_ENTRIES, opt("alteration.gene", "KRAS")];
    expect(forScope(entries, "report").map((e) => e.value)).toEqual(["wts", "liquid", "tissue", "KRAS"]);
    expect(forScope(entries, "patient")).toEqual(entries);
  });
});

describe("feasibility", () => {
  const result = (over: Partial<CountResult> = {}): CountResult => ({
    cohort_id: "abc", patients: 48, reports: 50, denominator: 1200, min_cell: 5, funnel: [], loosen: [], loosen_offered: true,
    by_year: [], breakdowns: {}, notes: ["Stage and treatment are not in the data."], ...over,
  });
  const d = {...EMPTY, population: {...EMPTY.population, oncotree: ["NSCLC"]}, criteria: [alt({class: ["mutation"]}), bio({name: "TMB", at_least: 10})]};
  /** The digit runs of the statement, without its fixed policy sentence and the API's notes (which hold digits of their own). */
  const numbers = (text: string, r: CountResult) =>
    text.replace(/ Counts are distinct.*$/, "").replace(r.notes.join(" "), "").match(/\d+(?:,\d{3})*(?:\.\d+)?/g) ?? [];

  test("says what the result says", () => {
    const text = feasibility(d, result(), [2020, 2024]);
    expect(text.startsWith("Between 2020 and 2024, the UCCC sequenced 1,200 patients in NSCLC, of whom 48 met: KRAS mutation; TMB ≥ 10 (about 9.6 a year).")).toBe(true);
    expect(text).toContain("Stage and treatment are not in the data.");
  });
  test("every number is from the result, the years or the definition", () => {
    const r = result();
    // 1,200 and 48 are in the result, 2020 and 2024 the window, 10 the TMB cut point, 9.6 = 48 / 5 years.
    expect(numbers(feasibility(d, r, [2020, 2024]), r)).toEqual(["2020", "2024", "1,200", "48", "10", "9.6"]);
  });
  test("a suppressed count claims no size and has no number", () => {
    const r = result({patients: null, denominator: null});
    const text = feasibility({...d, criteria: [alt({class: ["mutation"]})]}, r, null);
    expect(text.startsWith("To date, the UCCC sequenced a suppressed number of patients in NSCLC, of whom a suppressed number met: KRAS mutation.")).toBe(true);
    expect(text).not.toContain("fewer than");
    expect(text).toContain("counts under 5, and counts that would let one be worked out by subtraction, are not shown.");
    expect(numbers(text, r)).toEqual([]);
  });
  test("no criteria: no 'of whom' clause; report scope is stated", () => {
    const r = result();
    const text = feasibility({...EMPTY}, r, [2020, 2024]);
    expect(text.startsWith("Between 2020 and 2024, the UCCC sequenced 1,200 patients (about 9.6 a year).")).toBe(true);
    expect(text).not.toContain("of whom");
    expect(feasibility({...d, scope: "report"}, r, null)).toContain(". Every criterion was met on the same report.");
    expect(text).not.toContain("same report");
  });
});

describe("newCriterion and addToPopulation", () => {
  const rows: [Option, object][] = [
    [opt("alteration.gene", "KRAS"), {kind: "alteration", gene: ["KRAS"], aa: [], class: [], tier: []}],
    [opt("alteration.aa", "G12C", "KRAS"), {kind: "alteration", gene: ["KRAS"], aa: ["G12C"], class: ["mutation"], tier: []}],
    [opt("biomarker.name", "TMB"), {kind: "biomarker", name: "TMB", call: [], at_least: null}],
    [opt("biomarker.call", "high", "MSI"), {kind: "biomarker", name: "MSI", call: ["high"], at_least: null}],
    [opt("ihc.marker", "PD-L1"), {kind: "ihc", marker: "PD-L1", clone: null, call: [], measure: null, at_least: null}],
    [opt("ihc.call", "positive", "ER"), {kind: "ihc", marker: "ER", clone: null, call: ["positive"], measure: null, at_least: null}],
    [opt("ihc.clone", "22c3", "PD-L1"), {kind: "ihc", marker: "PD-L1", clone: "22c3", call: [], measure: null, at_least: null}],
    [opt("expression.gene", "TACSTD2"), {kind: "expression", gene: ["TACSTD2"], percentile_at_least: null}],
    [opt("specimen.site_type", "metastatic"), {kind: "specimen", site_type: ["metastatic"], site: [], purity_at_least: null}],
    [opt("specimen.site", "liver"), {kind: "specimen", site_type: [], site: ["liver"], purity_at_least: null}],
    [opt("actionability.evidence", "fmi_trial"), {kind: "actionability", evidence: ["fmi_trial"]}],
  ];
  for (const [e, expected] of rows) {
    test(`${e.field} -> criterion`, () => {
      expect(newCriterion(e)).toEqual({id: null, mode: "include", vendor: null, ...expected} as Criterion);
    });
  }
  test("data.has -> a data criterion", () => {
    expect(newCriterion(opt("data.has", "serial"))).toEqual({id: null, mode: "include", vendor: null, kind: "data", has: "serial"} as Criterion);
  });
  test("population entries are not criteria", () => {
    expect(newCriterion(opt("population.sex", "female"))).toBeNull();
  });
  test("addToPopulation", () => {
    const p = EMPTY.population;
    const once = addToPopulation(p, opt("population.oncotree", "NSCLC"))!;
    expect(once.oncotree).toEqual(["NSCLC"]);
    expect(addToPopulation(once, opt("population.oncotree", "NSCLC"))).toEqual(once);
    expect(addToPopulation(once, opt("population.sex", "female"))!.sex).toEqual(["female"]);
    expect(addToPopulation(p, opt("alteration.gene", "KRAS"))).toBeNull();
    expect(addToPopulation(p, opt("population.nope", "x"))).toBeNull();
  });
});

describe("pivotAxes", () => {
  test("nine dimensions and nothing else for an empty cohort", () => {
    const a = pivotAxes(EMPTY);
    expect(a.map((x) => x.value)).toEqual(["oncotree", "organ", "sex", "age_band", "vendor", "assay_class", "site_type", "has_wts", "year"]);
  });
  test("criterion axes by kind; none for specimen or any_of holding one", () => {
    const spec = {kind: "specimen", id: "c3", mode: "include", site_type: ["metastatic"], site: [], purity_at_least: null} as Criterion;
    const anySpec = {kind: "any_of", id: "c4", mode: "include", of: [spec, bio()]} as Criterion;
    const d = defn([alt({id: "c1"}), bio({id: "c2", call: ["high"]}), spec, anySpec, ihc({id: "c5", marker: "PD-L1", clone: "22c3", measure: "TPS", at_least: 50})]);
    const values = pivotAxes(d).slice(9).map((x) => x.value);
    expect(values).toEqual(["c1.key", "c1.sub", "c1.val", "c2.key", "c2.val", "c5.key", "c5.sub", "c5.val"]);
    const label = pivotAxes(d).find((x) => x.value === "c5.sub")!.label;
    expect(label).toBe("c5 · PD-L1 (22c3) TPS ≥ 50 · clone");
  });
  test("no axes for negated, data or sequence criteria", () => {
    const data = {kind: "data", id: "c3", mode: "include", has: "wts", vendor: null} as Criterion;
    const seq = {kind: "sequence", id: "c4", mode: "include", first: [data], then: [data]} as unknown as Criterion;
    const d = defn([alt({id: "c1", mode: "exclude"}), bio({id: "c2", mode: "tested_negative"}), data, seq, ihc({id: "c5"})]);
    expect(pivotAxes(d).slice(9).map((x) => x.value)).toEqual(["c5.key", "c5.sub", "c5.val"]);
  });
  test("an any_of without specimen offers finding/detail/value", () => {
    const c = {kind: "any_of", id: "c1", mode: "include", of: [bio(), bio({name: "LOH"})]} as Criterion;
    expect(pivotAxes(defn([c])).slice(9).map((x) => x.value)).toEqual(["c1.key", "c1.sub", "c1.val"]);
  });
});

describe("versions", () => {
  test("pushVersion numbers and points at the newest", () => {
    let h: History = {versions: [{n: 1, definition: EMPTY}], current: 0};
    h = pushVersion(h, {...EMPTY, name: "a"});
    expect(h.versions.map((v) => v.n)).toEqual([1, 2]);
    expect(h.current).toBe(1);
    h = {...h, current: 0};   // stepped back, then edit: appended after the newest
    h = pushVersion(h, {...EMPTY, name: "b"});
    expect(h.versions.map((v) => v.n)).toEqual([1, 2, 3]);
    expect(h.current).toBe(2);
  });
  test("the oldest are dropped past MAX_VERSIONS, numbers kept", () => {
    let h: History = {versions: [{n: 1, definition: EMPTY}], current: 0};
    for (let i = 0; i < MAX_VERSIONS + 4; i++) h = pushVersion(h, EMPTY);
    expect(h.versions.length).toBe(MAX_VERSIONS);
    expect(h.versions.at(-1)!.n).toBe(MAX_VERSIONS + 5);
    expect(h.versions[0].n).toBe(6);
    expect(h.current).toBe(MAX_VERSIONS - 1);
  });
});

describe("share hash", () => {
  test("round trip with a non-ASCII name", () => {
    const d = {...EMPTY, name: "Lungenkrebs · 肺癌 é"};
    const hash = shareHash(d);
    expect(hash.startsWith("#d=")).toBe(true);
    expect(hash.slice(3)).not.toMatch(/[+/=]/);
    expect(readShareHash(hash)).toEqual(d);
  });
  test("unreadable hashes give null", () => {
    expect(readShareHash("#x")).toBeNull();
    expect(readShareHash("")).toBeNull();
    expect(readShareHash("#d=!!!")).toBeNull();
    expect(readShareHash(`#d=${btoa("not json")}`)).toBeNull();
  });
});

describe("comboKey", () => {
  const closed = {open: false, active: 0};
  test("ArrowDown opens, then moves and wraps", () => {
    let s = comboKey(closed, "ArrowDown", 3);
    expect(s).toMatchObject({open: true, active: 0});
    s = comboKey(s, "ArrowDown", 3);
    expect(s.active).toBe(1);
    s = comboKey({open: true, active: 2}, "ArrowDown", 3);
    expect(s.active).toBe(0);
  });
  test("ArrowUp wraps, Home and End jump", () => {
    expect(comboKey({open: true, active: 0}, "ArrowUp", 3).active).toBe(2);
    expect(comboKey({open: true, active: 1}, "End", 3).active).toBe(2);
    expect(comboKey({open: true, active: 2}, "Home", 3).active).toBe(0);
  });
  test("Enter picks while open; Escape closes", () => {
    expect(comboKey({open: true, active: 1}, "Enter", 3)).toEqual({open: false, active: 1, pick: true});
    expect(comboKey(closed, "Enter", 3).pick).toBe(false);
    expect(comboKey({open: true, active: 1}, "Escape", 3).open).toBe(false);
    expect(comboKey({open: true, active: 0}, "Enter", 0).pick).toBe(false);
  });
});

describe("option rows and card labels", () => {
  test("kindLabel and optionText", () => {
    const rows: [Option, string, string][] = [
      [opt("alteration.gene", "KRAS"), "Gene alteration", "KRAS"],
      [opt("expression.gene", "KRAS"), "RNA expression", "KRAS"],
      [opt("alteration.aa", "G12C", "KRAS"), "Gene alteration", "KRAS G12C"],
      [opt("biomarker.call", "high", "MSI"), "Biomarker", "MSI high"],
      [opt("ihc.clone", "22C3", "PD-L1"), "IHC", "PD-L1 clone 22C3"],
      [opt("population.oncotree", "NSCLC"), "Tumor type", "NSCLC"],
      [opt("data.has", "wts"), "Data available", "Whole-transcriptome sequencing"],
      [opt("actionability.evidence", "fmi_trial"), "Actionability", "FMI trial match"],
      [opt("x.unknown", "v"), "x.unknown", "v"],
    ];
    for (const [o, kind, text] of rows) expect([kindLabel(o), optionText(o)]).toEqual([kind, text]);
  });
  test("KIND_LABELS covers every vocabulary field and the two static ones", () => {
    const fields = [
      "population.oncotree", "population.organ", "population.sex", "population.age_band", "population.vendor", "population.assay_class",
      "alteration.gene", "alteration.aa", "biomarker.call", "ihc.marker", "ihc.clone", "ihc.call", "expression.gene",
      "specimen.site_type", "specimen.site", "actionability.evidence", "biomarker.name", "data.has",
    ];
    expect(Object.keys(KIND_LABELS).sort()).toEqual([...fields].sort());
  });
  test("cardLabel drops the no of an exclusion, criterionLabel keeps it", () => {
    const ex = alt({mode: "exclude", gene: ["KEAP1", "STK11"]});
    expect(cardLabel(ex)).toBe("KEAP1 or STK11 alteration");
    expect(criterionLabel(ex)).toBe("no KEAP1 or STK11 alteration");
    expect(cardLabel(alt({mode: "tested_negative"}))).toBe("KRAS tested negative");
    expect(cardLabel({kind: "data", id: "c1", mode: "exclude", vendor: null, has: "both_vendors"} as Criterion)).toBe("Testing by both Caris and FMI");
    expect(cardLabel(alt({class: ["mutation"], tier: []}))).toBe("KRAS mutation");
  });
});
