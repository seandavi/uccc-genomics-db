import { useCallback, useEffect, useRef, useState } from "react";
import { Answer, type Counted, type Tab } from "./Answer.tsx";
import { Builder } from "./Builder.tsx";
import { EMPTY, HISTORY_KEY, pushVersion, readShareHash, shareHash, type History } from "./cohort.ts";
import { describeError, type Transport } from "./transport.ts";
import type { Definition, Operation, Options } from "./types.ts";

function loadHistory(): History {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "null") as History | null;
    if (h && Array.isArray(h.versions) && h.versions.length && h.versions[h.current]) return h;
  } catch { /* unreadable storage: start fresh */ }
  return {versions: [{n: 1, definition: EMPTY}], current: 0};
}

export function App({transport}: {transport: Transport}) {
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
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const seq = useRef(0);
  const started = useRef(false);

  const current: Definition = hist.versions[hist.current].definition;

  const setHist = useCallback((h: History) => {
    histRef.current = h;
    setHistState(h);
    const d = h.versions[h.current].definition;
    setName(d.name);
    setLink(null);
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

  useEffect(() => {
    tabRef.current = tab;
    if (tab === "Pivot") refresh();
  }, [tab, refresh]);

  const commitName = () => { if (name !== current.name) edit({op: "rename", name}, "builder"); };
  const share = async () => {
    if (navigator.clipboard) {
      try { await navigator.clipboard.writeText(window.location.href); setCopied(true); return; } catch { /* fall through */ }
    }
    setLink(window.location.href);
  };

  return (
    <div className="app">
      <header className="top">
        <h1>Discover</h1>
        <input aria-label="Cohort name" placeholder="Untitled cohort" value={name} maxLength={200}
          onChange={(e) => setName(e.target.value)} onBlur={commitName}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
        <label>Version{" "}
          <select aria-label="Version" value={hist.current}
            onChange={(e) => { setHist({...hist, current: Number(e.target.value)}); refresh(); }}>
            {hist.versions.map((v, i) => <option key={v.n} value={i}>v{v.n}</option>)}
          </select>
        </label>
        {answer && <code title="Cohort id">{answer.r.cohort_id}</code>}
        <button type="button" onClick={share}>Share link</button>
        {copied && <span role="status">Link copied</span>}
        {link && <input readOnly aria-label="Share link" className="link" value={link} autoFocus onFocus={(e) => e.currentTarget.select()} />}
      </header>
      <div className="cols">
        <div className="col-builder">
          {editError?.at === "builder" && <p role="alert" className="error">{editError.message}</p>}
          <Builder definition={current} transport={transport} options={options} onOp={(op) => edit(op, "builder")} />
        </div>
        <Answer definition={current} answer={answer} options={options} tab={tab} onTab={setTab}
          onOp={(op) => edit(op, "answer")} onRetry={refresh} busy={busy} error={answerError}
          editError={editError?.at === "answer" ? editError.message : null} />
        <aside aria-label="Assistant" className="assistant">
          <h2>Assistant</h2>
          <p>Coming later: ask in words and get a definition you can apply.</p>
        </aside>
      </div>
    </div>
  );
}
