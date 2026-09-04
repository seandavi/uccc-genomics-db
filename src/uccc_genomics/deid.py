"""Derive genomics.duckdb (de-identified) from genomics_phi.duckdb.

Generic over vendor schemas: every table that has the schema's report key
column is copied with
  - PHI columns (DROP set below) removed,
  - the report key replaced by a keyed hash, plus `research_id` (keyed hash of
    normalized MRN, shared across vendors) on `report` tables,
  - every DATE/TIMESTAMP column shifted by a stable per-patient offset (±182 d),
  - any column named *age* capped at 89.
Tables without the key column (e.g. load-error logs naming files) are not copied.
Key in $DATA/.deid_key (mode 600); same key => same IDs on rebuild.
"""
import os

from .config import DEID_DB, DEID_DB_KEY, KEY_FILE, PHI_DB, PHI_DB_KEY, connect, read_key, sql

KEY_COL = {"caris": "case_id", "fmi": "report_id"}
# patient identity per vendor: normalized MRN, else lower(last|first|dob) -- FMI leaves MRN empty on ~20% of reports
IDENTITY = {
    "caris": "coalesce(nullif(regexp_replace(mrn, '[^0-9]', '', 'g'), ''), "
             "lower(patient->>'lastName') || '|' || lower(patient->>'firstName') || '|' || dob::VARCHAR)",
    "fmi": "coalesce(nullif(regexp_replace(mrn, '[^0-9]', '', 'g'), ''), "
           "lower(last_name) || '|' || lower(first_name) || '|' || dob::VARCHAR)",
}
DROP = {
    "mrn", "dob", "patient", "physician", "pathologist", "organization", "pathologic_diagnosis",
    "first_name", "last_name", "full_name", "ordering_md", "ordering_md_id", "medical_facility_name",
    "medical_facility_id", "pathologist_comment", "copied_physician", "source_file", "sample_name",
    "specimen_ref", "npi", "extra", "test_request",
}
HASH = {"specimen_id", "accession_id"}  # vendor ids that embed the accession; hashed to stay joinable
ID_PATTERN = r"TN[0-9]{2}-[0-9]{5,}|ORD-[0-9]{6,}|TRF[0-9]{5,}|CRF[0-9]{5,}|QRF[0-9]{5,}|US[0-9]{6,}\.[0-9]{2}"


def run():
    if os.path.exists(DEID_DB):
        os.remove(DEID_DB)
    con = connect(deid=(DEID_DB, DEID_DB_KEY), phi=(PHI_DB, PHI_DB_KEY, "READ_ONLY"))
    con.execute("SET VARIABLE k = ?", [read_key(KEY_FILE)])

    present = [s for s in KEY_COL if con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_catalog='phi' AND table_schema=? AND table_name='report'", [s]).fetchone()[0]]
    union = " UNION ALL ".join(
        f"SELECT '{s}' AS vendor, {KEY_COL[s]}::VARCHAR AS id, {IDENTITY[s]} AS pid FROM phi.{s}.report"
        for s in present)
    con.execute(f"""
        CREATE TEMP TABLE xw AS
        SELECT vendor, id,
               substr(sha256(getvariable('k') || 'id' || vendor || id), 1, 16) AS hid,
               substr(sha256(getvariable('k') || 'pid' || coalesce(pid, 'nopid:' || vendor || id)), 1, 16) AS research_id,
               (hash(getvariable('k') || 'shift' || coalesce(pid, vendor || id)) % 365)::INT - 182 AS shift_days
        FROM ({union})""")

    for s in present:
        key = KEY_COL[s]
        con.execute(f"CREATE SCHEMA {s}")
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog='phi' AND table_schema=? AND table_type='BASE TABLE'", [s]).fetchall()]
        for t in tables:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_catalog='phi' AND table_schema=? AND table_name=? ORDER BY ordinal_position",
                [s, t]).fetchall()
            if key not in {c for c, _ in cols}:
                continue
            sel = []
            for c, typ in cols:
                if c == key:
                    sel.append(f'x.hid AS "{c}"')
                    if t == "report":
                        sel.append("x.research_id")
                elif c in DROP:
                    continue
                elif c in HASH:
                    sel.append(f'substr(sha256(getvariable(\'k\') || \'sid\' || r."{c}"), 1, 16) AS "{c}"')
                elif typ in ("DATE", "TIMESTAMP"):
                    sel.append(f'r."{c}" + to_days(x.shift_days) AS "{c}"')
                elif "age" in c and typ in ("INTEGER", "BIGINT", "DOUBLE"):
                    sel.append(f'least(r."{c}", 89) AS "{c}"')
                else:
                    sel.append(f'r."{c}"')
            con.execute(f"""CREATE TABLE {s}.{t} AS SELECT {', '.join(sel)}
                            FROM phi.{s}.{t} r JOIN xw x ON x.vendor = '{s}' AND x.id = r."{key}"::VARCHAR""")
            n = con.execute(f"SELECT count(*) FROM {s}.{t}").fetchone()[0]
            print(f"{s}.{t:16s} {n:>12,}")
        con.execute(sql(f"{s}_views.sql"))
    con.execute(sql("unified.sql"))
    print("views: unified.*")

    # ponytail: leak check — no vendor accession / sample id may survive in any text column
    leaks = []
    for s in present:
        for t, c in con.execute(
                "SELECT table_name, column_name FROM information_schema.columns WHERE table_catalog=current_database() "
                "AND table_schema=? AND data_type IN ('VARCHAR','JSON')", [s]).fetchall():
            n = con.execute(f'SELECT count(*) FROM {s}."{t}" WHERE "{c}"::VARCHAR ~ ?', [ID_PATTERN]).fetchone()[0]
            if n:
                leaks.append(f"{s}.{t}.{c}: {n}")
    assert not leaks, "identifier-like tokens survived de-identification: " + "; ".join(leaks)
    con.close()
    print("wrote", DEID_DB)
