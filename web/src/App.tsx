import { useCallback, useEffect, useRef, useState } from "react";
import { Answer, Count, TierPill, type Counted, type Tab } from "./Answer.tsx";
import { Builder } from "./Builder.tsx";
import { Compare } from "./Compare.tsx";
import { EMPTY, HISTORY_KEY, accrualPerYear, feasibility, pushVersion, readShareHash, shareHash, type History } from "./cohort.ts";
import { describeError, type Account, type Transport } from "./transport.ts";
import type { Definition, Me, Operation, Options } from "./types.ts";

function loadHistory(): History {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "null") as History | null;
    if (h && Array.isArray(h.versions) && h.versions.length && h.versions[h.current]) return h;
  } catch { /* unreadable storage: start fresh */ }
  return {versions: [{n: 1, definition: EMPTY}], current: 0};
}

export function FeasibilityPanel({statement, copied, onCopy, onClose, textareaRef}: {
  statement: string; copied: boolean; onCopy: () => void; onClose: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  return (
    <section aria-label="Feasibility statement" className="panel">
      {statement === ""
        ? <p role="status">Recounting… the statement updates when the count is current.</p>
        : <textarea readOnly aria-label="Feasibility statement" rows={6} value={statement} onFocus={(e) => e.currentTarget.select()} ref={textareaRef} />}
      <div className="row">
        <button type="button" disabled={statement === ""} onClick={onCopy}>Copy</button>
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

/** The patient count, tier and a jump to the answer: shown only at 600px and below (CSS). */
export function SummaryBar({answer, options}: {answer: Counted | null; options: Options | null}) {
  if (!answer) return null;
  const {d, r} = answer;
  const perYear = accrualPerYear(r.patients, d.population.years ?? options?.years ?? null);
  const view = (e: React.MouseEvent) => {
    e.preventDefault();   // a #answer-h fragment would replace the share hash in the address bar
    const h = document.getElementById("answer-h");
    h?.scrollIntoView();
    h?.focus();
  };
  return (
    <div className="summary-bar" role="region" aria-label="Cohort summary">
      <span><span className={r.patients == null ? "summary-count hatched" : "summary-count"}>
        <Count n={r.patients} minCell={r.min_cell} /></span> patients</span>
      {perYear != null && <TierPill perYear={perYear} />}
      <a href="#answer-h" onClick={view}>View</a>
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

export function App({transport, account}: {transport: Transport; account?: Account}) {
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
  const moreRef = useRef<HTMLButtonElement>(null);
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

  useEffect(() => {
    if (started.current) return;   // StrictMode runs effects twice in dev
    started.current = true;
    (async () => {
      const decoded = readShareHash(window.location.hash);
      if (window.location.hash.startsWith("#d=")) {
        try {
          if (decoded === null) throw new Error("it could not be read");
          const n = (decoded as {name?: unknown}).name;
          const r = await transport.apply(decoded as Definition, {op: "rename", name: typeof n === "string" ? n : ""});
          const h = histRef.current;
          if (JSON.stringify(r.definition) !== JSON.stringify(h.versions[h.current].definition)) setHist(pushVersion(h, r.definition));
        } catch (e) {
          setEditError({at: "builder", message: `This link does not hold a valid cohort: ${describeError(e)}`});
        }
      }
      try {
        setOptions(await transport.options({}));
      } catch (e) {
        setAnswerError(describeError(e));
      }
      setHist(histRef.current);   // puts the current version's share hash in the address bar
      refresh();
    })();
  }, [transport, setHist, refresh]);

  useEffect(() => { account?.me().then(setMe, () => {}); }, [account]);   // a failed me() shows nothing extra

  useEffect(() => {
    tabRef.current = tab;
    if (tab === "Pivot") refresh();
  }, [tab, refresh]);

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
      <header className="top">
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
        <div id="header-actions" className={menuOpen ? "actions open" : "actions"}
          onKeyDown={(e) => { if (e.key === "Escape" && menuOpen) { setMenuOpen(false); moreRef.current?.focus(); } }}>
          <button type="button" className="btn-secondary" aria-expanded={panel === "share"} onClick={share}>Share</button>
          <button type="button" className="btn-secondary" aria-expanded={panel === "compare"} disabled={single}
            aria-describedby={single ? "compare-why" : undefined} onClick={() => togglePanel("compare")}>Compare</button>
          {single && <span id="compare-why" className="hint">Make a change to compare versions</span>}
          <button type="button" className="btn-primary" aria-expanded={panel === "feasibility"}
            disabled={panel !== "feasibility" && (!answer || stale)} onClick={() => togglePanel("feasibility")}>Feasibility statement</button>
          {me && account && <Who me={me} onSignOut={() => { account.signOut().catch((e) => setEditError({at: "builder", message: `Sign-out failed: ${describeError(e)}`})); }} />}
        </div>
      </header>
      {panel === "share" && (
        <SharePanel link={window.location.href} copied={copied} cohortId={answer && !stale ? answer.r.cohort_id : null}
          onClose={() => setPanel(null)} />
      )}
      {panel === "compare" && (
        <Compare versions={hist.versions} transport={transport} years={options?.years ?? null} onClose={() => setPanel(null)} />
      )}
      {panel === "feasibility" && (
        <FeasibilityPanel statement={statement} copied={statementCopied} onCopy={copyStatement}
          onClose={() => setPanel(null)} textareaRef={statementRef} />
      )}
      <div className="cols">
        <div className="col-builder">
          {editError?.at === "builder" && <p role="alert" className="error">{editError.message}</p>}
          <Builder definition={current} transport={transport} options={options} onOp={(op) => edit(op, "builder")} />
        </div>
        <Answer definition={current} answer={answer} options={options} tab={tab} onTab={setTab}
          onOp={(op) => edit(op, "answer")} onRetry={refresh} busy={busy} error={answerError}
          editError={editError?.at === "answer" ? editError.message : null} />
      </div>
      <SummaryBar answer={answer} options={options} />
    </div>
  );
}
