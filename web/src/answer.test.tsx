import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Answer, DATA_FOOTNOTE, type AnswerProps, type Counted, type Tab } from "./Answer.tsx";
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
    expect(html).toContain("+ ALK fusion");
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
  test("the hero card holds the patient count", () => {
    expect(render(result())).toContain('class="card hero"><h3>Patients</h3><p class="big">8</p>');
  });
  test("a suppressed patient count is <5 in the hero", () => {
    const hero = /class="card hero"><h3>Patients<\/h3><p class="big"><span class="suppressed"[^>]*>&lt;(\d+)<\/span>/;
    const html = render(result({patients: null, reports: null, denominator: null}));
    expect(html.match(hero)?.[1]).toBe("5");
    expect(html).not.toContain(">0<");
    expect(render(result({patients: null, min_cell: 10})).match(hero)?.[1]).toBe("10");
  });
  test("accrual names its window", () => {
    expect(render(result())).toContain("per year, 2023–2026");
    const years = {...def, population: {...def.population, years: [2024, 2025] as [number, number]}};
    expect(render(result(), "Accrual", {}, years)).toContain("per year, 2024–2025");
    const html = renderToStaticMarkup(<Answer definition={def} answer={{d: def, r: result(), p: null}} options={null} tab="Accrual" onTab={() => {}} onOp={() => {}} />);
    expect(html).not.toContain("per year");
  });
  test("accrual shows one decimal below 10 and whole numbers from 10", () => {
    const html = render(result({patients: 120}));
    expect(html).toContain('<p class="big">30</p>');
    expect(html).not.toContain("30.0");
  });
  test("an empty definition shows no share card and no funnel", () => {
    const html = render(result(), "Accrual", {}, EMPTY);
    expect(html).not.toContain("Share of population");
    expect(html).not.toContain("funnel-h");
    expect(html).not.toContain('class="funnel"');
    for (const text of ["Patients", "Accrual", DATA_FOOTNOTE]) expect(html).toContain(text);
    const withYears = {...EMPTY, population: {...EMPTY.population, years: [2024, 2025] as [number, number]}};
    for (const d of [withYears, {...EMPTY, criteria: [kras]}]) {
      const shown = render(result(), "Accrual", {}, d);
      expect(shown).toContain("Share of population");
      expect(shown).toContain("funnel-h");
    }
  });
});

describe("funnel", () => {
  const exclude = {...alk, id: "c2", gene: ["KEAP1"], class: [], mode: "exclude"} as Criterion;
  const negative = {...alk, id: "c3", gene: ["STK11"], class: [], mode: "tested_negative"} as Criterion;
  const d: Definition = {...def, criteria: [kras, exclude, negative]};
  const r = result({funnel: [
    {criterion: null, patients: 120}, {criterion: "c1", patients: 40}, {criterion: "c2", patients: 30}, {criterion: "c3", patients: 20},
  ]});
  test("step prefixes by mode, no ∧", () => {
    const html = render(r, "Accrual", {}, d);
    for (const label of ["+ KRAS G12C", "− KEAP1 alteration", "+ tested negative: STK11 alteration"]) expect(html).toContain(label);
    expect(html).not.toContain("∧");
    expect(html).not.toContain("− no ");
  });
  test("a tested-negative step lists its genes with and, not or", () => {
    const two = {...negative, gene: ["STK11", "KEAP1"]} as Criterion;
    const html = render(r, "Accrual", {}, {...d, criteria: [kras, exclude, two]});
    expect(html).toContain("+ tested negative: STK11 and KEAP1 alteration");
    expect(html).not.toContain("STK11 or KEAP1");
  });
  test("the heading names the narrowing", () => {
    expect(render(r, "Accrual", {}, d)).toContain("How each criterion narrows the cohort");
  });
});

