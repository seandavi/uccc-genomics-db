import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Landing, discoverRedirect } from "./Landing.tsx";
import type { PublicSummary } from "./types.ts";

const SUMMARY: PublicSummary = {
  patients: 1230, reports: 1560, tumor_types: null, vendors: ["caris", "fmi", "other"], first_year: 2016, last_year: 2018,
  by_year: [{year: 2016, patients: 40, complete: true}, {year: 2017, patients: null, complete: true},
            {year: 2018, patients: 120, complete: false}],
  min_cell: 5, round_to: 10,
};
const render = (summary: PublicSummary | null, error = false) => renderToStaticMarkup(<Landing summary={summary} error={error} />);

describe("discoverRedirect", () => {
  test("a share hash goes to /discover with the hash", () => {
    expect(discoverRedirect("#d=abc")).toBe("/discover#d=abc");
  });
  test("anything else stays", () => {
    for (const h of ["", "#x", "#answer-h"]) expect(discoverRedirect(h)).toBeNull();
  });
});

describe("Landing", () => {
  test("the sign-in link opens Discover; no form", () => {
    const html = render(SUMMARY);
    expect(html).toContain('<a class="btn-primary" href="/discover">Sign in to Discover</a>');
    expect(html).not.toContain("<form");
  });
  test("totals: suppressed counts as <5, vendor labels, year range, rounding note", () => {
    const html = render(SUMMARY);
    expect(html).toContain("1,230");
    expect(html).toMatch(/Tumor types<\/dt><dd><span class="suppressed"[^>]*>&lt;5<\/span>/);
    expect(html).toContain("Caris Life Sciences, Foundation Medicine, other");
    expect(html).toContain("2016–2018");
    expect(html).toContain("rounded to the nearest 10");
    expect(html).toContain("Patients by year of first sample, 2016–2018");
  });
  test("a single year and no year", () => {
    expect(render({...SUMMARY, first_year: 2020, last_year: 2020})).toContain("<dd>2020</dd>");
    const html = render({...SUMMARY, first_year: null, last_year: null, by_year: []});
    expect(html).not.toContain("First-sample years");
  });
  test("access copy names campus Google sign-in", () => {
    const html = render(SUMMARY);
    expect(html).toContain("Sign in with your CU Anschutz Google account.");
    expect(html).toContain("Researchers without a CU Anschutz account can ask the UCCC genomics team for access.");
    expect(html).not.toContain("To get access");
  });
  test("the hint explains partial and hatched bars", () => {
    const html = render(SUMMARY);
    expect(html).toContain("A lighter bar is a year not yet complete; a hatched bar is fewer than 5.");
    expect(html).toContain("Years are approximate");
  });
  test("the sr-only table marks partial years", () => {
    const html = render(SUMMARY);
    expect(html).toContain("<td>2018 (partial year)</td>");
    expect(html).toContain("<td>2016</td>");
  });
  test("year label and vendors cell", () => {
    const html = render(SUMMARY);
    expect(html).toContain("<dt>First-sample years</dt>");
    expect(html).toContain('<div class="text"><dt>Vendors</dt>');
    expect(html).not.toContain("Collection years");
  });
  test("landing <5 titles", () => {
    const html = render(SUMMARY);
    expect(html).toMatch(/Tumor types<\/dt><dd><span class="suppressed" title="Fewer than 5">/);
    expect(html).toContain('title="Fewer than 5 patients"');
    expect(html).not.toContain("subtraction");
  });
  test("loading and error states show no totals", () => {
    expect(render(null)).toContain("Loading totals…");
    const html = render(null, true);
    expect(html).toContain("Totals are not available right now.");
    expect(html).not.toContain("<dl");
    expect(html).toContain("Sign in to Discover");
  });
});
