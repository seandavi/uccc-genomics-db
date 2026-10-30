import { useCallback, useEffect, useRef, useState } from "react";
import { Answer, Count, TierPill, type Counted, type Tab } from "./Answer.tsx";
import { Builder } from "./Builder.tsx";
import { Compare } from "./Compare.tsx";
import { EMPTY, HISTORY_KEY, accrualPerYear, feasibility, pushVersion, readShareHash, shareHash, type History } from "./cohort.ts";
import { describeError, type Account, type RequestsApi, type Transport } from "./transport.ts";
import type { Definition, Me, Operation, Options } from "./types.ts";

function loadHistory(): History {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "null") as History | null;
    if (h && Array.isArray(h.versions) && h.versions.length && h.versions[h.current]) return h;
  } catch { /* unreadable storage: start fresh */ }
  return {versions: [{n: 1, definition: EMPTY}], current: 0};
}

const COMPARE_WHY = "Make a change to compare versions";

/** Focus back on the button that opened a panel; else on ⋯ (the trigger sits in the closed mobile menu); else on
 *  fallback (the answer heading). An element is skipped when hidden (offsetParent null) or disabled. */
export function focusTrigger(trigger: HTMLElement | null, more: HTMLElement | null, fallback: HTMLElement | null): void {
  const usable = (el: HTMLElement | null): el is HTMLElement =>
    el !== null && el.offsetParent !== null && !(el as HTMLButtonElement).disabled;
  (usable(trigger) ? trigger : usable(more) ? more : fallback)?.focus();
}

export function FeasibilityPanel({statement, copied, onCopy, onClose, textareaRef}: {
  statement: string; copied: boolean; onCopy: () => void; onClose: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);   // a floating layer takes focus when it opens
  return (
    <section aria-labelledby="feasibility-h" className="panel floating"
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <h2 id="feasibility-h" tabIndex={-1} ref={headingRef}>Feasibility statement for grant text</h2>
      {statement === ""
        ? <p role="status">Recounting… the statement updates when the count is current.</p>
        : <textarea readOnly aria-label="Feasibility statement" rows={8} value={statement} onFocus={(e) => e.currentTarget.select()} ref={textareaRef} />}
      <div className="row">
        <button type="button" className="btn-primary" disabled={statement === ""} onClick={onCopy}>Copy</button>
        {copied && <span role="status">Copied</span>}
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </section>
  );
}

export function SharePanel({link, copied, cohortId, onClose}: {
  link: string; copied: boolean; cohortId: string | null; onClose: () => void;
}) {
  return (
    <section aria-label="Share" className="panel">
      <div className="row">
        <input readOnly aria-label="Share link" className="link" value={link} autoFocus onFocus={(e) => e.currentTarget.select()} />
        {copied && <span role="status">Link copied</span>}
        <button type="button" onClick={onClose}>Close</button>
      </div>
      {cohortId && <p className="hint">Cohort ID (for support): <code>{cohortId}</code></p>}
    </section>
  );
}

/** Scrolls to the answer heading and moves focus there (it is always mounted, so it outlives whatever was focused). */
function jumpToAnswer() {
  const h = document.getElementById("answer-h");
  h?.scrollIntoView();
  h?.focus();
}

/** The patient count, tier and a jump to the answer: shown only at 600px and below (CSS). While a recount runs, or
 *  when the count is for an earlier version (the recount failed), they are dimmed and a word says so. */
export function SummaryBar({answer, options, busy = false, stale = false}: {
  answer: Counted | null; options: Options | null; busy?: boolean; stale?: boolean;
}) {
  if (!answer) return null;
  const {d, r} = answer;
  const perYear = accrualPerYear(r.patients, d.population.years ?? options?.years ?? null);
  const view = (e: React.MouseEvent) => {
    e.preventDefault();   // a #answer-h fragment would replace the share hash in the address bar
    jumpToAnswer();
  };
  const dim = busy || stale ? "dim" : undefined;
  return (
    <div className="summary-bar" role="region" aria-label="Cohort summary">
      <span className={dim}><span className={r.patients == null ? "summary-count hatched" : "summary-count"}>
        <Count n={r.patients} minCell={r.min_cell} /></span> patients</span>
      {perYear != null && <span className={dim}><TierPill perYear={perYear} /></span>}
      {(busy || stale) && <span className="hint">{busy ? "Counting…" : "Out of date"}</span>}
      <a href="#answer-h" onClick={view}>View answer</a>
    </div>
  );
}

