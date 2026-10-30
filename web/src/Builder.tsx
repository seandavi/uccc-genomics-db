import { useEffect, useId, useState } from "react";
import {
  EVIDENCE, POP_DIMS, REPORT_DATA, addToPopulation, biomarkerEntries, capitalise, cardLabel, comboKey, criterionLabel, dataEntries,
  fieldLabel, forScope, kindLabel, modesFor, newCriterion, optionText, type ComboState, type PopDim,
} from "./cohort.ts";
import { describeError, type Transport } from "./transport.ts";
import type { Criterion, Definition, Leaf, Mode, Operation, Option, Options, Population, SeqMember } from "./types.ts";

const DIM_LABELS: Record<PopDim, string> = {
  oncotree: "Tumor type", organ: "Organ", sex: "Sex", age_band: "Age", vendor: "Vendor", assay_class: "Assay",
};

// --- typeahead (WAI-ARIA combobox) -----------------------------------------------------------------

interface TypeaheadProps {
  label: string;
  placeholder: string;
  search: (q: string) => Promise<Option[]>;
  onPick: (e: Option) => void;
  minChars?: number;
}

export function Typeahead({label, placeholder, search, onPick, minChars = 1}: TypeaheadProps) {
  const id = useId();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Option[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [st, setSt] = useState<ComboState>({open: false, active: 0});

  useEffect(() => {
    if (!st.open || q.length < minChars) { setItems(null); setError(null); return; }
    let stale = false;
    const t = setTimeout(() => {
      search(q).then((r) => { if (!stale) { setItems(r); setError(null); setSt((s) => ({...s, active: 0})); } })
        .catch((e) => { if (!stale) { setItems(null); setError(describeError(e)); } });
    }, 150);
    return () => { stale = true; clearTimeout(t); };
  }, [q, st.open]);   // search is a fresh closure each render; q and open are what change the request

  const pick = (e: Option) => { onPick(e); setQ(""); setItems(null); setSt({open: false, active: 0}); };
  const shown = st.open ? items : null;

  return (
    <div className="typeahead">
      <label htmlFor={`${id}-in`}>{label}</label>
      <input id={`${id}-in`} role="combobox" aria-expanded={!!shown} aria-controls={`${id}-list`}
        aria-activedescendant={shown?.length ? `${id}-o${st.active}` : undefined} aria-autocomplete="list"
        autoComplete="off" placeholder={placeholder} value={q}
        onChange={(e) => { setQ(e.target.value); setSt((s) => ({...s, open: true})); }}
        onFocus={() => setSt((s) => ({...s, open: true}))}
        onBlur={() => setSt((s) => ({...s, open: false}))}
        onKeyDown={(e) => {
          const r = comboKey(st, e.key, items?.length ?? 0);
          if (["ArrowDown", "ArrowUp", "Home", "End", "Escape"].includes(e.key) || (e.key === "Enter" && r.pick)) e.preventDefault();
          setSt({open: r.open, active: r.active});
          if (r.pick && items?.[st.active]) pick(items[st.active]);
        }} />
      <ul role="listbox" id={`${id}-list`} hidden={!shown}>
        {shown?.map((o, i) => (
          <li key={`${o.field}|${o.parent}|${o.value}`} role="option" id={`${id}-o${i}`} aria-selected={i === st.active}
            title={fieldLabel(o)} onMouseDown={(e) => { e.preventDefault(); pick(o); }}>
            <span className="kind">{kindLabel(o)}</span><span aria-hidden="true"> · </span><span>{optionText(o)}</span>
          </li>
        ))}
      </ul>
      {st.open && error && <p role="alert" className="error">Could not search: {error}</p>}
      {shown && shown.length === 0 && q.length >= minChars &&
        <p role="status" className="hint">No matching values (values held by fewer than 5 patients are not offered).</p>}
    </div>
  );
}

// --- small controls --------------------------------------------------------------------------------

/** The values the vocabulary holds for one field (and parent), most common first; [] until loaded. */
function useValues(transport: Transport, field: string, parent?: string): {values: string[]; error: string | null} {
  const [values, setValues] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stale = false;
    setError(null);
    transport.options({field, parent, limit: 50})
      .then((o) => { if (!stale) setValues(o.entries.map((e) => e.value)); })
      .catch((e) => { if (!stale) setError(describeError(e)); });
    return () => { stale = true; };
  }, [transport, field, parent]);
  return {values, error};
}

