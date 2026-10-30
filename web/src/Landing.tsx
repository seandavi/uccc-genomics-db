import { Count } from "./Answer.tsx";
import { Sparkline } from "./Start.tsx";
import type { PublicSummary } from "./types.ts";

const VENDORS: Record<string, string> = {caris: "Caris Life Sciences", fmi: "Foundation Medicine"};

/** "/discover" + hash for a share link (#d=…), else null: old links to /#d=… open in Discover. */
export function discoverRedirect(hash: string): string | null {
  return hash.startsWith("#d=") ? "/discover" + hash : null;
}

export function Landing({summary, error}: {summary: PublicSummary | null; error: boolean}) {
  const s = summary;
  const few = s ? `Fewer than ${s.min_cell}` : "";   // the landing page's <5 title: no subtraction on this fixed endpoint
  return (
    <main className="landing">
      <h1>UCCC tumor sequencing</h1>
      <p className="lede">De-identified tumor sequencing reports from Caris Life Sciences and Foundation Medicine
        for University of Colorado Cancer Center patients, for checking whether a study is feasible.</p>
      <p>Discover counts how many patients fit a study: choose tumor types, genes, biomarkers and other
        criteria, then copy a feasibility statement for grant text. It shows counts, never patient records.</p>
      <p>Discover is for University of Colorado researchers and staff. Sign in with your CU Anschutz
        Google account. Others can ask the UCCC genomics team for access.</p>
      <p><a className="btn-primary" href="/discover">Sign in to Discover</a></p>
      <section aria-labelledby="totals-h">
        <h2 id="totals-h">What's in it</h2>
        {s === null && <p role="status">{error ? "Totals are not available right now." : "Loading totals…"}</p>}
        {s && (
          <>
            <dl className="totals">
              <div><dt>Patients</dt><dd><Count n={s.patients} minCell={s.min_cell} title={`${few} patients`} /></dd></div>
              <div><dt>Reports</dt><dd><Count n={s.reports} minCell={s.min_cell} title={few} /></dd></div>
              <div><dt>Tumor types</dt><dd><Count n={s.tumor_types} minCell={s.min_cell} title={few} /></dd></div>
              <div className="text"><dt>Vendors</dt><dd>{s.vendors.map((v) => VENDORS[v] ?? v).join(", ")}</dd></div>
              {s.first_year != null && s.last_year != null && (
                <div><dt>First-sample years</dt><dd>{s.first_year === s.last_year ? s.first_year : `${s.first_year}–${s.last_year}`}</dd></div>
              )}
            </dl>
            <Sparkline years={s.by_year} minCell={s.min_cell} label="Patients by year of first sample" />
            <table className="sr-only">
              <caption>Patients by year of first sample</caption>
              <thead><tr><th>Year</th><th>Patients</th></tr></thead>
              <tbody>
                {s.by_year.map((y) => (
                  <tr key={y.year}>
                    <td>{y.year}{!y.complete && " (partial year)"}</td>
                    <td><Count n={y.patients} minCell={s.min_cell} title={`${few} patients`} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="hint">Counts are rounded to the nearest {s.round_to}; fewer than {s.min_cell} shows as
              &lt;{s.min_cell}. A lighter bar is a year not yet complete; a hatched bar is fewer
              than {s.min_cell}. A patient sequenced by both vendors counts once. Years are approximate: dates
              are shifted per patient for de-identification.</p>
          </>
        )}
      </section>
    </main>
  );
}
