import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { App, FeasibilityPanel, SharePanel, SummaryBar } from "./App.tsx";
import { EMPTY } from "./cohort.ts";
import type { Transport } from "./transport.ts";
import type { CountResult, Options } from "./types.ts";

const render = (statement: string, copied = false) =>
  renderToStaticMarkup(<FeasibilityPanel statement={statement} copied={copied} onCopy={() => {}} onClose={() => {}} textareaRef={{current: null}} />);

describe("FeasibilityPanel", () => {
  test("an empty statement says it is recounting: no textarea, Copy disabled, Close offered", () => {
    const html = render("");
    expect(html).toContain("Recounting…");
    expect(html).not.toContain("<textarea");
    expect(html).toMatch(/<button type="button" disabled="">Copy<\/button>/);
    expect(html).toContain(">Close</button>");
  });
  test("a statement is in a textarea and Copy is enabled", () => {
    const html = render("About 40 patients a year.");
    expect(html).toMatch(/<textarea[^>]*>About 40 patients a year\.<\/textarea>/);
    expect(html).not.toContain("Recounting");
    expect(html).toContain('<button type="button">Copy</button>');
  });
  test("copied is announced", () => {
    expect(render("x", true)).toContain("Copied");
    expect(render("x")).not.toContain("Copied");
  });
});

const never = new Promise(() => {});
const stalled = {count: () => never, apply: () => never, options: () => never, pivot: () => never} as unknown as Transport;
const headerOf = (html: string) => html.slice(html.indexOf("<header"), html.indexOf("</header>"));

describe("header", () => {
  test("one version: one primary button, no hash, History, Compare explained, no assistant", () => {
    const html = renderToStaticMarkup(<App transport={stalled} />);
    const h = headerOf(html);
    expect(h.match(/btn-primary/g)?.length).toBe(1);
    expect(h).toMatch(/class="btn-primary"[^>]*>Feasibility statement</);
    expect(h).not.toContain("<code");
    expect(h).toContain('aria-label="History"');
    expect(h).toContain(">Edit 1</option>");
    expect(h).toMatch(/aria-label="Previous edit"[^>]*disabled=""/);
    expect(h).toMatch(/aria-label="Next edit"[^>]*disabled=""/);
    expect(h).toMatch(/<button[^>]*aria-describedby="compare-why"[^>]*>Compare</);
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Compare</);
    expect(h).toContain("Make a change to compare versions");
    expect(h).toContain('aria-label="More actions"');
    expect(h).toContain('aria-expanded="false"');
    expect(h).toContain('aria-controls="header-actions"');
    expect(h.indexOf('aria-controls="header-actions"')).toBeLessThan(h.indexOf('id="header-actions"'));
    expect(html).not.toContain('aria-label="Assistant"');
    expect(html).not.toContain("Coming later");
  });
  test("two versions: Compare enabled without a reason, back enabled, forward disabled", () => {
    const stored = {versions: [{n: 1, definition: EMPTY}, {n: 2, definition: {...EMPTY, name: "b"}}], current: 1};
    (globalThis as unknown as {localStorage: unknown}).localStorage = {getItem: () => JSON.stringify(stored), setItem: () => {}};
    try {
      const h = headerOf(renderToStaticMarkup(<App transport={stalled} />));
      expect(h).toContain(">Edit 1</option>");
      expect(h).toContain(">Edit 2</option>");
      expect(h).not.toMatch(/aria-label="Previous edit"[^>]*disabled=""/);
      expect(h).toMatch(/aria-label="Next edit"[^>]*disabled=""/);
      expect(h).not.toMatch(/<button[^>]*disabled=""[^>]*>Compare</);
      expect(h).not.toContain("Make a change to compare versions");
      expect(h).toContain('value="b"');
    } finally {
      delete (globalThis as unknown as {localStorage?: unknown}).localStorage;
    }
  });
  test("the header source never mentions cohort_id", () => {
    const src = readFileSync(join(import.meta.dir, "App.tsx"), "utf8");
    const h = src.slice(src.indexOf('<header className="top">'), src.indexOf("</header>"));
    expect(h.length).toBeGreaterThan(500);
    expect(h).not.toContain("cohort_id");
  });
});

describe("SharePanel", () => {
  const share = (cohortId: string | null, copied = false) =>
    renderToStaticMarkup(<SharePanel link="http://x/#d=abc" cohortId={cohortId} copied={copied} onClose={() => {}} />);
  test("shows the link and the cohort id for support", () => {
    const html = share("v1-test");
    expect(html).toContain('aria-label="Share link"');
    expect(html).toContain("Cohort ID (for support)");
    expect(html).toContain("<code>v1-test</code>");
  });
  test("no cohort id without a current answer", () => expect(share(null)).not.toContain("Cohort ID"));
  test("copied is announced", () => {
    expect(share(null, true)).toContain("Link copied");
    expect(share(null)).not.toContain("Link copied");
  });
});

describe("SummaryBar", () => {
  const result = (over: Partial<CountResult> = {}): CountResult => ({
    cohort_id: "abc", patients: 8, reports: 9, denominator: 120, min_cell: 5, funnel: [], loosen: [], loosen_offered: true,
    by_year: [], breakdowns: {}, notes: [], ...over,
  });
  const options: Options = {entries: [], years: [2023, 2026], cut_points: {}, min_cell: 5};
  const bar = (patients: number | null) =>
    renderToStaticMarkup(<SummaryBar answer={{d: EMPTY, r: result({patients}), p: null}} options={options} />);
  test("a suppressed count is <5 in a hatched span, never 0, with no tier", () => {
    const html = bar(null);
    expect(html).toContain('class="summary-count hatched"');
    expect(html).toContain("&lt;5");
    expect(html).not.toContain(">0<");
    expect(html).not.toContain('class="tier');
    expect(html).toContain('href="#answer-h"');
    expect(html).toContain(">View</a>");
  });
  test("a shown count has the tier pill", () => {
    const html = bar(400);
    expect(html).toContain("400");
    expect(html).not.toContain("hatched");
    expect(html).toContain('class="tier tier-high"');
  });
  test("no answer, no bar", () => expect(renderToStaticMarkup(<SummaryBar answer={null} options={options} />)).toBe(""));
});