export function Who({me, onSignOut}: {me: Me; onSignOut: () => void}) {
  return (
    <>
      <span className="who"><span className="sr-only">Signed in as </span>{me.email}</span>
      {me.sign_out && <button type="button" className="btn-tertiary" onClick={onSignOut}>Sign out</button>}
    </>
  );
}

/** d as a new version, through the server: apply(d, rename to its own name) validates it, against the vocabulary
 *  too, and returns its normal form. history() is read after the request, so an edit made meanwhile is kept;
 *  no version is added when the normal form equals the current version. Throws what transport.apply throws. */
export async function applyDefinition(d: Definition, history: () => History, transport: Pick<Transport, "apply">): Promise<History> {
  const n = (d as {name?: unknown}).name;   // a share link's JSON is unchecked until the server reads it
  const r = await transport.apply(d, {op: "rename", name: typeof n === "string" ? n : ""});
  const h = history();
  return JSON.stringify(r.definition) === JSON.stringify(h.versions[h.current].definition) ? h : pushVersion(h, r.definition);
}

/** What a URL hash does to the history. null: it is the current version's share hash (setHist wrote it),
 *  nothing to do. {history}: the history with the link's definition as a new version, or the history read
 *  after the request (unchanged) when the server's form equals the current version or the hash is not a
 *  share link. {error}: the text to show. history() is read again after the request, so an edit made
 *  meanwhile is kept. */
export async function applyShareHash(hash: string, history: () => History, transport: Pick<Transport, "apply">):
    Promise<{history: History} | {error: string} | null> {
  const before = history();
  if (hash === shareHash(before.versions[before.current].definition)) return null;
  if (!hash.startsWith("#d=")) return {history: before};
  try {
    const decoded = readShareHash(hash);
    if (decoded === null) throw new Error("it could not be read");
    return {history: await applyDefinition(decoded as Definition, history, transport)};
  } catch (e) {
    return {error: `This link does not hold a valid cohort: ${describeError(e)}`};
  }
}

