import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { App, FeasibilityPanel, applyDefinition, applyShareHash, SharePanel, SummaryBar, Who } from "./App.tsx";
import { EMPTY, EXAMPLES, pushVersion, shareHash, type History } from "./cohort.ts";
import { TransportError, type Transport } from "./transport.ts";
import type { ApplyResult, CountResult, Definition, Options } from "./types.ts";

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
    expect(html).toContain("Start from an example");
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

describe("Who", () => {
  const html = (sign_out: boolean) =>
    renderToStaticMarkup(<Who me={{sub: "s", email: "a@example.edu", sign_out}} onSignOut={() => {}} />);
  test("shows the email and, when the backend has a session, Sign out", () => {
    expect(html(true)).toContain('<span class="sr-only">Signed in as </span>a@example.edu');
    expect(html(true)).toContain(">Sign out</button>");
  });
  test("no Sign out button without a session", () => {
    expect(html(false)).toContain("a@example.edu");
    expect(html(false)).not.toContain("Sign out");
  });
});

describe("applyShareHash", () => {
  const b = {...EMPTY, name: "b", population: {...EMPTY.population, sex: ["Female"]}};
  const c = {...EMPTY, name: "c", population: {...EMPTY.population, sex: ["Male"]}};
  const h: History = {versions: [{n: 1, definition: EMPTY}], current: 0};
  const fake = (result: unknown) => {
    const calls: unknown[][] = [];
    const apply = async (...args: unknown[]) => {
      calls.push(args);
      if (result instanceof Error) throw result;
      return {definition: result} as ApplyResult;
    };
    return {calls, transport: {apply} as unknown as Pick<Transport, "apply">};
  };
  const prefix = "This link does not hold a valid cohort: ";

  test("a valid link adds a version", async () => {
    const t = fake(b);
    const r = await applyShareHash(shareHash(b), () => h, t.transport) as {history: History};
    expect(r.history.versions.length).toBe(2);
    expect(r.history.current).toBe(1);
    expect(r.history.versions[1].n).toBe(2);
    expect(r.history.versions[1].definition).toEqual(b);
    expect(t.calls.length).toBe(1);
    expect(t.calls[0][1]).toEqual({op: "rename", name: "b"});
  });
  test("an unreadable hash is an error and no request", async () => {
    const t = fake(b);
    expect(await applyShareHash("#d=!!!", () => h, t.transport)).toEqual({error: `${prefix}it could not be read`});
    expect(t.calls.length).toBe(0);
  });
  test("a server rejection is an error", async () => {
    const t = fake(new TransportError("criteria.0.gene: unknown", 422));
    expect(await applyShareHash(shareHash(b), () => h, t.transport)).toEqual({error: `${prefix}criteria.0.gene: unknown`});
  });
  test("the current version's own hash does nothing", async () => {
    const t = fake(b);
    expect(await applyShareHash(shareHash(EMPTY), () => h, t.transport)).toBeNull();
    expect(t.calls.length).toBe(0);
  });
  test("a link equal to the current definition after normalisation adds no version", async () => {
    const t = fake(EMPTY);
    const r = await applyShareHash(shareHash({...EMPTY, name: "x"}), () => h, t.transport) as {history: History};
    expect(r.history).toBe(h);
  });
  test("a hash that is not a share link leaves the history alone", async () => {
    const t = fake(b);
    for (const hash of ["#answer-h", ""]) {
      const r = await applyShareHash(hash, () => h, t.transport) as {history: History};
      expect(r.history).toBe(h);
    }
    expect(t.calls.length).toBe(0);
  });
  test("an edit made during the request is kept", async () => {
    const h2 = pushVersion(h, c);
    let reads = 0;
    const r = await applyShareHash(shareHash(b), () => (reads++ === 0 ? h : h2), fake(b).transport) as {history: History};
    expect(r.history.versions.map((v) => v.n)).toEqual([1, 2, 3]);
    expect(r.history.versions[1].definition).toEqual(c);
    expect(r.history.versions[2].definition).toEqual(b);
  });
  test("one code path: the mount effect and a hashchange listener both use it", () => {
    const src = readFileSync(join(import.meta.dir, "App.tsx"), "utf8");
    expect(src).toContain('addEventListener("hashchange"');
    expect(src).toContain('removeEventListener("hashchange"');
    expect(src.split("applyShareHash(window.location.hash").length - 1).toBe(2);
    expect(src).not.toContain("window.location.hash.startsWith");
  });
});

describe("applyDefinition", () => {
  const h: History = {versions: [{n: 1, definition: EMPTY}], current: 0};
  const example = EXAMPLES[0];
  const normal = {...example, criteria: [{...example.criteria[0], tier: ["likely_pathogenic", "pathogenic"]}]} as Definition;
  const fake = (result: unknown) => {
    const calls: unknown[][] = [];
    const apply = async (...args: unknown[]) => {
      calls.push(args);
      if (result instanceof Error) throw result;
      return {definition: result} as ApplyResult;
    };
    return {calls, transport: {apply} as unknown as Pick<Transport, "apply">};
  };

  test("an example is version n+1 holding the server's normal form", async () => {
    const t = fake(normal);
    const r = await applyDefinition(example, () => h, t.transport);
    expect(r.versions.length).toBe(2);
    expect(r.current).toBe(1);
    expect(r.versions[1].n).toBe(2);
    expect(r.versions[1].definition).toEqual(normal);
    expect(t.calls.length).toBe(1);
    expect(t.calls[0][1]).toEqual({op: "rename", name: example.name});
  });
  test("a server rejection rejects and adds nothing", async () => {
    const err = new TransportError("criteria.c1.gene: 'EGFR' is not in the vocabulary", 400);
    await expect(applyDefinition(example, () => h, fake(err).transport)).rejects.toBe(err);
  });
  test("a normal form equal to the current version adds no version", async () => {
    expect(await applyDefinition(example, () => h, fake(EMPTY).transport)).toBe(h);
  });
  test("an edit made during the request is kept", async () => {
    const c = {...EMPTY, name: "c", population: {...EMPTY.population, sex: ["Male"]}};
    const h2 = pushVersion(h, c);
    const r = await applyDefinition(example, () => h2, fake(normal).transport);
    expect(r.versions.map((v) => v.n)).toEqual([1, 2, 3]);
    expect(r.versions[1].definition).toEqual(c);
    expect(r.versions[2].definition).toEqual(normal);
  });
  test("App.tsx: share links and examples go through it", () => {
    const src = readFileSync(join(import.meta.dir, "App.tsx"), "utf8");
    const body = (start: string, end: string) => src.slice(src.indexOf(start), src.indexOf(end, src.indexOf(start)));
    expect(body("export async function applyShareHash", "export function App")).toContain("applyDefinition(");
    const example = body("const applyExample", "}, [transport");
    for (const text of ["applyDefinition(", "setHist(", "refresh()", "This example could not be used: "]) expect(example).toContain(text);
    expect(src).toContain("onExample={applyExample}");
  });
});
