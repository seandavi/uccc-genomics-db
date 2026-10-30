import { Count } from "./Answer.tsx";
import { EXAMPLES, exampleLabel } from "./cohort.ts";
import type { CountResult, Definition } from "./types.ts";

export interface StartProps {
  total: CountResult | null;   // the count of the current (empty) definition; null while it is counted
  busy: boolean;
  minCell: number;
  onExample: (d: Definition) => void;
}

function Sparkline({r}: {r: CountResult}) {
  if (r.by_year.length === 0) return null;
  const years = r.by_year.map((y) => y.year);
  const max = Math.max(1, ...r.by_year.map((y) => y.patients ?? 0));
  // same rule as barPct (issue 100: the one that encodes this rule)
  const height = (n: number | null) => Math.min(100, Math.max(2, ((n ?? r.min_cell) / max) * 100));
  return (
    <figure className="spark">
      <div className="spark-bars" aria-hidden="true">
        {r.by_year.map((y) => (
          <span key={y.year} className={["vbar", y.patients == null && "hatched", !y.complete && "partial"].filter(Boolean).join(" ")}
            style={{height: `${height(y.patients)}%`}} />
        ))}
      </div>
      <figcaption>Patients by year of first qualifying report, {Math.min(...years)}–{Math.max(...years)}</figcaption>
    </figure>
  );
}

/** The answer column for an empty definition: how it works, example cohorts (no counts), the total, a sparkline. */
export function Start({total, busy, minCell, onExample}: StartProps) {
  return (
    <section className="start" aria-labelledby="start-h">
      <p className="intro">How many of our sequenced patients fit your study? Pick who on the left, add criteria,
        then copy a feasibility statement. Counts under {minCell} show as {`<${minCell}`}.</p>
      <h3 id="start-h">Start from an example</h3>
      <ul className="examples">
        {EXAMPLES.map((d) => (
          <li key={d.name} className="card example">
            <h4>{d.name}</h4>
            <p className="sub">{exampleLabel(d)}</p>
            <button type="button" className="btn-secondary" aria-label={`Use example: ${d.name}`}
              onClick={() => onExample(d)}>Use →</button>
          </li>
        ))}
      </ul>
      {total
        ? <p className="total">Discover covers <Count n={total.patients} minCell={total.min_cell} /> patients sequenced by Caris and FMI.</p>
        : busy && <p className="total">Counting…</p>}
      {total && <Sparkline r={total} />}
    </section>
  );
}