export function App({transport, account, requests}: {transport: Transport; account?: Account; requests?: Pick<RequestsApi, "start">}) {
  const [me, setMe] = useState<Me | null>(null);
  const [hist, setHistState] = useState<History>(loadHistory);
  const histRef = useRef(hist);
  const [options, setOptions] = useState<Options | null>(null);
  const [answer, setAnswer] = useState<Counted | null>(null);
  const answerRef = useRef(answer);
  const [tab, setTab] = useState<Tab>("Accrual");
  const tabRef = useRef(tab);
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState<{at: "builder" | "answer"; message: string} | null>(null);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [name, setName] = useState(hist.versions[hist.current].definition.name);
  const [copied, setCopied] = useState(false);
  const [panel, setPanel] = useState<"compare" | "feasibility" | "share" | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const moreRef = useRef<HTMLButtonElement>(null);
  const shareRef = useRef<HTMLButtonElement>(null);
  const compareRef = useRef<HTMLButtonElement>(null);
  const feasibilityRef = useRef<HTMLButtonElement>(null);
  const [statementCopied, setStatementCopied] = useState(false);
  const statementRef = useRef<HTMLTextAreaElement>(null);
  const seq = useRef(0);
  const started = useRef(false);

  const current: Definition = hist.versions[hist.current].definition;

  const setHist = useCallback((h: History) => {
    histRef.current = h;
    setHistState(h);
    const d = h.versions[h.current].definition;
    setName(d.name);
    setCopied(false);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(h)); } catch { /* storage full or disabled */ }
    window.history.replaceState(null, "", shareHash(d));
  }, []);

  const setAnswerBoth = useCallback((a: Counted) => {
    answerRef.current = a;
    setAnswer(a);
  }, []);

  const refresh = useCallback(async () => {
    const mine = ++seq.current;
    const h = histRef.current;
    const d = h.versions[h.current].definition;
    setBusy(true);
    try {
      const last = answerRef.current;
      const same = last?.d === d;   // definitions are immutable objects (every edit makes a new one): identity is "unchanged"
      const r = same ? last.r : await transport.count(d);
      if (mine !== seq.current) return;
      const p = tabRef.current === "Pivot" && d.pivot ? (same && last.p) || await transport.pivot(d) : null;
      if (mine !== seq.current) return;
      setAnswerBoth({d, r, p});
      setAnswerError(null);
    } catch (e) {
      if (mine === seq.current) setAnswerError(describeError(e));
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }, [transport, setAnswerBoth]);

  const edit = useCallback(async (op: Operation, at: "builder" | "answer") => {
    try {
      const r = await transport.apply(histRef.current.versions[histRef.current.current].definition, op);
      setEditError(null);
      setHist(pushVersion(histRef.current, r.definition));
      refresh();
    } catch (e) {
      setEditError({at, message: describeError(e)});
    }
  }, [transport, setHist, refresh]);

  const applyExample = useCallback(async (d: Definition) => {
    try {
      setHist(await applyDefinition(d, () => histRef.current, transport));
      setEditError(null);
      refresh();
      requestAnimationFrame(jumpToAnswer);   // after the commit, so the heading reads the example's name ("Use →" unmounted the landing that held focus)
    } catch (e) {
      setEditError({at: "answer", message: `This example could not be used: ${describeError(e)}`});
    }
  }, [transport, setHist, refresh]);

  useEffect(() => {
    if (started.current) return;   // StrictMode runs effects twice in dev
    started.current = true;
    (async () => {
      const loaded = await applyShareHash(window.location.hash, () => histRef.current, transport);
      if (loaded && "error" in loaded) setEditError({at: "builder", message: loaded.error});
      else if (loaded && "history" in loaded && loaded.history !== histRef.current) setHist(loaded.history);
      try {
        setOptions(await transport.options({}));
      } catch (e) {
        setAnswerError(describeError(e));
      }
      setHist(histRef.current);   // puts the current version's share hash in the address bar
      refresh();
    })();
  }, [transport, setHist, refresh]);

  useEffect(() => {
    const onHashChange = async () => {
      const loaded = await applyShareHash(window.location.hash, () => histRef.current, transport);
      if (loaded === null) return;   // the app's own hash
      setEditError("error" in loaded ? {at: "builder", message: loaded.error} : null);
      setHist("history" in loaded ? loaded.history : histRef.current);   // the address bar shows the current version's share hash again
      refresh();
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [transport, setHist, refresh]);

  useEffect(() => { account?.me().then(setMe, () => {}); }, [account]);   // a failed me() shows nothing extra

  useEffect(() => {
    tabRef.current = tab;
    if (tab === "Pivot") refresh();
  }, [tab, refresh]);

  const closePanel = () => {
    const trigger = panel ? {share: shareRef, compare: compareRef, feasibility: feasibilityRef}[panel].current : null;
    setPanel(null);
    requestAnimationFrame(() => focusTrigger(trigger, moreRef.current, document.getElementById("answer-h")));   // after the commit: a trigger the close disabled is skipped
  };
  const commitName = () => { if (name !== current.name) edit({op: "rename", name}, "builder"); };
  const go = (i: number) => { setHist({...histRef.current, current: i}); refresh(); };
  const share = async () => {
    setMenuOpen(false);
    if (panel === "share") { setPanel(null); return; }
    setPanel("share");
    setCopied(false);
    if (navigator.clipboard) {
      try { await navigator.clipboard.writeText(window.location.href); setCopied(true); } catch { /* the panel shows the link to copy */ }
    }
  };

  const startRequest = async () => {
    if (!requests) return;
    setStarting(true);
    try {
      window.location.assign("/requests#" + (await requests.start(current)).id);
    } catch (e) {
      setEditError({at: "builder", message: `Could not start a request: ${describeError(e)}`});
      setStarting(false);
    }
  };

  const stale = !!answer && answer.d !== current;
  const statement = answer && !stale ? feasibility(answer.d, answer.r, answer.d.population.years ?? options?.years ?? null) : "";
  useEffect(() => setStatementCopied(false), [statement]);
  const togglePanel = (p: "compare" | "feasibility") => { setPanel(panel === p ? null : p); setStatementCopied(false); setMenuOpen(false); };
  const single = hist.versions.length < 2;
  const last = hist.versions.length - 1;
  const copyStatement = async () => {
    if (statement === "") return;
    if (navigator.clipboard) {
      try { await navigator.clipboard.writeText(statement); setStatementCopied(true); return; } catch { /* fall through */ }
    }
    statementRef.current?.select();
  };

  return (
    <div className="app">
      <header className="top"
        onKeyDown={(e) => { if (e.key === "Escape" && menuOpen) { setMenuOpen(false); moreRef.current?.focus(); } }}
        onBlur={(e) => {   // Tab out of the header closes the menu, so it never covers the focused control (WCAG 2.4.11)
          if (menuOpen && e.relatedTarget instanceof Node && !e.currentTarget.contains(e.relatedTarget)) setMenuOpen(false);
        }}>
        <h1>Discover</h1>
        <input aria-label="Cohort name" className="cohort-name" placeholder="Untitled cohort" value={name} maxLength={200}
          onChange={(e) => setName(e.target.value)} onBlur={commitName}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
        <div className="history">
          <button type="button" aria-label="Previous edit" title="Previous edit" disabled={hist.current === 0}
            onClick={() => go(hist.current - 1)}>↶</button>
          <button type="button" aria-label="Next edit" title="Next edit" disabled={hist.current === last}
            onClick={() => go(hist.current + 1)}>↷</button>
          <label>History{" "}
            <select aria-label="History" value={hist.current} onChange={(e) => go(Number(e.target.value))}>
              {hist.versions.map((v, i) => <option key={v.n} value={i}>Edit {v.n}</option>)}
            </select>
          </label>
        </div>
        <button type="button" ref={moreRef} className="more" aria-label="More actions" aria-expanded={menuOpen}
          aria-controls="header-actions" onClick={() => setMenuOpen(!menuOpen)}>⋯</button>
        <div id="header-actions" className={menuOpen ? "actions open" : "actions"}>
          <button type="button" ref={shareRef} className="btn-secondary" aria-expanded={panel === "share"} onClick={share}>Share</button>
          <button type="button" ref={compareRef} className="btn-secondary" aria-expanded={panel === "compare"} disabled={single}
            aria-describedby={single ? "compare-why" : undefined} title={single ? COMPARE_WHY : undefined}
            onClick={() => togglePanel("compare")}>Compare</button>
          {single && <span id="compare-why" className="sr-only">{COMPARE_WHY}</span>}
          <button type="button" ref={feasibilityRef} className="btn-primary" aria-expanded={panel === "feasibility"}
            disabled={panel !== "feasibility" && (!answer || stale)} onClick={() => togglePanel("feasibility")}>Feasibility statement</button>
          {requests && (
            <>
              <button type="button" className="btn-secondary" disabled={starting} onClick={startRequest}
                title="Saves this cohort and opens a request form; identified data comes only from the honest broker">Request identified data</button>
              <a className="btn-tertiary" href="/requests">My requests</a>
            </>
          )}
          {me && account && <Who me={me} onSignOut={() => { account.signOut().catch((e) => setEditError({at: "builder", message: `Sign-out failed: ${describeError(e)}`})); }} />}
        </div>
      </header>
      {panel === "share" && (
        <SharePanel link={window.location.href} copied={copied} cohortId={answer && !stale ? answer.r.cohort_id : null}
          onClose={closePanel} />
      )}
      {panel === "compare" && (
        <Compare versions={hist.versions} transport={transport} years={options?.years ?? null} onClose={closePanel} />
      )}
      {panel === "feasibility" && (
        <div className="panel-anchor">
          <FeasibilityPanel statement={statement} copied={statementCopied} onCopy={copyStatement}
            onClose={closePanel} textareaRef={statementRef} />
        </div>
      )}
      <div className="cols">
        <div className="col-builder">
          {editError?.at === "builder" && <p role="alert" className="error">{editError.message}</p>}
          <Builder definition={current} transport={transport} options={options} onOp={(op) => edit(op, "builder")} />
        </div>
        <Answer definition={current} answer={answer} options={options} tab={tab} onTab={setTab}
          onOp={(op) => edit(op, "answer")} onRetry={refresh} busy={busy} error={answerError} onExample={applyExample}
          editError={editError?.at === "answer" ? editError.message : null} />
      </div>
      <SummaryBar answer={answer} options={options} busy={busy} stale={stale} />
    </div>
  );
}
