import { useEffect, useRef, useState } from "react";
import { Who } from "./App.tsx";
import { shareHash } from "./cohort.ts";
import {
  DOC_LABEL, FIELD_LABEL, exactIrb, IDENTIFIER_LABEL, STATUS_LABEL, STATUS_TEXT, editable, toDraft,
} from "./requests.ts";
import { TransportError, describeError, type Account, type RequestsApi } from "./transport.ts";
import type {
  DocType, Identifier, IrbDocumentCreate, IrbStatus, Me, MyRequestDetail, RequestDraft, RequestField, Requests,
} from "./types.ts";

const day = (iso: string) => iso.slice(0, 10);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const FIELDS = Object.keys(FIELD_LABEL) as RequestField[];
const IDENTIFIERS = Object.keys(IDENTIFIER_LABEL) as Identifier[];
const REQUIRED_DOCS: DocType[] = ["approval_letter", "personnel_list", "protocol_excerpt"];
const DOC_TYPES: DocType[] = [...REQUIRED_DOCS, "consent_form"];

export function RequestList({requests}: {requests: Requests}) {
  if (requests.requests.length === 0)
    return <p>No requests yet. In Discover, build a cohort and choose Request identified data.</p>;
  return (
    <table className="list">
      <thead><tr><th scope="col">Cohort</th><th scope="col">Status</th><th scope="col">IRB</th><th scope="col">Updated</th></tr></thead>
      <tbody>
        {requests.requests.map((r) => (
          <tr key={r.id}>
            <th scope="row"><a href={`#${r.id}`}>{r.definition.name || "Untitled cohort"}</a></th>
            <td>{STATUS_LABEL[r.status]}</td>
            <td>{r.irb_number ? `${r.irb_number} v${r.irb_version}` : "—"}</td>
            <td>{day(r.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Summary({detail}: {detail: MyRequestDetail}) {
  return (
    <dl className="summary">
      <dt>IRB authorization</dt><dd>{detail.irb_number ? `${detail.irb_number} version ${detail.irb_version}` : "—"}</dd>
      <dt>Purpose</dt><dd>{detail.purpose || "—"}</dd>
      <dt>Fields</dt><dd>{detail.fields.length ? detail.fields.map((f) => FIELD_LABEL[f as RequestField] ?? f).join(", ") : "None"}</dd>
      <dt>Identifiers</dt>
      <dd>{detail.identifiers.length === 0 ? "—" : (
        <ul>{detail.identifiers.map((i) => <li key={i.identifier}>{IDENTIFIER_LABEL[i.identifier]}: {i.reason}</li>)}</ul>)}</dd>
      <dt>Recipients</dt>
      <dd>{detail.recipients.length === 0 ? "—" : (
        <ul>{detail.recipients.map((r) => <li key={r.email}>{r.name} ({r.email})</li>)}</ul>)}</dd>
      <dt>Storage location</dt><dd>{detail.storage_location || "—"}</dd>
      <dt>Retention end</dt><dd>{detail.retention_end ?? "—"}</dd>
    </dl>
  );
}

/** The submit block's three states: unsaved edits, what is missing, or the attestation to sign. */
export function SubmitBlock({detail, dirty, busy, onSubmit}: {
  detail: MyRequestDetail; dirty: boolean; busy: boolean; onSubmit: () => void;
}) {
  const [attested, setAttested] = useState(false);
  if (dirty) return <p className="hint" role="status">Save the draft to check it before submitting.</p>;
  if (detail.missing.length > 0)
    return (
      <>
        <h3>Before you can submit:</h3>
        <ul>{detail.missing.map((m) => <li key={m}>{m}</li>)}</ul>
      </>
    );
  return (
    <>
      <h3>Requester attestation</h3>
      <blockquote>{detail.attestation}</blockquote>
      <label><input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} /> I attest to the statement above</label>
      <div className="row">
        <button type="button" className="btn-primary" disabled={!attested || busy} onClick={onSubmit}>Submit request</button>
      </div>
    </>
  );
}

function Checklist({irb}: {irb: IrbStatus}) {
  return (
    <div>
      <p>
        IRB {irb.irb_number} version {irb.version}: {irb.status}
        {irb.expiration_date ? `, expires ${irb.expiration_date}` : ", no expiration"}.
      </p>
      <ul className="checklist">
        {DOC_TYPES.map((t) => (
          <li key={t}>{DOC_LABEL[t]}: {irb.doc_types.includes(t) ? "✓ referenced" : REQUIRED_DOCS.includes(t) ? "missing" : "not referenced"}</li>
        ))}
      </ul>
    </div>
  );
}

const BLANK_IRB = {irb_number: "", pi: "", approval_date: "", expiration_date: "", hipaa_pathway: "", approved_population: ""};
const BLANK_DOC = {doc_type: "approval_letter" as DocType, title: "", file_ref: "", section_cited: "", protocol_version: ""};

export function IntakeForm({detail, api, onChange}: {
  detail: MyRequestDetail; api: Pick<RequestsApi, "update" | "submit" | "remove" | "get" | "lookupIrb" | "registerIrb" | "addDocument">;
  onChange: (d: MyRequestDetail) => void;
}) {
  const [draft, setDraft] = useState<RequestDraft>(() => toDraft(detail));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [irb, setIrb] = useState<IrbStatus | null>(detail.irb ?? null);
  const [query, setQuery] = useState(detail.irb_number ?? "");
  const [options, setOptions] = useState<IrbStatus[]>([]);
  const [looked, setLooked] = useState<string | null>(null);   // the number the suggestions were fetched for
  const alertRef = useRef<HTMLParagraphElement>(null);
  const [registering, setRegistering] = useState(false);
  const [reg, setReg] = useState(BLANK_IRB);
  const [doc, setDoc] = useState(BLANK_DOC);

  useEffect(() => { if (error) alertRef.current?.scrollIntoView?.({block: "center"}); }, [error]);   // the buttons are far below

  const edit = (patch: Partial<RequestDraft>) => { setDraft((d) => ({...d, ...patch})); setDirty(true); };
  const select = (s: IrbStatus | null) => {
    setIrb(s);
    edit({irb_number: s?.irb_number ?? null, irb_version: s?.version ?? null});
  };

  useEffect(() => {   // the number box's suggestions
    const q = query.trim();
    if (q === "") { setOptions([]); setLooked(null); return; }
    let live = true;
    const t = setTimeout(() => {
      api.lookupIrb(q).then((r) => { if (live) { setOptions(r.authorizations); setLooked(q); } },
                            () => { if (live) setOptions([]); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [query, api]);

  // An exact number is chosen whenever the suggestions and the box agree, however it got there (typed, pasted, late lookup).
  const match = exactIrb(options, query);
  useEffect(() => {
    if (match && draft.irb_number !== match.irb_number) select(match);
    if (match && query !== match.irb_number) setQuery(match.irb_number);   // show the canonical case
  }, [match]);

  const typed = (value: string) => {
    setQuery(value);
    if (draft.irb_number && draft.irb_number.toLowerCase() !== value.trim().toLowerCase()) select(null);
  };

  const run = async (what: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await what(); } catch (e) { setError(describeError(e)); } finally { setBusy(false); }
  };

  const save = () => run(async () => {
    if (draft.identifiers.some((i) => i.reason.trim() === "")) throw new Error("Give a reason for each identifier you choose.");
    const recipients = draft.recipients.filter((r) => r.name.trim() !== "" || r.email.trim() !== "");
    onChange(await api.update(detail.id, {...draft, recipients}));
    setDraft((d) => ({...d, recipients}));
    setDirty(false);
  });

  const register = () => run(async () => {
    const s = await api.registerIrb({
      irb_number: reg.irb_number, pi: reg.pi, approval_date: reg.approval_date,
      expiration_date: reg.expiration_date || null, hipaa_pathway: reg.hipaa_pathway, approved_population: reg.approved_population,
    });
    setRegistering(false);
    setQuery(s.irb_number);
    select(s);
  });

  const addDocument = () => run(async () => {
    if (!irb) return;
    const d: IrbDocumentCreate = {
      doc_type: doc.doc_type, title: doc.title, file_ref: doc.file_ref,
      section_cited: doc.section_cited || null, protocol_version: doc.protocol_version || null,
    };
    setIrb(await api.addDocument(irb.irb_number, irb.version, d));
    setDoc(BLANK_DOC);
    setDirty(true);   // what is missing has changed: save to recompute
  });

  const submit = () => run(async () => {
    try {
      onChange(await api.submit(detail.id, detail.attestation ?? ""));
    } catch (e) {
      if (e instanceof TransportError && e.status === 409) onChange(await api.get(detail.id));
      throw e;
    }
  });

  const remove = () => {
    if (!window.confirm("Delete this draft? The saved cohort is kept.")) return;
    run(async () => { await api.remove(detail.id); window.location.hash = ""; });
  };

  const toggleIdentifier = (id: Identifier, on: boolean) =>
    edit({identifiers: on ? [...draft.identifiers, {identifier: id, reason: ""}] : draft.identifiers.filter((i) => i.identifier !== id)});
  const setRecipient = (n: number, patch: Partial<{name: string; email: string}>) =>
    edit({recipients: draft.recipients.map((r, i) => (i === n ? {...r, ...patch} : r))});

  return (
    <form className="intake" onSubmit={(e) => e.preventDefault()}>
      {error && <p ref={alertRef} role="alert" className="error">{error}</p>}
      <fieldset>
        <legend>IRB authorization</legend>
        <label>IRB number{" "}
          <input aria-label="IRB number" list="irb-options" value={query} onChange={(e) => typed(e.target.value)} />
        </label>
        <datalist id="irb-options">{options.map((o) => <option key={o.irb_number} value={o.irb_number} />)}</datalist>
        <button type="button" className="btn-tertiary" aria-expanded={registering} onClick={() => { setRegistering(!registering); setReg({...BLANK_IRB, irb_number: query.trim()}); }}>
          Register a new IRB version</button>
        {!irb && looked === query.trim() && !match && (
          <p className="hint">No IRB {looked} on file. Register it below if it is new.</p>
        )}
        {irb && <Checklist irb={irb} />}
        {registering && (
          <div className="editor">
            <label>New IRB number <input value={reg.irb_number} onChange={(e) => setReg({...reg, irb_number: e.target.value})} /></label>
            <label>PI <input value={reg.pi} onChange={(e) => setReg({...reg, pi: e.target.value})} /></label>
            <label>Approval date <input type="date" value={reg.approval_date} onChange={(e) => setReg({...reg, approval_date: e.target.value})} /></label>
            <label>Expiration date <input type="date" value={reg.expiration_date} onChange={(e) => setReg({...reg, expiration_date: e.target.value})} /></label>
            <label>HIPAA pathway <input value={reg.hipaa_pathway} onChange={(e) => setReg({...reg, hipaa_pathway: e.target.value})} /></label>
            <label>Approved population <textarea rows={3} value={reg.approved_population} onChange={(e) => setReg({...reg, approved_population: e.target.value})} /></label>
            <div className="row"><button type="button" className="btn-secondary" disabled={busy} onClick={register}>Register</button></div>
          </div>
        )}
      </fieldset>

      {irb && (
        <fieldset>
          <legend>IRB documents</legend>
          <p className="hint">Give a link or where the document is filed (for example a SharePoint folder). Don't paste patient information.
            The honest broker files copies; nothing is uploaded here.</p>
          {irb.registered_by_you ? (
            <div className="editor">
              <label>Document type{" "}
                <select value={doc.doc_type} onChange={(e) => setDoc({...doc, doc_type: e.target.value as DocType})}>
                  {DOC_TYPES.map((t) => <option key={t} value={t}>{DOC_LABEL[t]}</option>)}
                </select>
              </label>
              <label>Title or version <input value={doc.title} onChange={(e) => setDoc({...doc, title: e.target.value})} /></label>
              <label>Link or location <input value={doc.file_ref} onChange={(e) => setDoc({...doc, file_ref: e.target.value})} /></label>
              {doc.doc_type === "protocol_excerpt" && (
                <>
                  <label>Section <input value={doc.section_cited} onChange={(e) => setDoc({...doc, section_cited: e.target.value})} /></label>
                  <label>Protocol version <input value={doc.protocol_version} onChange={(e) => setDoc({...doc, protocol_version: e.target.value})} /></label>
                </>
              )}
              <div className="row"><button type="button" className="btn-secondary" disabled={busy} onClick={addDocument}>Add reference</button></div>
            </div>
          ) : <p className="hint">To add documents, register a new version of this IRB.</p>}
        </fieldset>
      )}

      <fieldset>
        <legend>Fields</legend>
        <div className="checks">
          {FIELDS.map((f) => (
            <label key={f}><input type="checkbox" checked={draft.fields.includes(f)}
              onChange={(e) => edit({fields: e.target.checked ? [...draft.fields, f] : draft.fields.filter((x) => x !== f)})} /> {FIELD_LABEL[f]}</label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Identifiers</legend>
        {IDENTIFIERS.map((id) => {
          const chosen = draft.identifiers.find((i) => i.identifier === id);
          return (
            <div key={id}>
              <label><input type="checkbox" checked={!!chosen} onChange={(e) => toggleIdentifier(id, e.target.checked)} /> {IDENTIFIER_LABEL[id]}</label>
              {chosen && (
                <label>Reason for {IDENTIFIER_LABEL[id]}{" "}
                  <textarea rows={2} required value={chosen.reason}
                    onChange={(e) => edit({identifiers: draft.identifiers.map((i) => (i.identifier === id ? {...i, reason: e.target.value} : i))})} />
                </label>
              )}
            </div>
          );
        })}
      </fieldset>

      <fieldset>
        <legend>Recipients</legend>
        {draft.recipients.map((r, n) => (
          <div className="row" key={n}>
            <label>Recipient {n + 1} name <input value={r.name} onChange={(e) => setRecipient(n, {name: e.target.value})} /></label>
            <label>Recipient {n + 1} email <input type="email" value={r.email} onChange={(e) => setRecipient(n, {email: e.target.value})} /></label>
            <button type="button" onClick={() => edit({recipients: draft.recipients.filter((_, i) => i !== n)})}>Remove recipient {n + 1}</button>
          </div>
        ))}
        <button type="button" onClick={() => edit({recipients: [...draft.recipients, {name: "", email: ""}]})}>Add recipient</button>
      </fieldset>

      <fieldset>
        <legend>Use and storage</legend>
        <label>Purpose <textarea rows={4} value={draft.purpose} onChange={(e) => edit({purpose: e.target.value})} /></label>
        <label>Storage location <input value={draft.storage_location} onChange={(e) => edit({storage_location: e.target.value})} /></label>
        <label>Retention end <input type="date" value={draft.retention_end ?? ""} onChange={(e) => edit({retention_end: e.target.value || null})} /></label>
      </fieldset>

      <div className="row">
        <button type="button" className="btn-secondary" disabled={busy} onClick={save}>Save draft</button>
        {detail.status === "draft" && <button type="button" disabled={busy} onClick={remove}>Delete draft</button>}
      </div>
      <SubmitBlock key={detail.attestation ?? ""} detail={detail} dirty={dirty} busy={busy} onSubmit={submit} />
    </form>
  );
}

export function RequestView({detail, api, onChange}: {
  detail: MyRequestDetail; api: Parameters<typeof IntakeForm>[0]["api"]; onChange: (d: MyRequestDetail) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return (
    <article>
      <h2 tabIndex={-1} ref={heading}>{detail.definition.name || "Untitled cohort"} <small>{STATUS_LABEL[detail.status]}</small></h2>
      <p>{STATUS_TEXT[detail.status]}</p>
      <section aria-label="Cohort">
        <h3>Cohort</h3>
        <p className="hint">Cohort ID <code>{detail.cohort_id}</code>{detail.snapshot_id && <> · data build <code>{detail.snapshot_id}</code></>}</p>
        <p><a href={`/discover${shareHash(detail.definition)}`}>Open in Discover</a></p>
      </section>
      {editable(detail.status) ? <IntakeForm detail={detail} api={api} onChange={onChange} /> : <Summary detail={detail} />}
      <section aria-label="Messages from the honest broker">
        <h3>Messages from the honest broker</h3>
        {detail.reviews.length === 0 ? <p>None yet.</p> : (
          <ul>{detail.reviews.map((r) => <li key={r.id}>{r.decision}, {day(r.decided_at)}: {r.notes}</li>)}</ul>)}
      </section>
      <section aria-label="Releases">
        <h3>Releases</h3>
        {detail.releases.length === 0 ? <p>None yet.</p> : (
          <ul>{detail.releases.map((r) => (
            <li key={r.id}>{day(r.released_at)}: {r.file_name}{detail.retention_end && `, keep until ${detail.retention_end}`}</li>))}</ul>)}
      </section>
      <section aria-label="Signed attestations">
        <h3>Signed attestations</h3>
        {detail.attestations.length === 0 ? <p>None yet.</p> : (
          <ul>{detail.attestations.map((a) => <li key={a.signed_at}>{day(a.signed_at)}, version {a.attestation_version}</li>)}</ul>)}
      </section>
    </article>
  );
}

export function RequestsPage({api, account}: {api: Parameters<typeof RequestView>[0]["api"] & Pick<RequestsApi, "list">; account?: Account}) {
  const [me, setMe] = useState<Me | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [list, setList] = useState<Requests | null>(null);
  const [detail, setDetail] = useState<MyRequestDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const read = () => { const h = window.location.hash.slice(1); setSelected(UUID.test(h) ? h : null); };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  useEffect(() => { account?.me().then(setMe, () => {}); }, [account]);
  useEffect(() => {
    setError(null);
    setDetail(null);
    setList(null);
    const load = selected === null ? api.list().then(setList) : api.get(selected).then(setDetail);
    load.catch((e) => setError(describeError(e)));
  }, [selected, api]);

  return (
    <div className="app requests">
      <header className="top">
        <h1>My requests</h1>
        <div className="actions">
          <a className="btn-tertiary" href="/discover">Back to Discover</a>
          {me && account && <Who me={me} onSignOut={() => { account.signOut().catch((e) => setError(`Sign-out failed: ${describeError(e)}`)); }} />}
        </div>
      </header>
      <main>
        <p className="intro">Discover shows counts only. Identified data (MRNs, true dates, report ids) comes only from the honest broker,
          for an active IRB approval, delivered to restricted storage.</p>
        {error && <p role="alert" className="error">{error}</p>}
        {selected !== null && <p><a href="#">← All requests</a></p>}
        {selected === null && list && <RequestList requests={list} />}
        {selected !== null && detail && <RequestView key={detail.id} detail={detail} api={api} onChange={setDetail} />}
      </main>
    </div>
  );
}
