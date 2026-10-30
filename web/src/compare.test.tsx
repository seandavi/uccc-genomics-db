import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Compare, CompareTable, type CompareColumn } from "./Compare.tsx";
import { EMPTY } from "./cohort.ts";
import type { Transport } from "./transport.ts";
import type { CountResult } from "./types.ts";

const result = (over: Partial<CountResult>): CountResult => ({
  cohort_id: "v1-aaaa", patients: 60, reports: 70, denominator: 600, min_cell: 5, funnel: [], loosen: [], loosen_offered: true,
  by_year: [], breakdowns: {}, notes: [], ...over,
});

const columns: CompareColumn[] = [
  {label: "v1 · Untitled", definition: "NSCLC; KRAS mutation", window: [2023, 2024], error: null, result: result({
    cohort_id: "v1-aaaa", by_year: [{year: 2023, patients: 20, complete: true}, {year: 2024, patients: null, complete: true}]})},
  {label: "v2 · Wider", definition: "NSCLC · 2023–2025; KRAS mutation; no TP53 mutation; same report", window: [2023, 2025], error: null, result: result({
    cohort_id: "v1-bbbb", by_year: [{year: 2024, patients: 30, complete: true}, {year: 2025, patients: 25, complete: false}]})},
];
// the server returns no year rows for a column whose patient count is suppressed
const suppressedColumn: CompareColumn = {label: "v3", definition: "All patients", error: null, result: result({patients: null, by_year: []})};
const html = renderToStaticMarkup(<CompareTable columns={columns} minCell={5} />);

describe("CompareTable", () => {
  test("a null count renders <5, a shown one with separators", () => {
    expect(html).toContain("&lt;5");
    expect(html).toContain(">600<");
  });
  test("a null count comes with the legend that says why, and no null no legend", () => {
    expect(html).toContain('<p class="legend">&lt;5: fewer than 5 patients, or hidden so that a small count cannot be worked out by subtraction.</p>');
    const shownOnly = renderToStaticMarkup(<CompareTable minCell={5} columns={[{label: "v1", definition: "All patients", error: null, result: result({})}]} />);
    expect(shownOnly).not.toContain("legend");
  });
  test("one row per year in the union of the years, blank where a result has none", () => {
    for (const y of ["2023", "2024", "2025"]) expect(html).toContain(`<th scope="row">${y}</th>`);
    expect(html).not.toContain('<th scope="row">2022</th>');
    expect(html).toContain('<th scope="row">2023</th><td>20</td><td></td>');
    expect(html).toMatch(/<th scope="row">2025<\/th><td><\/td><td>25<\/td>/);
  });
  test("a blank year cell comes with a legend, and no blank no legend", () => {
    expect(html).toContain('<p class="legend">Blank: no patients that year for that version.</p>');
    const shownOnly = renderToStaticMarkup(<CompareTable minCell={5} columns={[{label: "v1", definition: "All patients", error: null, result: result({})}]} />);
    expect(shownOnly).not.toContain("Blank:");
  });
  test("a suppressed column's year cells are suppressed, never blank, and claim no 'no patients'", () => {
    const out = renderToStaticMarkup(<CompareTable minCell={5} columns={[columns[1], suppressedColumn]} />);
    expect(out).toMatch(/<th scope="row">2024<\/th><td>30<\/td><td><span class="suppressed"[^>]*>&lt;5<\/span><\/td>/);
    expect(out).not.toContain("Blank:");
    expect(out).toContain("legend");
  });
  test("each column's cohort_id is its header's title", () => {
    expect(html).toContain('title="v1-aaaa"');
    expect(html).toContain('title="v1-bbbb"');
  });
  test("each column says what it selects, in the first body row", () => {
    expect(html).toContain('<tbody><tr><th scope="row">Definition</th><td>NSCLC; KRAS mutation</td><td>NSCLC · 2023–2025; KRAS mutation; no TP53 mutation; same report</td></tr>');
  });
  test("accrual uses each column's own window, and a suppressed patient count has none", () => {
    const out = renderToStaticMarkup(<CompareTable minCell={5} columns={[columns[0], suppressedColumn]} />);
    expect(out).toContain("<th scope=\"row\">Accrual a year</th><td>30.0</td><td>–</td>");
  });
  test("a failed column says why", () => {
    const out = renderToStaticMarkup(<CompareTable minCell={5} columns={[...columns, {label: "v3", definition: "All patients", result: null, error: "request failed (500)"}]} />);
    expect(out).toContain("request failed (500)");
  });
});

describe("Compare", () => {
  const panel = (n: number) => renderToStaticMarkup(
    <Compare versions={Array.from({length: n}, (_, i) => ({n: i + 1, definition: EMPTY}))} transport={{} as Transport} years={null} onClose={() => {}} />);
  test("one version: explanation and Close, no checkbox, no disabled button", () => {
    const html = panel(1);
    expect(html).toContain("Compare needs two or more edits");
    expect(html).toContain(">Close</button>");
    for (const gone of ['type="checkbox"', "Compare selected", 'disabled=""']) expect(html).not.toContain(gone);
  });
  test("two versions: Compare selected, and Count is gone", () => {
    const html = panel(2);
    expect(html).toContain(">Compare selected</button>");
    expect(html).not.toContain(">Count<");
  });
});