export function Checks({legend, values, selected, onChange, labels, error}: {
  legend: string; values: string[]; selected: string[]; onChange: (v: string[]) => void; labels?: Record<string, string>;
  error?: string | null;
}) {
  const all = [...values, ...selected.filter((s) => !values.includes(s))];
  return (
    <fieldset className="checks">
      <legend>{legend}</legend>
      {error && <p role="alert" className="error">Could not load values: {error}</p>}
      {all.map((v) => (
        <label key={v}>
          <input type="checkbox" checked={selected.includes(v)}
            onChange={(e) => onChange(e.target.checked ? [...selected, v] : selected.filter((x) => x !== v))} /> {labels?.[v] ?? v}
        </label>
      ))}
    </fieldset>
  );
}

function CutSelect({label, cuts, value, onChange}: {label: string; cuts: number[]; value: number | null | undefined; onChange: (v: number | null) => void}) {
  return (
    <label>{label}{" "}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}>
        <option value="">any</option>
        {cuts.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );
}

// --- population ------------------------------------------------------------------------------------

function PopulationChips({p, onOp}: {p: Population; onOp: (op: Operation) => void}) {
  const set = (population: Population) => onOp({op: "set_population", population});
  return (
    <ul className="chips" aria-label="Population filters">
      {POP_DIMS.flatMap((d) => p[d].map((v) => (
        <li key={`${d}:${v}`} className="chip">
          <span>{v}</span>
          <button type="button" aria-label={`Remove ${v}`} onClick={() => set({...p, [d]: p[d].filter((x) => x !== v)})}>✕</button>
        </li>
      )))}
      {p.years && (
        <li className="chip">
          <span>{p.years[0]}–{p.years[1]}</span>
          <button type="button" aria-label="Remove years" onClick={() => set({...p, years: null})}>✕</button>
        </li>
      )}
    </ul>
  );
}

function PopulationAdders({transport, p, options, onOp}: {transport: Transport; p: Population; options: Options | null; onOp: (op: Operation) => void}) {
  const [open, setOpen] = useState<PopDim | null>(null);
  const yid = useId();
  const set = (population: Population) => onOp({op: "set_population", population});
  const years = options?.years ? Array.from({length: options.years[1] - options.years[0] + 1}, (_, i) => options.years![0] + i) : [];
  const setYears = (from: string, to: string) => {
    if (from === "" || to === "") return set({...p, years: null});
    set({...p, years: [Number(from), Math.max(Number(from), Number(to))]});
  };
  return (
    <div>
      <div className="adders">
        {POP_DIMS.map((d) => (
          <button key={d} type="button" className="adder" aria-expanded={open === d} onClick={() => setOpen(open === d ? null : d)}>+ {DIM_LABELS[d]}</button>
        ))}
      </div>
      {open && (open === "oncotree" || open === "organ"
        ? <Typeahead label={`Add ${DIM_LABELS[open].toLowerCase()}`} minChars={0}
            placeholder={open === "oncotree" ? "Search tumor types… e.g. NSCLC" : "Search organ systems… e.g. Lung"}
            search={(q) => transport.options({q, field: `population.${open}`, limit: 20}).then((o) => o.entries)}
            onPick={(e) => { const next = addToPopulation(p, e); if (next && next !== p) set(next); setOpen(null); }} />
        : <PopulationChecks transport={transport} dim={open} p={p} set={set} />)}
      <div className="years" role="group" aria-labelledby={`${yid}-years`}>
        <span id={`${yid}-years`}>Years</span>
        <select aria-label="From year" value={p.years?.[0] ?? ""} onChange={(e) => setYears(e.target.value, String(p.years?.[1] ?? years.at(-1) ?? ""))}>
          <option value="">Any</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <span aria-hidden="true">–</span>
        <select aria-label="To year" value={p.years?.[1] ?? ""} onChange={(e) => setYears(String(p.years?.[0] ?? years[0] ?? ""), e.target.value)}>
          <option value="">Any</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
    </div>
  );
}

function PopulationChecks({transport, dim, p, set}: {transport: Transport; dim: PopDim; p: Population; set: (p: Population) => void}) {
  const {values, error} = useValues(transport, `population.${dim}`);
  return <Checks legend={`Limit to ${DIM_LABELS[dim].toLowerCase()}`} values={values} error={error} selected={p[dim]} onChange={(v) => set({...p, [dim]: v})} />;
}