describe("answer heading and data footnote", () => {
  test("the heading is the cohort name or Your cohort", () => {
    expect(render(result(), "Accrual", {}, {...def, name: "Lung pilot"})).toContain('<h2 id="answer-h" tabindex="-1">Lung pilot</h2>');
    for (const name of ["", "  "]) expect(render(result(), "Accrual", {}, {...def, name})).toContain('<h2 id="answer-h" tabindex="-1">Your cohort</h2>');
  });
  test("the footnote sits under the cards, before the tabs", () => {
    const html = render(result());
    expect(html).toContain(`<p class="hint footnote">${DATA_FOOTNOTE} <button type="button" class="btn-tertiary">More in Data notes</button></p>`);
    expect(html.indexOf('class="card hero"')).toBeLessThan(html.indexOf('class="hint footnote"'));
    expect(html.indexOf('class="hint footnote"')).toBeLessThan(html.indexOf('class="tabs"'));
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
    expect(html).toContain("+ ALK fusion");
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

describe("accrual chart", () => {
  const yr = (year: number, patients: number | null, complete = true) => ({year, patients, complete});
  const colOf = (html: string, year: string) => html.split('<div class="col').find((c) => c.includes(`<span>${year}`)) ?? "";
  const heights = (html: string) => [...html.matchAll(/height:([\d.]+)%/g)].map((m) => Number(m[1]));
  const years = (from: number, n: number) => Array.from({length: n}, (_, i) => yr(from + i, 6));

  test("a null year is a hatched bar labelled <5, never 0 or blank", () => {
    const col = colOf(render(result()), "2024");
    expect(col).toContain("vbar hatched");
    expect(col).toContain("&lt;5");
    expect(col).not.toContain(">0<");
    expect(col).not.toContain("<span></span>");
  });
  test("a year with no patients is an empty dash slot", () => {
    const html = render(result({by_year: [yr(2020, 6), yr(2022, 7)]}));
    expect(html).toContain('<div class="col gap"><div class="barbox" aria-hidden="true"></div><div class="barlabel" aria-hidden="true"><span>–</span><span>2021</span></div></div>');
    expect(html).toContain("–: no patients that year");
    expect(html).toContain('<th scope="row">2021</th><td>no patients</td><td>unknown</td>');
    const gap = html.split('<div class="col').find((c) => c.startsWith(" gap")) ?? "";
    expect(gap).not.toContain("&lt;5");
    expect(gap).not.toContain("hatched");
    expect(render(result({by_year: [yr(2020, 6), yr(2021, 7)]}))).not.toContain("no patients that year");
  });
  test("a partial year is starred, with one legend line and no third label line", () => {
    const html = render(result());
    expect(html).toContain("<span>2025*</span>");
    expect(html).toContain("* partial year");
    for (const label of html.split('<div class="barlabel"').slice(1)) expect(label.split("</div>")[0]).not.toContain("partial year");
    expect(html).toContain("<td>partial year</td>");
  });
  test("past 12 years the labels are two-digit; the table keeps four", () => {
    const html = render(result({by_year: years(2010, 14)}));
    expect(html).toContain("<span>’10</span>");
    expect(html).toContain("<span>’23</span>");
    expect(html).not.toContain("<span>2010</span>");
    expect(html).toContain('<th scope="row">2010</th>');
    expect(render(result({by_year: years(2010, 12)}))).toContain("<span>2010</span>");
  });
  test("a suppressed bar is not taller than a shown bar of min_cell or more", () => {
    const [shown, hidden] = heights(render(result({by_year: [yr(2020, 5), yr(2021, null), yr(2022, 400)]})));
    expect(hidden).toBeLessThanOrEqual(shown);
  });
  test("a suppressed funnel bar is drawn as min_cell would be", () => {
    const html = render(result({funnel: [{criterion: null, patients: 50}, {criterion: "c1", patients: 5}, {criterion: "c2", patients: null}]}));
    expect(html).toContain('class="bar hatched" style="width:10%"');
    expect(html).toContain('class="bar" style="width:10%"');
  });
  test("every year hidden is one hatched strip", () => {
    const html = render(result({by_year: [yr(2023, null), yr(2024, null)]}));
    expect(html).toContain('class="strip"');
    expect(html).toContain("Every year under 5 or hidden");
    expect(html).not.toContain('class="bars"');
    expect(html).toContain("<span class=\"swatch hatched\"");
    expect(html.match(/<th scope="row">\d{4}<\/th><td><span class="suppressed"[^>]*>&lt;5/g)?.length).toBe(2);
    expect(render(result({by_year: [yr(2023, null)], min_cell: 10}))).toContain("Every year under 10 or hidden");
  });
  test("no years shows a message and no chart", () => {
    const html = render(result({by_year: []}));
    expect(html).toContain("No years to show.");
    expect(html).not.toContain('class="bars"');
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
  test("the accrual tier renders as a pill class per tier", () => {
    for (const [patients, cls, label] of [[400, "tier-high", "High"], [60, "tier-moderate", "Moderate"], [8, "tier-low", "Low / pilot"]] as const) {
      const html = render(result({patients}));
      expect(html).toContain(`class="tier ${cls}"`);
      expect(html).toContain(`>${label}<`);
    }
  });
  test("tablist roles", () => {
    const html = render(result());
    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain('role="tabpanel"');
  });
});

describe("Data notes and the answer heading", () => {
  test("the Data notes tab shows the cohort id for support", () => {
    const html = render(result(), "Data notes");
    expect(html).toContain("Cohort ID (for support)");
    expect(html).toContain("<code>abc</code>");
    expect(render(result())).not.toContain("<code>abc</code>");
  });
  test("the answer heading is a focus target", () => {
    expect(render(result())).toContain('id="answer-h" tabindex="-1"');
  });
});
