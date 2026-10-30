import { useState, type KeyboardEvent, type ReactNode } from "react";
import {
  BREAKDOWN_DIMS, accrualPerYear, barPct, criterionBody, criterionLabel, fmtCount, fmtPerYear, isEmptyDefinition, pct, pivotAxes, populationLabel, tierFor, yearSlots,
} from "./cohort.ts";
import type { BreakdownDim, CountResult, Definition, Operation, Options, PivotResult } from "./types.ts";

export const TABS = ["Accrual", "Breakdown", "Pivot", "Data notes"] as const;
export type Tab = (typeof TABS)[number];

export const SUPPRESSED = "Fewer than 5 patients, or hidden so that a small count cannot be worked out by subtraction";

/** A count as the API returned it: null is "<5", never 0 or blank. */
export function Count({n, minCell}: {n: number | null | undefined; minCell: number}) {
  if (n == null) return <span className="suppressed" title={SUPPRESSED}>{`<${minCell}`}</span>;
  return <>{fmtCount(n)}</>;
}

function stepLabel(d: Definition, i: number, criterion: string | null): string {
  if (i === 0 || criterion == null) return populationLabel(d.population);
  const c = d.criteria.find((x) => x.id === criterion);
  if (!c) return `+ ${criterion}`;
  const label = criterionBody(c);   // the mode word is the prefix, once
  return c.mode === "exclude" ? `− ${label}` : c.mode === "tested_negative" ? `+ tested negative: ${label}` : `+ ${label}`;
}

/** The accrual tier as a pill: `tier tier-high|tier-moderate|tier-low`, with the tier's description as its title. */
export function TierPill({perYear}: {perYear: number}) {
  const t = tierFor(perYear);
  return <span className={`tier tier-${t.name.split(" ")[0].toLowerCase()}`} title={t.desc}>{t.name}</span>;
}

function Cards({r, d, options}: {r: CountResult; d: Definition; options: Options | null}) {
  const pop = populationLabel(d.population);
  const window = d.population.years ?? options?.years ?? null;
  const perYear = accrualPerYear(r.patients, window);
  const share = pct(r.patients, r.denominator);
  return (
    <div className="cards">
      <div className="card hero">
        <h3>Patients</h3>
        <p className="big"><Count n={r.patients} minCell={r.min_cell} /></p>
        <p className="sub">{r.reports == null
          ? <span className="suppressed" title={SUPPRESSED}>reports not shown</span>
          : <>in <Count n={r.reports} minCell={r.min_cell} /> reports</>}</p>
      </div>
      <div className="card">
        <h3>Accrual</h3>
        <p className="big">{perYear == null ? "–" : fmtPerYear(perYear)}</p>
        {window && <p className="sub">per year, {window[0]}–{window[1]}</p>}
        {perYear != null && <p className="sub"><TierPill perYear={perYear} /></p>}
      </div>
      {!isEmptyDefinition(d) && <div className="card">
        <h3>Share of population</h3>
        <p className="big">{share ?? "–"}</p>
        <p className="sub">of <Count n={r.denominator} minCell={r.min_cell} /> patients {pop === "All patients" ? "(all patients)" : `in ${pop}`}</p>
      </div>}
    </div>
  );
}

export const DATA_FOOTNOTE = "Not in this data: stage, treatment, outcomes, race and ethnicity. "
  + "Dates are shifted for de-identification; the last years are partial.";

function DataFootnote({onTab}: {onTab: (t: Tab) => void}) {
  return <p className="hint footnote">{DATA_FOOTNOTE}{" "}
    <button type="button" className="btn-tertiary" onClick={() => onTab("Data notes")}>More in Data notes</button></p>;
}

