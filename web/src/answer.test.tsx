import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Answer, type AnswerProps, type Counted, type Tab } from "./Answer.tsx";
import { EMPTY } from "./cohort.ts";
import type { CountResult, Criterion, Definition, PivotResult } from "./types.ts";

const kras = {kind: "alteration", id: "c1", mode: "include", gene: ["KRAS"], aa: ["G12C"], class: ["mutation"], tier: ["likely_pathogenic", "pathogenic"]} as Criterion;
const alk = {kind: "alteration", id: "c2", mode: "include", gene: ["ALK"], aa: [], class: ["fusion"], tier: ["likely_pathogenic", "pathogenic"]} as Criterion;
const def: Definition = {
  ...EMPTY, criteria: [kras, alk], breakdown: ["sex"],
  population: {...EMPTY.population, oncotree: ["NSCLC"]},
};

const result = (over: Partial<CountResult> = {}): CountResult => ({
  cohort_id: "abc", patients: 8, reports: 9, denominator: 120, min_cell: 5,
  funnel: [{criterion: null, patients: 120}, {criterion: "c1", patients: 8}, {criterion: "c2", patients: null}],
  loosen: [], loosen_offered: true, by_year: [{year: 2023, patients: 6, complete: true}, {year: 2024, patients: null, complete: true}, {year: 2025, patients: 3, complete: false}],
  breakdowns: {sex: [{value: "female", patients: 6, denominator: 70}, {value: "male", patients: null, denominator: null}]},
  notes: ["Stage and treatment are not in the data."],
  ...over,
});

const render = (r: CountResult | null, tab: Tab = "Accrual", extra: Partial<AnswerProps> = {}, d: Definition = def,
                p: PivotResult | null = null) =>
  renderToStaticMarkup(<Answer definition={d} answer={r && {d, r, p}} options={{entries: [], years: [2023, 2026], cut_points: {}, min_cell: 5}}
    tab={tab} onTab={() => {}} onOp={() => {}} {...extra} />);

describe("suppressed counts", () => {
  test("null patients renders <5, never 0", () => {
    const html = render(result({patients: null, reports: null, denominator: null}));
    expect(html).toContain('<span class="suppressed"');
    expect(html).toContain("&lt;5");
    expect(html).not.toContain(">0<");
    expect(html).toContain("patient count not shown");
  });
  test("a hidden reports count is never shown as <5 reports", () => {
    const html = render(result({patients: 9, reports: null}));
    expect(html).toContain("reports not shown");
    expect(html).not.toContain("&lt;5</span> reports");
  });
  test("zero renders 0 and a shown count is formatted", () => {
    const html = render(result({patients: 0, reports: 1234}));
    expect(html).toContain(">0<");
    expect(html).toContain("1,234");
  });
  test("min_cell comes from the result", () => {
    expect(render(result({patients: null, min_cell: 10}))).toContain("&lt;10");
  });
  test("a null funnel step is a hatched bar", () => {
    const html = render(result());
    expect(html).toMatch(/class="bar hatched"/);
    expect(html).toContain("∧ ALK fusion");
  });
  test("a known zero is an empty bar, not a hatched one", () => {
    const html = render(result({funnel: [{criterion: null, patients: 0}, {criterion: "c1", patients: 0}]}));
    expect(html).not.toContain('class="bar hatched"');
    expect(html).toContain("width:0%");
  });
});

describe("cards", () => {
  test("share names its denominator; accrual uses the window", () => {
    const html = render(result());
    expect(html).toContain("7%");
    expect(html).toContain("of 120 patients in NSCLC");
    expect(html).toContain("2.0");   // 8 patients over the 4-year options window
    expect(html).toContain("Low / pilot");
  });
  test("the share card's denominator goes through Count; an empty population reads (all patients)", () => {
    const html = render(result({denominator: null}));
    expect(html).toMatch(/of <span class="suppressed"[^>]*>&lt;5<\/span> patients in NSCLC/);
    expect(render(result(), "Accrual", {}, {...def, population: EMPTY.population})).toContain("patients (all patients)");
  });
  test("suppressed share and accrual are dashes", () => {
    const html = render(result({patients: null, denominator: null}));
    expect(html).toContain(">–<");
  });
});

describe("loosen", () => {
  test("suggestions show with a Drop button", () => {
    const html = render(result({patients: null, loosen: [{drop: "c2", patients: 6}]}));
    expect(html).toContain("Too few patients to show.");
    expect(html).toContain("Drop ALK fusion → 6 patients");
    expect(html).toContain(">Drop</button>");
  });
  test("labels come from the counted definition; Drop is disabled while stale", () => {
    const egfr = {...alk, gene: ["EGFR"], aa: [], class: ["mutation"]} as Criterion;
    const edited: Definition = {...def, criteria: [kras, egfr]};
    const counted: Counted = {d: def, r: result({patients: null, loosen: [{drop: "c2", patients: 6}]}), p: null};
    const html = renderToStaticMarkup(<Answer definition={edited} answer={counted} options={null} tab="Accrual" onTab={() => {}} onOp={() => {}} />);
    expect(html).toContain("∧ ALK fusion");
    expect(html).not.toContain("EGFR");
    expect(html).toMatch(/<button type="button" disabled="">Drop<\/button>/);
    expect(html).not.toContain("dim");   // stale, not busy
    expect(render(result())).not.toContain("dim");
  });
  test("nothing to loosen says so", () => {
    expect(render(result({patients: null}))).toContain("No single criterion, dropped, brings this cohort to 5 or more.");
  });
  test("a definition with neighbours is not offered suggestions: it says why, once", () => {
    const html = render(result({patients: null, loosen_offered: false}));
    expect(html).toContain("Too few patients to show, or hidden so a small group cannot be worked out by subtraction.");
    expect(html).not.toContain("No single criterion");
    expect(html).not.toContain("Too few patients to show.");
    expect(render(result({loosen_offered: false}))).not.toContain('class="loosen"');
  });
  test("no box for a shown cohort without suggestions", () => {
    expect(render(result())).not.toContain('class="loosen"');
  });
});

