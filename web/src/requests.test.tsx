import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { EMPTY, shareHash } from "./cohort.ts";
import { IntakeForm, RequestList, RequestView, SubmitBlock } from "./Requests.tsx";
import { STATUS_LABEL, STATUS_TEXT, editable, exactIrb, toDraft } from "./requests.ts";
import type { IrbStatus, MyRequestDetail, Requests } from "./types.ts";

const IRB: IrbStatus = {irb_number: "TEST-0100", version: 1, status: "active", expiration_date: "2099-01-01",
                        doc_types: ["approval_letter", "personnel_list"], registered_by_you: true};

const DETAIL: MyRequestDetail = {
  id: "11111111-1111-4111-8111-111111111111", requester: "sub-a", cohort: "22222222-2222-4222-8222-222222222222", seq: 1,
  cohort_id: "v1-0123456789abcdef", definition: {...EMPTY, name: "Synthetic cohort"}, snapshot_id: "synthetic-build-1",
  irb_number: "TEST-0100", irb_version: 1, purpose: "synthetic purpose", fields: ["demographics", "diagnosis"],
  identifiers: [{identifier: "mrn", reason: "synthetic reason"}], recipients: [{name: "R Example", email: "r@example.edu"}],
  storage_location: "synthetic share", retention_end: "2099-06-01", status: "draft",
  created_at: "2026-10-30T10:00:00Z", updated_at: "2026-10-30T11:00:00Z",
  irb: IRB, attestation: null, missing: ["add a reference to the protocol excerpt"], attestations: [], reviews: [], releases: [],
};

const api = {
  update: async () => DETAIL, submit: async () => DETAIL, remove: async () => {}, get: async () => DETAIL,
  lookupIrb: async () => ({authorizations: []}), registerIrb: async () => IRB, addDocument: async () => IRB,
};
const view = (d: Partial<MyRequestDetail>) => renderToStaticMarkup(<RequestView detail={{...DETAIL, ...d}} api={api} onChange={() => {}} />);

describe("RequestList", () => {
  test("empty says how to start one", () => {
    const html = renderToStaticMarkup(<RequestList requests={{requests: []}} />);
    expect(html).toBe("<p>No requests yet. In Discover, build a cohort and choose Request identified data.</p>");
  });
  test("a row links to #id and shows status, IRB and date; an unnamed cohort is Untitled", () => {
    const requests: Requests = {requests: [DETAIL, {...DETAIL, id: "33333333-3333-4333-8333-333333333333",
      definition: {...EMPTY, name: ""}, irb_number: null, irb_version: null, status: "submitted"}]};
    const html = renderToStaticMarkup(<RequestList requests={requests} />);
    expect(html).toContain(`<a href="#${DETAIL.id}">Synthetic cohort</a>`);
    expect(html).toContain("<td>Draft</td><td>TEST-0100 v1</td><td>2026-10-30</td>");
    expect(html).toContain(">Untitled cohort</a>");
    expect(html).toContain("<td>Submitted</td><td>—</td>");
  });
});

describe("RequestView", () => {
  test("a draft shows the form and the cohort block, not the read-only summary", () => {
    const html = view({});
    expect(html).toContain('<h2 tabindex="-1">Synthetic cohort <small>Draft</small></h2>');
    expect(html).toContain(STATUS_TEXT.draft);
    expect(html).toContain("<form");
    expect(html).not.toContain('class="summary"');
    expect(html).toContain("v1-0123456789abcdef");
    expect(html).toContain(`href="/discover${shareHash(DETAIL.definition)}">Open in Discover`);
    expect(html).toContain("Delete draft");
  });
  test("a submitted request is read-only: no form, no Submit, signed attestations listed", () => {
    const html = view({status: "submitted", missing: [], attestations: [
      {attestation_version: "2026-10-30", text: "t", signed_as: "a@x.edu", signed_at: "2026-10-31T09:00:00Z"}]});
    expect(html).not.toContain("<form");
    expect(html).not.toContain("Submit request");
    expect(html).toContain('class="summary"');
    expect(html).toContain("MRN: synthetic reason");
    expect(html).toContain("R Example (r@example.edu)");
    expect(html).toContain("2026-10-31, version 2026-10-30");
    expect(html).toContain(STATUS_TEXT.submitted);
  });
  test("a returned request shows the form and the broker's message", () => {
    const html = view({status: "returned", reviews: [{id: "r1", reviewer: "broker", checklist: {}, decision: "return",
      notes: "please add the personnel list", decided_at: "2026-11-02T09:00:00Z"}]});
    expect(html).toContain("<form");
    expect(html).not.toContain("Delete draft");
    expect(html).toContain("return, 2026-11-02: please add the personnel list");
  });
  test("no messages, releases or attestations yet", () => {
    expect(view({}).match(/None yet\./g)?.length).toBe(3);
  });
  test("releases show the retention end", () => {
    const html = view({status: "fulfilled", releases: [{id: "x", file_name: "synthetic.csv", sha256: "0".repeat(64), row_count: 1,
      fields_released: [], recipients: [], sharepoint_link: "l", released_at: "2026-12-01T00:00:00Z"}]});
    expect(html).toContain("2026-12-01: synthetic.csv, keep until 2099-06-01");
  });
  test("every status has a label and a sentence", () => {
    for (const s of Object.keys(STATUS_LABEL) as (keyof typeof STATUS_LABEL)[]) expect(STATUS_TEXT[s].length).toBeGreaterThan(10);
    expect([editable("draft"), editable("returned"), editable("submitted"), editable("closed")]).toEqual([true, true, false, false]);
  });
});