function Funnel({r, d}: {r: CountResult; d: Definition}) {
  const max = Math.max(1, ...r.funnel.map((s) => s.patients ?? 0));
  return (
    <section aria-labelledby="funnel-h">
      <h3 id="funnel-h">How each criterion narrows the cohort</h3>
      <ol className="funnel">
        {r.funnel.map((s, i) => (
          <li key={i}>
            <span className="label">{stepLabel(d, i, s.criterion)}</span>
            <span className="num"><Count n={s.patients} minCell={r.min_cell} /></span>
            <span className="track" aria-hidden="true">
              <span className={s.patients == null ? "bar hatched" : "bar"} style={{width: `${barPct(s.patients, max, r.min_cell)}%`}} />
            </span>
          </li>
        ))}
      </ol>
      <p className="legend"><span className="swatch hatched" aria-hidden="true" /> {`<${r.min_cell}`}: {SUPPRESSED.toLowerCase()}.</p>
    </section>
  );
}

function Loosen({r, d, stale, onOp}: {r: CountResult; d: Definition; stale: boolean; onOp: (op: Operation) => void}) {
  if (r.loosen_offered === false) {   // the definition has neighbours: a suggestion would need its own privacy checks
    return r.patients == null
      ? <div className="loosen"><p>Too few patients to show, or hidden so a small group cannot be worked out by subtraction.</p></div>
      : null;
  }
  if (r.patients != null && r.loosen.length === 0) return null;
  return (
    <div className="loosen">
      {r.patients == null && <p><strong>Too few patients to show.</strong></p>}
      {r.loosen.length === 0
        ? <p>No single criterion, dropped, brings this cohort to {r.min_cell} or more.</p>
        : <ul>{r.loosen.map((l) => {
            const c = d.criteria.find((x) => x.id === l.drop);
            return (
              <li key={l.drop}>
                Drop {c ? criterionLabel(c) : l.drop} → {fmtCount(l.patients, r.min_cell)} patients{" "}
                <button type="button" disabled={stale} onClick={() => onOp({op: "remove_criterion", id: l.drop})}>Drop</button>
              </li>
            );
          })}</ul>}
    </div>
  );
}

const ACCRUAL = "Patients by year of first qualifying report";