describe("tabs", () => {
  test("accrual: hatched <5 year, partial year label, hidden table", () => {
    const html = render(result(), "Accrual");
    expect(html).toContain("vbar hatched");
    expect(html).toContain("partial year");
    expect(html).toContain("Patients by year of first qualifying report");
    expect(html).toContain('class="sr-only"');
    expect(html).toContain('role="group" aria-label="Patients by year of first qualifying report"');
    expect(html).toContain('<div class="barlabel" aria-hidden="true">');
  });
  test("breakdown: null denominator shows <5 and a dash share", () => {
    const html = render(result(), "Breakdown");
    expect(html).toContain("<th scope=\"row\">male</th><td class=\"hatched\"><span class=\"suppressed\"");
    expect(html).toContain("Of patients in population");
    expect(html).toContain('role="region" aria-label="Sex"');
    expect(html).toContain("9%");   // 6 of 70
    expect(html).toContain("<td>–</td>");
  });
  test("pivot: a null cell renders <5 in its td; an omitted cell is a known zero", () => {
    const d: Definition = {...def, pivot: {rows: "oncotree", cols: "year"}};
    const pivot: PivotResult = {
      cohort_id: "abc", rows: "oncotree", cols: "year", patients: 8, min_cell: 5, notes: [],
      cells: [{row: "NSCLC", col: "2023", patients: 6}, {row: "NSCLC", col: "2024", patients: null}],
      row_totals: [{value: "NSCLC", patients: 8}, {value: "LUAD", patients: 12}],
      col_totals: [{value: "2023", patients: 6}, {value: "2024", patients: null}],
    };
    const html = render(result(), "Pivot", {}, d, pivot);
    expect(html).toContain('<td class="hatched"><span class="suppressed"');
    expect(html).toContain("<td>0</td>");   // LUAD x 2023
    expect(html).toContain("<caption>Tumor type (OncoTree) × Year of first qualifying report</caption>");
    expect(html).toContain('<th scope="col">Tumor type (OncoTree)</th>');
    expect(html).toContain('<th scope="col">2023</th>');
    expect(html).toContain("0: no patients have that combination. &lt;5: fewer than 5 patients, or hidden so that a small count cannot be worked out by subtraction.");
    expect(html).not.toContain("Blank combinations");
  });
  test("breakdown: a stale answer shows the counted breakdown", () => {
    const edited: Definition = {...def, breakdown: ["sex", "age_band"]};
    const counted: Counted = {d: def, r: result(), p: null};
    const html = renderToStaticMarkup(<Answer definition={edited} answer={counted} options={null} tab="Breakdown"
      onTab={() => {}} onOp={() => {}} />);
    expect(html).toContain('role="region" aria-label="Sex"');
    expect(html).not.toContain('aria-label="Age band"');
  });
  test("pivot: a stale answer labels criterion axes from the counted definition", () => {
    const egfr = {...alk, gene: ["EGFR"], aa: [], class: ["mutation"]} as Criterion;   // same id c2
    const countedD: Definition = {...def, pivot: {rows: "c2.key", cols: "year"}};
    const edited: Definition = {...countedD, criteria: [kras, egfr]};
    const pivot: PivotResult = {
      cohort_id: "abc", rows: "c2.key", cols: "year", patients: 8, min_cell: 5, notes: [],
      cells: [{row: "ALK", col: "2023", patients: 6}],
      row_totals: [{value: "ALK", patients: 6}], col_totals: [{value: "2023", patients: 6}],
    };
    const html = renderToStaticMarkup(<Answer definition={edited} answer={{d: countedD, r: result(), p: pivot}}
      options={null} tab="Pivot" onTab={() => {}} onOp={() => {}} />);
    expect(html).toContain("<caption>c2 · ALK fusion · gene × Year of first qualifying report</caption>");
    expect(html).toContain('<th scope="col">c2 · ALK fusion · gene</th>');
    expect(html).not.toMatch(/<caption>[^<]*EGFR/);
  });
  test("pivot before choosing", () => {
    expect(render(result(), "Pivot")).toContain("Choose rows and columns.");
  });
  test("data notes verbatim", () => {
    expect(render(result(), "Data notes")).toContain("<li>Stage and treatment are not in the data.</li>");
  });
});

describe("states", () => {
  test("errors show in an alert and the page keeps the result", () => {
    const html = render(result(), "Accrual", {error: "Too many queries; try again in 7 s."});
    expect(html).toContain('role="alert"');
    expect(html).toContain("Too many queries");
    expect(html).toContain("Patients");
  });
  test("an edit error and an answer error with Retry each render an alert", () => {
    const html = render(result(), "Accrual", {editError: "c9: no such criterion", error: "request failed (500)", onRetry: () => {}});
    expect(html).toContain("c9: no such criterion");
    expect(html).toContain(">Retry</button>");
    expect(render(result(), "Accrual", {error: "x"})).not.toContain("Retry");
  });
  test("the body is dimmed only while busy", () => {
    expect(render(result(), "Accrual", {busy: true})).toContain('class="answer-body dim"');
    expect(render(result(), "Accrual", {busy: false})).not.toContain("dim");
  });
  test("tablist roles", () => {
    const html = render(result());
    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain('role="tabpanel"');
  });
});