describe("SubmitBlock", () => {
  const block = (detail: MyRequestDetail, dirty = false) =>
    renderToStaticMarkup(<SubmitBlock detail={detail} dirty={dirty} busy={false} onSubmit={() => {}} />);
  test("dirty: save first, nothing else", () => {
    const html = block({...DETAIL, missing: [], attestation: "TEXT"}, true);
    expect(html).toContain("Save the draft to check it before submitting.");
    expect(html).not.toContain("TEXT");
    expect(html).not.toContain("Submit request");
  });
  test("missing: the list, no attestation", () => {
    const html = block({...DETAIL, missing: ["state the purpose", "give the storage location"]});
    expect(html).toContain("Before you can submit:");
    expect(html).toContain("<li>state the purpose</li><li>give the storage location</li>");
    expect(html).not.toContain("blockquote");
    expect(html).not.toContain("Submit request");
  });
  test("ready: the text, the checkbox, and one primary button that is disabled until checked", () => {
    const html = block({...DETAIL, missing: [], attestation: "I attest that synthetic."});
    expect(html).toContain("<blockquote>I attest that synthetic.</blockquote>");
    expect(html).toContain("I attest to the statement above");
    expect(html.match(/btn-primary/g)?.length).toBe(1);
    expect(html).toMatch(/<button type="button" class="btn-primary" disabled="">Submit request<\/button>/);
  });
});

describe("IntakeForm", () => {
  const form = (d: Partial<MyRequestDetail> = {}) =>
    renderToStaticMarkup(<IntakeForm detail={{...DETAIL, ...d}} api={api} onChange={() => {}} />);
  test("the IRB's checklist and the document reference form, for the version you registered", () => {
    const html = form();
    expect(html).toContain("IRB TEST-0100 version 1: active, expires 2099-01-01.");
    expect(html).toContain("IRB approval letter: ✓ referenced");
    expect(html).toContain("Protocol excerpt: missing");
    expect(html).toContain("Link or location");
    expect(html).toContain("Add reference");
    expect(html).toContain("Don&#x27;t paste patient information.");
    expect(html).toContain("nothing is uploaded here");
  });
  test("a version you did not register: the hint, no reference form", () => {
    const html = form({irb: {...IRB, registered_by_you: false}});
    expect(html).toContain("To add documents, register a new version of this IRB.");
    expect(html).not.toContain("Add reference");
    expect(html).not.toContain("Link or location");
  });
  test("no IRB chosen: no checklist and no documents section", () => {
    const html = form({irb: null, irb_number: null, irb_version: null});
    expect(html).not.toContain("IRB documents");
    expect(html).not.toContain("referenced");
  });
  test("the saved values are in the form; the reason box shows for a chosen identifier only", () => {
    const html = form();
    expect(html).toContain("Reason for MRN");
    expect(html).not.toContain("Reason for Patient name");
    expect(html).toContain(">synthetic purpose</textarea>");
    expect(html).toContain('value="synthetic share"');
    expect(html).toContain('value="2099-06-01"');
    expect(html).toContain('value="r@example.edu"');
  });
  test("a dirty-free form shows the attestation when ready", () => {
    expect(form({missing: [], attestation: "SIGN THIS"})).toContain("<blockquote>SIGN THIS</blockquote>");
  });
  test("every input, select and textarea has a visible label or an aria-label", () => {
    const html = form();
    const bare = html.replace(/<label[^>]*>[\s\S]*?<\/label>/g, "");
    for (const tag of bare.match(/<(input|select|textarea)\b[^>]*>/g) ?? []) expect(tag).toContain("aria-label=");
    expect((html.match(/<(input|select|textarea)\b/g) ?? []).length).toBeGreaterThan(10);
  });
  test("with the registration form closed, its fields are not rendered", () => {
    expect(form()).not.toContain("Approved population");
  });
});

describe("toDraft", () => {
  test("round-trips the editable columns", () => {
    expect(toDraft(DETAIL)).toEqual({irb_number: "TEST-0100", irb_version: 1, purpose: "synthetic purpose",
      fields: ["demographics", "diagnosis"], identifiers: [{identifier: "mrn", reason: "synthetic reason"}],
      recipients: [{name: "R Example", email: "r@example.edu"}], storage_location: "synthetic share", retention_end: "2099-06-01"});
  });
  test("a fresh draft has no IRB and no retention end, and copies the lists", () => {
    const fresh = toDraft({...DETAIL, irb_number: null, irb_version: null, retention_end: null, identifiers: []});
    expect([fresh.irb_number, fresh.irb_version, fresh.retention_end]).toEqual([null, null, null]);
    const d = toDraft(DETAIL);
    d.recipients[0].name = "changed";
    expect(DETAIL.recipients[0].name).toBe("R Example");
  });
});

describe("exactIrb", () => {
  const options = [IRB, {...IRB, irb_number: "TEST-0200"}];
  test("a pasted or late-arriving number matches its suggestion, spaces ignored", () => {
    expect(exactIrb(options, " TEST-0200 ")?.irb_number).toBe("TEST-0200");
  });
  test("case is ignored, the suggestion keeps its canonical case", () => {
    expect(exactIrb(options, "test-0200")?.irb_number).toBe("TEST-0200");
  });
  test("a prefix or an unknown number matches nothing", () => {
    expect(exactIrb(options, "TEST-02")).toBeUndefined();
    expect(exactIrb([], "TEST-0100")).toBeUndefined();
  });
});
