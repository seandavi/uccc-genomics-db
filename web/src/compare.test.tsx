import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { CompareTable, type CompareColumn } from "./Compare.tsx";
import type { CountResult } from "./types.ts";

const result = (over: Partial<CountResult>): CountResult => ({
  cohort_id: "v1-aaaa", patients: 60, reports: 70, denominator: 600, min_cell: 5, funnel: [], loosen: [], loosen_offered: true,
  by_year: [], breakdowns: {}, notes: [], ...over,
});

const columns: CompareColumn[] = [
  {label: "v1 · Untitled", window: [2023, 2024], error: null, result: result({
    cohort_id: "v1-aaaa", by_year: [{year: 2023, patients: 20, complete: true}, {year: 2024, patients: null, complete: true}]})},
  {label: "v2 · Wider", window: [2023, 2025], error: null, result: result({
    cohort_id: "v1-bbbb", patients: null, by_year: [{year: 2024, patients: 30, complete: true}, {year: 2025, patients: 25, complete: false}]})},
];
const html = renderToStaticMarkup(<CompareTable columns={columns} minCell={5} />);

describe("CompareTable", () => {
  test("a null count renders <5, a shown one with separators", () => {
    expect(html).toContain("&lt;5");
    expect(html).toContain(">600<");
  });
  test("one row per year in the union of the years, blank where a result has none", () => {
    for (const y of ["2023", "2024", "2025"]) expect(html).toContain(`<th scope="row">${y}</th>`);
    expect(html).not.toContain('<th scope="row">2022</th>');
    expect(html).toContain('<th scope="row">2023</th><td>20</td><td></td>');
    expect(html).toMatch(/<th scope="row">2025<\/th><td><\/td><td>25<\/td>/);
  });
  test("each column's cohort_id is its header's title", () => {
    expect(html).toContain('title="v1-aaaa"');
    expect(html).toContain('title="v1-bbbb"');
  });
  test("accrual uses each column's own window, and a suppressed patient count has none", () => {
    expect(html).toContain("<th scope=\"row\">Accrual a year</th><td>30.0</td><td>–</td>");
  });
  test("a failed column says why", () => {
    const out = renderToStaticMarkup(<CompareTable minCell={5} columns={[...columns, {label: "v3", result: null, error: "request failed (500)"}]} />);
    expect(out).toContain("request failed (500)");
  });
});
