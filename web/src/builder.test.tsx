import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Builder, Checks } from "./Builder.tsx";
import { EMPTY } from "./cohort.ts";
import type { Transport } from "./transport.ts";
import type { Criterion, Definition } from "./types.ts";

describe("Checks", () => {
  test("a failed value load says so in an alert", () => {
    const html = renderToStaticMarkup(<Checks legend="Site" values={[]} selected={[]} onChange={() => {}} error="request failed (500)" />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Could not load values: request failed (500)");
  });
  test("no error, no alert", () => {
    expect(renderToStaticMarkup(<Checks legend="Site" values={["a"]} selected={[]} onChange={() => {}} />)).not.toContain("alert");
  });
});

const transport = {} as Transport;   // a static render starts no request
const render = (d: Definition) => renderToStaticMarkup(<Builder definition={d} transport={transport} options={null} onOp={() => {}} />);
const alt = {id: "c1", kind: "alteration", mode: "include", vendor: null, gene: ["KRAS"], aa: [], class: [], tier: []} as Criterion;
const ihc = {id: "c2", kind: "ihc", mode: "include", vendor: null, marker: "ER", clone: null, call: [], measure: null, at_least: null} as Criterion;
const data = {id: "c3", kind: "data", mode: "include", vendor: null, has: "serial"} as Criterion;
const sequence = {
  id: "c4", kind: "sequence", mode: "include",
  first: [{kind: "data", mode: "include", vendor: null, has: "tissue"}],
  then: [{kind: "data", mode: "include", vendor: null, has: "liquid"}, {...alt, id: null}],
} as Criterion;

const options = (html: string, id: string) => {
  const select = html.match(new RegExp(`<select aria-label="Mode of ${id}"[^>]*>(.*?)</select>`));
  return [...(select?.[1] ?? "").matchAll(/<option value="([a-z_]+)"/g)].map((m) => m[1]);
};

describe("criterion cards", () => {
  test("an alteration card offers three modes and an ihc card two", () => {
    const html = render({...EMPTY, criteria: [alt, ihc]});
    expect(options(html, "c1")).toEqual(["include", "exclude", "tested_negative"]);
    expect(options(html, "c2")).toEqual(["include", "exclude"]);
  });
  test("Then… is offered for a finding, not for an exclusion or a sequence", () => {
    expect(render({...EMPTY, criteria: [alt]})).toContain(">Then…</button>");
    expect(render({...EMPTY, criteria: [{...alt, mode: "exclude"} as Criterion]})).not.toContain("Then…");
    expect(render({...EMPTY, criteria: [sequence]})).not.toContain(">Then…</button>");
  });
  test("the same-report box follows the scope", () => {
    expect(render({...EMPTY, scope: "report"})).toMatch(/checked=""[^>]*\/> All criteria on the same report/);
    expect(render(EMPTY)).not.toMatch(/checked=""[^>]*\/> All criteria on the same report/);
  });
  test("a sequence card shows both member lists, and no Edit", () => {
    const html = render({...EMPTY, criteria: [sequence]});
    expect(html).toContain("First report");
    expect(html).toContain("Later report");
    expect(html).toContain("Has tissue testing");
    expect(html).toContain("Has a liquid biopsy");
    expect(html).toContain("KRAS alteration");
    expect(html).not.toContain(">Edit</button>");
    expect(options(html, "c4")).toEqual(["include"]);
    // the only member of a side cannot be removed; the two-member side can lose one
    expect(html).toMatch(/aria-label="Remove Has tissue testing from first report of c4" disabled=""/);
    expect(html).not.toMatch(/aria-label="Remove Has a liquid biopsy from later report of c4" disabled=""/);
  });
  test("a per-patient data criterion has no Edit; no Or… for data", () => {
    const html = render({...EMPTY, criteria: [data]});
    expect(html).not.toContain(">Edit</button>");
    expect(html).not.toContain(">Or…</button>");
    expect(html).not.toContain("Then…");
  });
});
