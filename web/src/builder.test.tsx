import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AlterationEditor, Builder, Checks, withoutMember } from "./Builder.tsx";
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
  const select = html.match(new RegExp(`<select[^>]*aria-label="Mode of ${id}"[^>]*>(.*?)</select>`));
  return [...(select?.[1] ?? "").matchAll(/<option value="([a-z_]+)"/g)].map((m) => m[1]);
};

describe("criterion cards", () => {
  test("an alteration card offers three modes and an ihc card two", () => {
    const html = render({...EMPTY, criteria: [alt, ihc]});
    expect(options(html, "c1")).toEqual(["include", "exclude", "tested_negative"]);
    expect(options(html, "c2")).toEqual(["include", "exclude"]);
  });
  test("+ Later report is offered for a finding, not for an exclusion or a sequence", () => {
    expect(render({...EMPTY, criteria: [alt]})).toContain(">+ Later report</button>");
    expect(render({...EMPTY, criteria: [{...alt, mode: "exclude"} as Criterion]})).not.toContain(">+ Later report</button>");
    expect(render({...EMPTY, criteria: [sequence]})).not.toContain(">+ Later report</button>");
  });
  test("the same-report toggle shows with two criteria, below the cards, or when on", () => {
    expect(render(EMPTY)).not.toContain("same report");
    expect(render({...EMPTY, criteria: [alt]})).not.toContain("same report");
    const two = render({...EMPTY, criteria: [alt, ihc]});
    expect(two).toContain("Match all criteria on the same report");
    expect(two).not.toMatch(/checked=""[^>]*\/> Match all criteria on the same report/);
    expect(two.indexOf("Match all criteria on the same report")).toBeGreaterThan(two.lastIndexOf("</article>"));
    expect(render({...EMPTY, scope: "report"})).toMatch(/checked=""[^>]*\/> Match all criteria on the same report/);
    // one negated criterion counts differently at report scope, so the switch shows
    expect(render({...EMPTY, criteria: [{...alt, mode: "exclude"} as Criterion]})).toContain("Match all criteria on the same report");
  });
  test("a sequence card shows both member lists, and no Edit", () => {
    const html = render({...EMPTY, criteria: [sequence]});
    expect(html).toContain("First report");
    expect(html).toContain("Later report");
    expect(html).toContain("Tissue testing");
    expect(html).toContain("Liquid biopsy");
    expect(html).toContain("KRAS alteration");
    expect(html).not.toContain(">Edit</button>");
    expect(options(html, "c4")).toEqual(["include"]);
    // the only member of a side cannot be removed; the two-member side can lose one
    expect(html).toMatch(/aria-label="Remove tissue testing from first report of c4" disabled=""/);
    expect(html).not.toMatch(/aria-label="Remove liquid biopsy from later report of c4" disabled=""/);
  });
  test("a data card heading is a noun phrase with a capital", () => {
    expect(render({...EMPTY, criteria: [data]})).toContain('aria-label="Serial reports (two or more)"');
  });
  test("a criterion that spans reports disables the same-report box; a visible hint says why", () => {
    const html = render({...EMPTY, criteria: [alt, sequence]});
    const id = html.match(/<input type="checkbox" disabled=""[^>]*aria-describedby="([^"]+)"/)?.[1];
    expect(id).toBeTruthy();
    expect(html).toMatch(new RegExp(`<p id="${id}" class="hint">[^<]*cannot be matched on one report`));
    expect(html).not.toMatch(/<label title=/);
    const open = render({...EMPTY, criteria: [alt, ihc]});
    expect(open).not.toMatch(/<input type="checkbox" disabled=""/);
    expect(open).not.toContain("aria-describedby");
    expect(render({...EMPTY, scope: "report"})).not.toMatch(/<input type="checkbox" disabled=""/);
  });
  test("no + Later report at report scope", () => {
    expect(render({...EMPTY, scope: "report", criteria: [alt]})).not.toContain(">+ Later report</button>");
  });
  test("a per-patient data criterion has no Edit; no + Or another for data", () => {
    const html = render({...EMPTY, criteria: [data]});
    expect(html).not.toContain(">Edit</button>");
    expect(html).not.toContain(">+ Or another</button>");
    expect(html).not.toContain(">+ Later report</button>");
  });
  test("the header holds the mode, a separator, the label and Remove, in that order", () => {
    const html = render({...EMPTY, criteria: [alt]});
    const header = html.slice(html.indexOf("<header"), html.indexOf("</header>"));
    const at = ['aria-label="Mode of c1"', '<span class="sep" aria-hidden="true">·</span>', '<span class="clabel">', 'class="btn-icon remove"']
      .map((x) => header.indexOf(x));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((x, y) => x - y)).toEqual(at);
  });
  test("an alteration card has an actions row; a sequence card has none", () => {
    expect(render({...EMPTY, criteria: [alt]})).toContain('class="row card-actions"');
    expect(render({...EMPTY, criteria: [sequence]})).not.toContain("card-actions");
  });
  test("+ Or another is offered for a finding", () => {
    expect(render({...EMPTY, criteria: [alt]})).toContain(">+ Or another</button>");
  });
  test("every text input has a placeholder", () => {
    const html = render({...EMPTY, criteria: [alt, sequence]});
    const inputs = html.match(/<input(?![^>]*type="checkbox")[^>]*>/g) ?? [];
    expect(inputs.length).toBeGreaterThanOrEqual(3);
    for (const i of inputs) expect(i).toMatch(/placeholder="[^"]+"/);
    expect(html).toContain('placeholder="Search genes, biomarkers, IHC, specimens… e.g. KRAS, TMB, PD-L1"');
  });
  test("adders are dashed chips and the years row reads Years Any – Any", () => {
    const html = render(EMPTY);
    expect(html.match(/<button[^>]*class="adder"/g)?.length).toBe(6);
    expect(html).toContain(">+ Tumor type</button>");
    expect(html).toContain(">+ Assay</button>");
    expect(html).toContain(">Years</span>");
    expect(html.match(/<option value=""[^>]*>Any<\/option>/g)?.length).toBe(2);
    for (const gone of ["All years", ">From", ">To"]) expect(html).not.toContain(gone);
  });
  test("an exclude card: mode badge before the label, no visible No", () => {
    const html = render({...EMPTY, criteria: [{...alt, id: "c1", mode: "exclude", gene: ["KEAP1", "STK11"]} as Criterion]});
    expect(html).toContain('<option value="exclude" selected="">');
    expect(html).toContain('<span class="clabel">KEAP1 or STK11 alteration</span>');
    expect(html.indexOf('aria-label="Mode of c1"')).toBeLessThan(html.indexOf('class="clabel"'));
    expect(html).not.toContain(">No KEAP1");
    expect(html).toContain('class="criterion mode-exclude"');
  });
  test("the criterion id is not shown, only named in aria labels", () => {
    const html = render({...EMPTY, criteria: [alt, ihc]});
    expect(html).not.toMatch(/>c\d+</);
    expect(html).toContain('aria-label="Mode of c1"');
    expect(html).toContain('aria-label="Mode of c2"');
  });
  test("Remove is an icon button and the text actions are tertiary and separated", () => {
    const html = render({...EMPTY, criteria: [alt]});
    expect(html).toContain('class="btn-icon remove" aria-label="Remove KRAS alteration"');
    expect(html).toContain(">✕</button>");
    expect(html).not.toContain(">Remove</button>");
    expect(html).toMatch(/class="btn-tertiary"[^>]*>Edit<\/button>/);
    expect(html).toContain('>Edit</button><span class="sep" aria-hidden="true">·</span>');
  });
});