// --- criterion editors -----------------------------------------------------------------------------

const ALT_CLASSES = ["mutation", "amplification", "loss", "fusion"] as const;
const TIERS = ["pathogenic", "likely_pathogenic", "vus", "unclassified"] as const;
const TIER_LABELS = {pathogenic: "pathogenic", likely_pathogenic: "likely pathogenic", vus: "VUS", unclassified: "unclassified"};

function Editor({c, transport, options, onSave, onCancel}: {
  c: Criterion; transport: Transport; options: Options | null; onSave: (c: Criterion) => void; onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Criterion>(c);
  const cuts = (k: string) => options?.cut_points[k] ?? [];
  return (
    <form className="editor" onSubmit={(e) => { e.preventDefault(); onSave(draft); }}>
      <EditorBody d={draft} set={setDraft} transport={transport} cuts={cuts} />
      <div className="row">
        <button type="submit">Save</button> <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

const VENDORS = [["", "any vendor"], ["caris", "Caris"], ["fmi", "FMI"]] as const;

function VendorSelect({d, set}: {d: Exclude<Criterion, {kind: "any_of" | "sequence"}>; set: (c: Criterion) => void}) {
  if (d.kind === "data" && !REPORT_DATA.includes(d.has)) return null;   // both_vendors and serial span vendors
  return (
    <label>Vendor{" "}
      <select aria-label="Vendor" value={d.vendor ?? ""} onChange={(e) => set({...d, vendor: (e.target.value || null) as typeof d.vendor})}>
        {VENDORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
  );
}

function EditorBody({d, set, transport, cuts}: {d: Criterion; set: (c: Criterion) => void; transport: Transport; cuts: (k: string) => number[]}) {
  if (d.kind === "any_of" || d.kind === "sequence") return null;
  return (
    <>
      <KindEditor d={d} set={set} transport={transport} cuts={cuts} />
      <VendorSelect d={d} set={set} />
    </>
  );
}

function KindEditor({d, set, transport, cuts}: {d: Exclude<Criterion, {kind: "any_of" | "sequence"}>; set: (c: Criterion) => void; transport: Transport; cuts: (k: string) => number[]}) {
  switch (d.kind) {
    case "alteration": return <AlterationEditor d={d} set={set} transport={transport} />;
    case "biomarker": return <BiomarkerEditor d={d} set={set} transport={transport} cuts={cuts} />;
    case "ihc": return <IhcEditor d={d} set={set} transport={transport} cuts={cuts} />;
    case "expression":
      return <CutSelect label="At least percentile" cuts={cuts("expression.percentile")} value={d.percentile_at_least}
        onChange={(v) => set({...d, percentile_at_least: v})} />;
    case "specimen": return <SpecimenEditor d={d} set={set} transport={transport} cuts={cuts} />;
    case "actionability": return <ActionabilityEditor d={d} set={set} transport={transport} />;
    case "data": return null;
  }
}

type Of<K extends Criterion["kind"]> = Extract<Criterion, {kind: K}>;
interface EditorProps<K extends Criterion["kind"]> { d: Of<K>; set: (c: Criterion) => void; transport: Transport }

export function AlterationEditor({d, set, transport}: EditorProps<"alteration">) {
  const negative = d.mode === "tested_negative";   // per gene: Save takes no protein change and no class but mutation
  const oneGene = d.gene.length === 1;
  const mutationOnly = d.class.length === 0 || (d.class.length === 1 && d.class[0] === "mutation");
  const aa = useValues(transport, "alteration.aa", oneGene && mutationOnly ? d.gene[0] : undefined);
  return (
    <>
      <Checks legend="Alteration class (none = any)" values={negative ? ["mutation"] : [...ALT_CLASSES]} selected={d.class}
        onChange={(v) => {
          const cls = v as typeof d.class;
          const stillMutation = cls.length === 0 || (cls.length === 1 && cls[0] === "mutation");
          set({...d, class: cls, aa: stillMutation ? d.aa : []});
        }} />
      {negative && <p className="hint">Tested negative is per gene: it takes no protein change and no copy-number or fusion class.</p>}
      {!negative && oneGene && mutationOnly && (aa.values.length > 0 || aa.error) &&
        <Checks legend={`${d.gene[0]} protein change (none = any)`} values={aa.values} error={aa.error} selected={d.aa} onChange={(v) => set({...d, aa: v})} />}
      <Checks legend="Classification" values={[...TIERS]} selected={d.tier} labels={TIER_LABELS}
        onChange={(v) => set({...d, tier: v as typeof d.tier})} />
    </>
  );
}

function BiomarkerEditor({d, set, transport, cuts}: EditorProps<"biomarker"> & {cuts: (k: string) => number[]}) {
  const {values: calls, error: callsError} = useValues(transport, "biomarker.call", d.name);
  return (
    <>
      {d.name === "TMB" &&
        <CutSelect label="At least (mut/Mb)" cuts={cuts("biomarker.TMB")} value={d.at_least} onChange={(v) => set({...d, at_least: v, call: v == null ? d.call : []})} />}
      <Checks legend={`${d.name} call (none = tested)`} values={calls} error={callsError} selected={d.call}
        onChange={(v) => set({...d, call: v, at_least: v.length ? null : d.at_least})} />
    </>
  );
}

function IhcEditor({d, set, transport, cuts}: EditorProps<"ihc"> & {cuts: (k: string) => number[]}) {
  const clones = useValues(transport, "ihc.clone", d.marker);
  const calls = useValues(transport, "ihc.call", d.marker);
  return (
    <>
      <label>Clone{" "}
        <select value={d.clone ?? ""} onChange={(e) => set({...d, clone: e.target.value || null})}>
          <option value="">any clone</option>
          {[...new Set([...clones.values, ...(d.clone ? [d.clone] : [])])].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      {clones.error && <p role="alert" className="error">Could not load values: {clones.error}</p>}
      <Checks legend={`${d.marker} call`} values={calls.values} error={calls.error} selected={d.call}
        onChange={(v) => set({...d, call: v, measure: v.length ? null : d.measure, at_least: v.length ? null : d.at_least})} />
      <label>Measure{" "}
        <select value={d.measure ?? ""} onChange={(e) => set({...d, measure: (e.target.value || null) as typeof d.measure, at_least: null, call: e.target.value ? [] : d.call})}>
          <option value="">none</option>
          <option value="TPS">TPS</option>
          <option value="CPS">CPS</option>
        </select>
      </label>
      {d.measure && <CutSelect label="At least" cuts={cuts(`ihc.${d.measure}`)} value={d.at_least} onChange={(v) => set({...d, at_least: v})} />}
    </>
  );
}

function SpecimenEditor({d, set, transport, cuts}: EditorProps<"specimen"> & {cuts: (k: string) => number[]}) {
  const types = useValues(transport, "specimen.site_type");
  const sites = useValues(transport, "specimen.site");
  return (
    <>
      <Checks legend="Site type" values={types.values} error={types.error} selected={d.site_type} onChange={(v) => set({...d, site_type: v})} />
      <Checks legend="Site" values={sites.values} error={sites.error} selected={d.site} onChange={(v) => set({...d, site: v})} />
      <CutSelect label="Tumor purity at least (%)" cuts={cuts("specimen.purity")} value={d.purity_at_least} onChange={(v) => set({...d, purity_at_least: v})} />
    </>
  );
}

function ActionabilityEditor({d, set, transport}: EditorProps<"actionability">) {
  const present = useValues(transport, "actionability.evidence");
  return (
    <Checks legend="Evidence" values={present.values} error={present.error} selected={d.evidence} labels={EVIDENCE}
      onChange={(v) => set({...d, evidence: v as typeof d.evidence})} />
  );
}

// --- criterion cards -------------------------------------------------------------------------------

const MAX_OR = 8;
const MAX_SEQ = 4;
const MODE_LABELS: Record<Mode, string> = {include: "Include", exclude: "Exclude", tested_negative: "Tested negative"};
const leafOf = (c: Criterion | SeqMember): Leaf => { const {id: _id, ...rest} = c as Leaf; return {...rest, id: null, mode: "include"} as Leaf; };
/** A criterion that spans several reports, so it cannot be matched on one report. */
const spansReports = (c: Criterion) => c.kind === "sequence" || (c.kind === "data" && !REPORT_DATA.includes(c.has));
const isReportData = (c: Criterion | SeqMember) => c.kind === "data" && REPORT_DATA.includes(c.has);
/** An entry that can be a `sequence` member: a finding, or data held by one report. */
const seqEntry = (e: Option) => !e.field.startsWith("population.") && (e.field !== "data.has" || REPORT_DATA.includes(e.value));
const seqMember = (e: Option): SeqMember | null => {
  const nc = newCriterion(e);
  return nc && nc.kind !== "any_of" && nc.kind !== "sequence" ? (leafOf(nc) as SeqMember) : null;
};

/** An any_of without member i; the last member left stands in for it, keeping the any_of's mode (its members are always include). */
export function withoutMember(c: Extract<Criterion, {kind: "any_of"}>, i: number): Criterion {
  const rest = c.of.filter((_, j) => j !== i);
  return rest.length === 1 ? {...rest[0], id: c.id, mode: c.mode} : {...c, of: rest};
}

function CriterionCard({c, scope, transport, options, onOp}: {
  c: Criterion; scope: Definition["scope"]; transport: Transport; options: Options | null; onOp: (op: Operation) => void;
}) {
  const [mode, setMode] = useState<"edit" | "or" | "then" | null>(null);
  const id = c.id ?? "";
  const update = (criterion: Criterion) => { setMode(null); onOp({op: "update_criterion", id, criterion}); };
  const orIn = (e: Option) => {
    const nc = newCriterion(e);
    if (!nc || nc.kind === "any_of" || nc.kind === "sequence" || nc.kind === "data") return;
    setMode(null);
    update(c.kind === "any_of" ? {...c, of: [...c.of, leafOf(nc)]} : {kind: "any_of", id, mode: c.mode, of: [leafOf(c), leafOf(nc)]});
  };
  const thenIn = (e: Option) => {
    const member = seqMember(e);
    if (member) update({kind: "sequence", id, mode: "include", first: [leafOf(c) as SeqMember], then: [member]});
  };
  const dropMember = (i: number) => { if (c.kind === "any_of") update(withoutMember(c, i)); };
  const editable = c.kind !== "any_of" && c.kind !== "sequence" && !(c.kind === "data" && !isReportData(c));
  const canOr = c.kind !== "sequence" && c.kind !== "data" && c.mode !== "tested_negative";
  const canThen = c.mode === "include" && c.kind !== "any_of" && c.kind !== "sequence" && (c.kind !== "data" || isReportData(c)) && scope !== "report";
  const label = cardLabel(c);
  const actions = [
    editable && <button key="edit" type="button" className="btn-tertiary" aria-expanded={mode === "edit"}
      title="Change this criterion's details" onClick={() => setMode(mode === "edit" ? null : "edit")}>Edit</button>,
    canOr && <button key="or" type="button" className="btn-tertiary" aria-expanded={mode === "or"}
      disabled={c.kind === "any_of" && c.of.length >= MAX_OR}
      title="Match this or another finding (either one counts)" onClick={() => setMode(mode === "or" ? null : "or")}>+ Or another</button>,
    canThen && <button key="then" type="button" className="btn-tertiary" aria-expanded={mode === "then"}
      title="Also require a finding on a report later than this one" onClick={() => setMode(mode === "then" ? null : "then")}>+ Later report</button>,
  ].filter(Boolean).flatMap((a, i) => (i ? [<span key={`sep${i}`} className="sep" aria-hidden="true">·</span>, a] : [a]));
  return (
    <article className={`criterion mode-${c.mode}`} aria-label={capitalise(criterionLabel(c))}>
      <header>
        <select className="mode" aria-label={`Mode of ${id}`} value={c.mode}
          onChange={(e) => onOp({op: "set_mode", id, mode: e.target.value as Mode})}>
          {modesFor(c).map((m) => <option key={m} value={m}>{MODE_LABELS[m]}</option>)}
        </select>
        <span className="sep" aria-hidden="true">·</span>
        <span className="clabel">{label}</span>
        <button type="button" className="btn-icon remove" aria-label={`Remove ${label}`} title="Remove this criterion"
          onClick={() => onOp({op: "remove_criterion", id})}>✕</button>
      </header>
      {c.kind === "any_of" && (
        <ul className="members">{c.of.map((m, i) => (
          <li key={i}>{capitalise(criterionLabel(m))} <button type="button" className="btn-icon" aria-label={`Remove ${criterionLabel(m)} from ${id}`} onClick={() => dropMember(i)}>✕</button></li>
        ))}</ul>
      )}
      {c.kind === "sequence" && <SequenceMembers c={c} transport={transport} onChange={update} />}
      {actions.length > 0 && <div className="row card-actions">{actions}</div>}
      {mode === "edit" && <Editor c={c} transport={transport} options={options} onSave={update} onCancel={() => setMode(null)} />}
      {mode === "or" && <Typeahead label="Or any of" placeholder="Search another finding… e.g. NRAS" search={(q) => searchAll(transport, q).then((r) => r.filter((e) => !e.field.startsWith("population.") && e.field !== "data.has"))} onPick={orIn} />}
      {mode === "then" && <Typeahead label="Then, on a later report" placeholder="Search a finding on the later report… e.g. liquid biopsy" search={(q) => searchAll(transport, q).then((r) => r.filter(seqEntry))} onPick={thenIn} />}
    </article>
  );
}

/** A sequence criterion: the members of the first report and of a strictly later one (each side ANDed on one report). */
function SequenceMembers({c, transport, onChange}: {c: Extract<Criterion, {kind: "sequence"}>; transport: Transport; onChange: (c: Criterion) => void}) {
  const sides = [["first", "First report"], ["then", "Later report"]] as const;
  return (
    <div className="sequence">
      {sides.map(([side, title]) => {
        const members = c[side];
        const set = (next: SeqMember[]) => onChange({...c, [side]: next});
        return (
          <div key={side}>
            <h4>{title}</h4>
            <ul className="members">{members.map((m, i) => (
              <li key={i}>{capitalise(criterionLabel(m))}{" "}
                <button type="button" className="btn-icon" aria-label={`Remove ${criterionLabel(m)} from ${title.toLowerCase()} of ${c.id}`}
                  disabled={members.length === 1} onClick={() => set(members.filter((_, j) => j !== i))}>✕</button>
              </li>
            ))}</ul>
            {members.length < MAX_SEQ && (
              <Typeahead label={`And on the same report… (${title.toLowerCase()})`} placeholder="Search a finding… e.g. KRAS"
                search={(q) => searchAll(transport, q).then((r) => r.filter(seqEntry))}
                onPick={(e) => { const m = seqMember(e); if (m) set([...members, m]); }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

const searchAll = (transport: Transport, q: string): Promise<Option[]> =>
  transport.options({q, limit: 20}).then((o) => [...biomarkerEntries(q), ...dataEntries(q), ...o.entries]);

// --- builder ---------------------------------------------------------------------------------------

export function Builder({definition: d, transport, options, onOp}: {
  definition: Definition; transport: Transport; options: Options | null; onOp: (op: Operation) => void;
}) {
  const add = (e: Option) => {
    const pop = addToPopulation(d.population, e);
    if (pop) { if (pop !== d.population) onOp({op: "set_population", population: pop}); return; }
    const criterion = newCriterion(e);
    if (criterion) onOp({op: "add_criterion", criterion});
  };
  const sid = useId();
  // Scope changes the count with two criteria or any negated one (definition._scope_swap)
  const showSameReport = d.scope === "report" || d.criteria.length >= 2 || d.criteria.some((c) => c.mode !== "include");
  const sameReportBlocked = d.scope !== "report" && d.criteria.some(spansReports);
  return (
    <div className="builder">
      <section aria-labelledby="pop-h">
        <h2 id="pop-h">Population</h2>
        <PopulationChips p={d.population} onOp={onOp} />
        <PopulationAdders transport={transport} p={d.population} options={options} onOp={onOp} />
      </section>
      <section aria-labelledby="crit-h">
        <h2 id="crit-h">Criteria <small>(all must match)</small></h2>
        {d.criteria.map((c) => <CriterionCard key={c.id} c={c} scope={d.scope} transport={transport} options={options} onOp={onOp} />)}
        <Typeahead label="Add criterion" placeholder="Search genes, biomarkers, IHC, specimens… e.g. KRAS, TMB, PD-L1"
          search={(q) => searchAll(transport, q).then((r) => forScope(r, d.scope))} onPick={add} />
        {showSameReport && (
          <div className="same-report">
            <label>
              <input type="checkbox" checked={d.scope === "report"} disabled={sameReportBlocked}
                aria-describedby={sameReportBlocked ? `${sid}-why` : undefined}
                onChange={(e) => onOp({op: "set_scope", scope: e.target.checked ? "report" : "patient"})} /> Match all criteria on the same report
            </label>
            {sameReportBlocked && <p id={`${sid}-why`} className="hint">A sequence, testing by both vendors or serial reports spans several reports, so it cannot be matched on one report.</p>}
          </div>
        )}
      </section>
    </div>
  );
}
