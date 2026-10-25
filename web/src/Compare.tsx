import { useState, type ReactNode } from "react";
import { Count, GridTable, SUPPRESSED } from "./Answer.tsx";
import { accrualPerYear, criterionLabel, pct, populationLabel, type Version } from "./cohort.ts";
import { describeError, type Transport } from "./transport.ts";
import type { CountResult } from "./types.ts";

/** One definition's answer: a result, or why there is none. `window` is the year span its accrual is over. */
export interface CompareColumn {
  label: string;
  definition: string;   // what the version selects, since a name is shared by every version of a cohort
  result: CountResult | null;
  error: string | null;
  window?: readonly [number, number] | null;
}

export function CompareTable({columns, minCell}: {columns: CompareColumn[]; minCell: number}) {
  const years = [...new Set(columns.flatMap((c) => c.result?.by_year.map((y) => y.year) ?? []))].sort((a, b) => a - b);
  const cell = (c: CompareColumn, show: (r: CountResult) => ReactNode) =>
    c.result ? show(c.result) : <span className="error">{c.error ?? "no result"}</span>;
  const anySuppressed = columns.some((c) => c.result && [c.result.patients, c.result.denominator, ...c.result.by_year.map((y) => y.patients)].some((n) => n == null));
  const anyBlank = years.some((y) => columns.some((c) => c.result && !c.result.by_year.some((x) => x.year === y)));
  return (
    <>
    <GridTable label="Compare versions">
      <thead><tr>
        <th scope="col">Measure</th>
        {columns.map((c) => <th key={c.label} scope="col" title={c.result?.cohort_id}>{c.label}</th>)}
      </tr></thead>
      <tbody>
        <tr><th scope="row">Definition</th>{columns.map((c) => <td key={c.label}>{c.definition}</td>)}</tr>
        <tr><th scope="row">Patients</th>{columns.map((c) => <td key={c.label}>{cell(c, (r) => <Count n={r.patients} minCell={minCell} />)}</td>)}</tr>
        <tr><th scope="row">Population</th>{columns.map((c) => <td key={c.label}>{cell(c, (r) => <Count n={r.denominator} minCell={minCell} />)}</td>)}</tr>
        <tr><th scope="row">Share</th>{columns.map((c) => <td key={c.label}>{cell(c, (r) => pct(r.patients, r.denominator) ?? "–")}</td>)}</tr>
        <tr><th scope="row">Accrual a year</th>{columns.map((c) => (
          <td key={c.label}>{cell(c, (r) => { const a = accrualPerYear(r.patients, c.window ?? null); return a == null ? "–" : a.toFixed(1); })}</td>
        ))}</tr>
        {years.map((y) => (
          <tr key={y}><th scope="row">{y}</th>{columns.map((c) => {
            const row = c.result?.by_year.find((x) => x.year === y);
            return <td key={c.label}>{row ? <Count n={row.patients} minCell={minCell} /> : null}</td>;
          })}</tr>
        ))}
      </tbody>
    </GridTable>
    {anySuppressed && <p className="legend">{`<${minCell}`}: {SUPPRESSED.toLowerCase()}.</p>}
    {anyBlank && <p className="legend">Blank: no patients that year for that version.</p>}
    </>
  );
}

const MIN_PICKED = 2;
const MAX_PICKED = 4;

export function Compare({versions, transport, years, onClose}: {
  versions: Version[]; transport: Transport; years: readonly [number, number] | null; onClose: () => void;
}) {
  const [picked, setPicked] = useState<number[]>(() => versions.slice(-MIN_PICKED).map((v) => v.n));
  const [columns, setColumns] = useState<CompareColumn[] | null>(null);
  const [busy, setBusy] = useState(false);
  const toggle = (n: number) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));
  const run = async () => {
    const chosen = versions.filter((v) => picked.includes(v.n));
    setBusy(true);
    const settled = await Promise.allSettled(chosen.map((v) => transport.count(v.definition)));
    setColumns(chosen.map((v, i) => {
      const s = settled[i];
      return {
        label: versionLabel(v), definition: definitionLabel(v), window: v.definition.population.years ?? years,
        result: s.status === "fulfilled" ? s.value : null, error: s.status === "rejected" ? describeError(s.reason) : null,
      };
    }));
    setBusy(false);
  };
  const minCell = columns?.find((c) => c.result)?.result?.min_cell ?? 5;
  return (
    <section aria-label="Compare versions" className="panel">
      <fieldset className="checks">
        <legend>Versions to compare ({MIN_PICKED}–{MAX_PICKED})</legend>
        {versions.map((v) => (
          <label key={v.n}>
            <input type="checkbox" checked={picked.includes(v.n)} disabled={!picked.includes(v.n) && picked.length >= MAX_PICKED}
              onChange={() => toggle(v.n)} /> <span title={definitionLabel(v)}>{versionLabel(v)}</span>
          </label>
        ))}
      </fieldset>
      <div className="row">
        <button type="button" disabled={busy || picked.length < MIN_PICKED || picked.length > MAX_PICKED} onClick={run}>Count</button>{" "}
        <button type="button" onClick={onClose}>Close</button>
      </div>
      {columns && <CompareTable columns={columns} minCell={minCell} />}
    </section>
  );
}

const versionLabel = (v: Version) => `v${v.n} · ${v.definition.name || "Untitled"}`;

const definitionLabel = ({definition: d}: Version) =>
  [populationLabel(d.population), ...d.criteria.map(criterionLabel), ...(d.scope === "report" ? ["same report"] : [])].join("; ");