function AccrualTab({r}: {r: CountResult}) {
  const slots = yearSlots(r.by_year);
  if (slots.length === 0) return <p>No years to show.</p>;
  const max = Math.max(1, ...r.by_year.map((y) => y.patients ?? 0));
  const allHidden = r.by_year.every((y) => y.patients == null);
  const short = slots.length > 12;
  const partial = r.by_year.some((y) => !y.complete);
  const gap = slots.some((s) => s.row == null);
  const hidden = r.by_year.some((y) => y.patients == null);
  return (
    <div>
      <figure className="accrual">
        {allHidden
          ? <p className="strip"><span className="bar hatched" aria-hidden="true" /><span>{`Every year under ${r.min_cell} or hidden`}</span></p>
          : <div className="bars" role="group" aria-label={ACCRUAL}>
              {slots.map(({year, row}) => (
                <div key={year} className={row == null ? "col gap" : row.complete ? "col" : "col partial"}>
                  <div className="barbox" aria-hidden="true">
                    {row && <div className={row.patients == null ? "vbar hatched" : "vbar"}
                      style={{height: `${barPct(row.patients, max, r.min_cell)}%`}} />}
                  </div>
                  <div className="barlabel" aria-hidden="true">
                    <span>{row ? <Count n={row.patients} minCell={r.min_cell} /> : "–"}</span>
                    <span>{`${short ? `’${String(year).slice(-2)}` : year}${row && !row.complete ? "*" : ""}`}</span>
                  </div>
                </div>
              ))}
            </div>}
        <figcaption>{ACCRUAL}</figcaption>
      </figure>
      {(partial || gap || hidden) && <p className="legend">
        {partial && !allHidden && <span>* partial year</span>}
        {gap && !allHidden && <span>–: no patients that year</span>}
        {hidden && <span><span className="swatch hatched" aria-hidden="true" /> {`<${r.min_cell}`}: {SUPPRESSED.toLowerCase()}.</span>}
      </p>}
      <table className="sr-only">
        <caption>{ACCRUAL}</caption>
        <thead><tr><th scope="col">Year</th><th scope="col">Patients</th><th scope="col">Complete</th></tr></thead>
        <tbody>{slots.map(({year, row}) => (
          <tr key={year}><th scope="row">{year}</th>
            {row
              ? <><td><Count n={row.patients} minCell={r.min_cell} /></td><td>{row.complete ? "yes" : "partial year"}</td></>
              : <><td>no patients</td><td>unknown</td></>}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function BreakdownTab({r, counted, d, onOp}: {r: CountResult; counted: Definition; d: Definition; onOp: (op: Operation) => void}) {
  const chosen = d.breakdown;
  const toggle = (dim: BreakdownDim) =>
    onOp({op: "set_breakdown", breakdown: chosen.includes(dim) ? chosen.filter((x) => x !== dim) : [...chosen, dim]});
  return (
    <div>
      <fieldset className="checks">
        <legend>Break down by (up to 4)</legend>
        {BREAKDOWN_DIMS.map(({value, label}) => (
          <label key={value}>
            <input type="checkbox" checked={chosen.includes(value)} disabled={!chosen.includes(value) && chosen.length >= 4}
              onChange={() => toggle(value)} /> {label}
          </label>
        ))}
      </fieldset>
      {counted.breakdown.map((dim) => (
        <GridTable key={dim} label={BREAKDOWN_DIMS.find((b) => b.value === dim)?.label ?? dim}>
          <thead><tr><th scope="col">Value</th><th scope="col">Patients</th><th scope="col">Of patients in population</th><th scope="col">Share</th></tr></thead>
          <tbody>{(r.breakdowns[dim] ?? []).map((c) => (
            <tr key={c.value}>
              <th scope="row">{c.value}</th>
              <td className={c.patients == null ? "hatched" : ""}><Count n={c.patients} minCell={r.min_cell} /></td>
              <td className={c.denominator == null ? "hatched" : ""}><Count n={c.denominator} minCell={r.min_cell} /></td>
              <td>{pct(c.patients, c.denominator) ?? "–"}</td>
            </tr>
          ))}</tbody>
        </GridTable>
      ))}
    </div>
  );
}

// Every count table goes through here so a wide one scrolls inside the answer column, not the page.
export function GridTable({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className="grid"><caption>{label}</caption>{children}</table>
    </div>
  );
}

function PivotTab({d, counted, pivot, minCell, onOp}: {d: Definition; counted: Definition; pivot: PivotResult | null; minCell: number; onOp: (op: Operation) => void}) {
  const axes = pivotAxes(d);
  const label = (v: string) => pivotAxes(counted).find((a) => a.value === v)?.label ?? v;
  const [rows, setRows] = useState(d.pivot?.rows ?? "");
  const [cols, setCols] = useState(d.pivot?.cols ?? "");
  const choose = (nextRows: string, nextCols: string) => {
    setRows(nextRows);
    setCols(nextCols);
    if (nextRows && nextCols && nextRows !== nextCols) onOp({op: "set_pivot", pivot: {rows: nextRows, cols: nextCols}});
    else if (d.pivot && (!nextRows || !nextCols)) onOp({op: "set_pivot", pivot: null});
  };
  const select = (name: string, value: string, set: (v: string) => void) => (
    <label>{name}{" "}
      <select value={value} onChange={(e) => set(e.target.value)}>
        <option value="">none</option>
        {axes.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
      </select>
    </label>
  );
  const cell = new Map(pivot?.cells.map((c) => [`${c.row}\u0000${c.col}`, c.patients]));
  return (
    <div>
      <div className="pivot-controls">
        {select("Rows", rows, (v) => choose(v, cols))}
        {select("Columns", cols, (v) => choose(rows, v))}
      </div>
      {!d.pivot || !pivot
        ? <p>Choose rows and columns.</p>
        : (
          <>
          <GridTable label={`${label(pivot.rows)} × ${label(pivot.cols)}`}>
            <thead><tr>
              <th scope="col">{label(pivot.rows)}</th>
              {pivot.col_totals.map((c) => <th key={c.value} scope="col">{c.value}</th>)}
              <th scope="col">Total</th>
            </tr></thead>
            <tbody>
              {pivot.row_totals.map((r) => (
                <tr key={r.value}>
                  <th scope="row">{r.value}</th>
                  {pivot.col_totals.map((c) => {
                    const k = `${r.value}\u0000${c.value}`;
                    return cell.has(k)
                      ? <td key={c.value} className={cell.get(k) == null ? "hatched" : ""}><Count n={cell.get(k)} minCell={minCell} /></td>
                      : <td key={c.value}>0</td>;
                  })}
                  <td className={r.patients == null ? "hatched" : ""}><Count n={r.patients} minCell={minCell} /></td>
                </tr>
              ))}
              <tr>
                <th scope="row">Total</th>
                {pivot.col_totals.map((c) => <td key={c.value} className={c.patients == null ? "hatched" : ""}><Count n={c.patients} minCell={minCell} /></td>)}
                <td className={pivot.patients == null ? "hatched" : ""}><Count n={pivot.patients} minCell={minCell} /></td>
              </tr>
            </tbody>
          </GridTable>
          <p className="legend">0: no patients have that combination. {`<${minCell}`}: {SUPPRESSED.toLowerCase()}.</p>
          </>
        )}
    </div>
  );
}

/** The last good answer and the definition it was counted for (it can trail the one being edited). */
export interface Counted { d: Definition; r: CountResult; p: PivotResult | null }

export interface AnswerProps {
  definition: Definition;           // current version: breakdown checkboxes and pivot selects edit it
  answer: Counted | null;
  options: Options | null;
  tab: Tab;
  onTab: (t: Tab) => void;
  onOp: (op: Operation) => void;
  onRetry?: () => void;
  busy?: boolean;
  error?: string | null;            // count/pivot failure: shown with a Retry button
  editError?: string | null;        // an edit made from this column failed
}

export function Answer({definition, answer, options, tab, onTab, onOp, onRetry, busy = false, error = null, editError = null}: AnswerProps) {
  const onKey = (e: KeyboardEvent) => {
    const i = TABS.indexOf(tab);
    const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length : -1;
    if (next < 0) return;
    e.preventDefault();
    onTab(TABS[next]);
    document.getElementById(`tab-${next}`)?.focus();
  };
  const stale = !!answer && answer.d !== definition;
  return (
    <main aria-labelledby="answer-h" aria-busy={busy}>
      <h2 id="answer-h" tabIndex={-1}>{definition.name.trim() || "Your cohort"}</h2>
      {editError && <p role="alert" className="error">{editError}</p>}
      {error && <p role="alert" className="error">{error}{onRetry && <> <button type="button" onClick={onRetry}>Retry</button></>}</p>}
      {!answer ? <p>{busy ? "Counting…" : "No result yet."}</p> : (() => {
        const {d: counted, r, p: pivot} = answer;
        return (
          <div className={busy ? "answer-body dim" : "answer-body"}>
            <p aria-live="polite" className="sr-only">
              {r.patients == null ? "patient count not shown" : `${fmtCount(r.patients)} patients`}
            </p>
            <Cards r={r} d={counted} options={options} />
            <DataFootnote onTab={onTab} />
            <Loosen r={r} d={counted} stale={stale} onOp={onOp} />
            {!isEmptyDefinition(counted) && <Funnel r={r} d={counted} />}
            <div role="tablist" aria-label="Views" className="tabs" onKeyDown={onKey}>
              {TABS.map((t, i) => (
                <button key={t} type="button" role="tab" id={`tab-${i}`} aria-selected={t === tab} aria-controls="tabpanel"
                  tabIndex={t === tab ? 0 : -1} onClick={() => onTab(t)}>{t}</button>
              ))}
            </div>
            <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${TABS.indexOf(tab)}`}>
              <h3 className="sr-only">{tab}</h3>
              {tab === "Accrual" && <AccrualTab r={r} />}
              {tab === "Breakdown" && <BreakdownTab r={r} counted={counted} d={definition} onOp={onOp} />}
              {tab === "Pivot" && <PivotTab key={JSON.stringify(definition.pivot)} d={definition} counted={counted} pivot={pivot} minCell={r.min_cell} onOp={onOp} />}
              {tab === "Data notes" && <>
                <ul>{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
                <p className="hint">Cohort ID (for support): <code>{r.cohort_id}</code></p>
              </>}
            </div>
          </div>
        );
      })()}
    </main>
  );
}