describe("AlterationEditor", () => {
  const editor = (mode: "include" | "tested_negative") =>
    renderToStaticMarkup(<AlterationEditor d={{...alt, mode} as Extract<Criterion, {kind: "alteration"}>} set={() => {}} transport={transport} />);
  const classes = (html: string) => ["mutation", "amplification", "loss", "fusion"].filter((c) => html.includes(`/> ${c}</label>`));
  test("tested negative offers only the mutation class, and says why", () => {
    const html = editor("tested_negative");
    expect(classes(html)).toEqual(["mutation"]);
    expect(html).toContain("Tested negative is per gene");
  });
  test("an include criterion offers all four classes and no hint", () => {
    const html = editor("include");
    expect(classes(html)).toEqual(["mutation", "amplification", "loss", "fusion"]);
    expect(html).not.toContain("Tested negative is per gene");
  });
});

describe("withoutMember", () => {
  const anyOf = (mode: "include" | "exclude") => ({
    id: "c1", kind: "any_of", mode,
    of: [{...alt, id: null, gene: ["STK11"]}, {...alt, id: null, gene: ["KEAP1"]}],
  }) as Extract<Criterion, {kind: "any_of"}>;
  test("the last member of an excluded any_of stays an exclusion", () => {
    expect(withoutMember(anyOf("exclude"), 1)).toMatchObject({id: "c1", kind: "alteration", mode: "exclude", gene: ["STK11"]});
  });
  test("an included any_of stays an include, and a longer one stays an any_of", () => {
    expect(withoutMember(anyOf("include"), 0)).toMatchObject({kind: "alteration", mode: "include", gene: ["KEAP1"]});
    const three = {...anyOf("exclude"), of: [...anyOf("exclude").of, {...alt, id: null, gene: ["TP53"]}]} as Extract<Criterion, {kind: "any_of"}>;
    expect(withoutMember(three, 0)).toMatchObject({kind: "any_of", mode: "exclude"});
  });
});
