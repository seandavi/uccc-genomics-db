"""UCCC Genomics MCP (v2) Server.

Provides read-only access to the de-identified DuckDB database (genomics.duckdb)
over standard MCP transports (SSE, Streamable HTTP, stdio) for use on the tailnet.
"""
import argparse
import os
import re
import sys
from typing import Any

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

# Configuration defaults
DATA = os.environ.get("DATA", "/data/davsean/genomics")
DEID_DB = os.environ.get("DEID_DB", f"{DATA}/genomics.duckdb")
DEID_DB_KEY = os.environ.get("DEID_DB_KEY", f"{DATA}/.db_key")

DOCS = {
    "overview": """
# UCCC Genomics Database Overview
- Aggregates clinical NGS reports from Caris Life Sciences and Foundation Medicine (FMI).
- Fully de-identified: patient research_id is a deterministic cross-vendor keyed hash of MRN (or name+DOB).
- Dates shifted per-patient by ±182 days (all intervals preserved).
- Patient age capped at 89.
- Three primary database schemas:
  1. `unified.*`: Cross-vendor unified views (patient, report, variant, cna, fusion, biomarker, gene_tested).
  2. `caris.*`: Caris-specific deliveries, including WTS expression, IHC, and ~68k gene TPMs.
  3. `fmi.*`: Foundation Medicine deliveries, including curated alterations, therapies, trials, pertinent negatives.
""".strip(),

    "unified": """
# Unified Schema Reference (`unified.*`)
All tables share `research_id` (patient) and `report_id` (test accession).

1. `unified.patient`:
   - Columns: research_id, gender, n_reports, n_vendors, vendors, first_collected_on, last_collected_on
   - 1 row per patient across all vendors.

2. `unified.report`:
   - Columns: vendor, report_id, research_id, assay_name, assay_class (tissue/liquid/heme), genome_build, ordered_on, collected_on, received_on, reported_on, gender, disease_text, disease_detail_text, primary_site_text, icd_code, tumor_purity_pct, report_status

3. `unified.variant`:
   - Short variants (SNVs, indels, non-wildtype calls).
   - Columns: vendor, report_id, research_id, gene, hgvs_c, hgvs_p, chrom, pos, ref, alt, transcript, vaf (0..1), depth, consequence, is_vus, is_subclonal, genome_build, vendor_call

4. `unified.cna`:
   - Copy number alterations.
   - Columns: vendor, report_id, research_id, gene, cn_type (amplification/loss), copy_number, ratio, coordinates, equivocal, genome_build, vendor_call

5. `unified.fusion`:
   - Structural rearrangements and gene fusions.
   - Columns: vendor, report_id, research_id, gene1, gene2, description, breakpoint1, breakpoint2, supporting_reads, in_frame, genome_build, vendor_call

6. `unified.biomarker`:
   - Key molecular biomarkers in long format: TMB, MSI, LOH, PD-L1.
   - Columns: vendor, report_id, research_id, name, call, value, unit, call_norm (e.g. HIGH / LOW / STABLE)

7. `unified.gene_tested`:
   - Tracks which genes were verified tested (Caris wild-type records + FMI pertinent negatives).
   - Columns: vendor, report_id, research_id, gene, evidence, panel
""".strip(),

    "vendor_schemas": """
# Vendor-Specific Schemas (`caris.*` and `fmi.*`)
Joinable back to `unified.report` using `report_id`.

Caris-specific (`caris.*`):
- `caris.gene_tpm`: Whole-transcriptome RNA-seq TPM for ~68k genes per case (case_id, gene, tpm).
- `caris.wts_expression`: Curated high/low/normal percentile expression calls.
- `caris.ihc`: Immunohistochemistry results (e.g. HER2, PD-L1 clones, mismatch repair).
- `caris.specimen`: Specimen collection details, age at collection, specimen site.

Foundation Medicine-specific (`fmi.*`):
- `fmi.alteration`: Curated alteration blocks from FMI's Include section.
- `fmi.therapy`: Curated vendor-suggested therapies linked to specific alterations.
- `fmi.trial`: Matched clinical trials listed on FMI reports.
- `fmi.sample`: Sequencing quality metrics (mean exon depth, nucleic acid type, bait set).
""".strip(),

    "examples": """
# Example SQL Queries

-- 1. Find patients with KRAS G12C and their TMB status:
SELECT v.research_id, v.vendor, v.report_id, v.hgvs_p, v.vaf, b.call_norm AS tmb_status, b.value AS tmb_mut_per_mb
FROM unified.variant v
LEFT JOIN unified.biomarker b ON b.report_id = v.report_id AND b.name = 'TMB'
WHERE v.gene = 'KRAS' AND v.hgvs_p ILIKE '%G12C%'
LIMIT 20;

-- 2. Multi-vendor patient overlap (tested at both Caris and FMI):
SELECT p.research_id, p.n_reports, p.vendors, r.vendor, r.assay_name, r.disease_text
FROM unified.patient p
JOIN unified.report r ON r.research_id = p.research_id
WHERE p.n_vendors > 1
ORDER BY p.research_id, r.collected_on
LIMIT 20;

-- 3. Top mutated genes across all reports (excluding VUS):
SELECT gene, count(DISTINCT report_id) AS n_reports, count(DISTINCT research_id) AS n_patients
FROM unified.variant
WHERE NOT coalesce(is_vus, false)
GROUP BY gene
ORDER BY n_reports DESC
LIMIT 15;
""".strip()
}


def get_db():
    """Create a new read-only DuckDB connection to the encrypted de-id database."""
    if not os.path.exists(DEID_DB_KEY):
        raise FileNotFoundError(f"Database encryption key file not found: {DEID_DB_KEY}")
    key = open(DEID_DB_KEY).read().strip()
    con = duckdb.connect()
    con.execute(f"ATTACH '{DEID_DB}' AS db (ENCRYPTION_KEY '{key}', READ_ONLY)")
    con.execute("USE db")
    return con


# Initialize MCP server
mcp = MCPServer(
    name="uccc-genomics-mcp",
    title="UCCC Genomics Database MCP Server",
    description="Query de-identified UCCC vendor genomics data (Caris + Foundation Medicine)",
    instructions=(
        "You have read-only access to the UCCC de-identified genomics database via DuckDB. "
        "Use list_tables to explore available schemas (unified, caris, fmi), describe_tables "
        "for column definitions, query for executing SQL, and get_docs for domain documentation."
    ),
)


@mcp.tool()
def list_tables(schema: str = "") -> list[dict[str, str]]:
    """List tables and views available in the database.
    
    Args:
        schema: Optional schema name filter (e.g. 'unified', 'caris', 'fmi'). Leave empty for all.
    """
    con = get_db()
    try:
        where = ["table_schema NOT IN ('information_schema', 'pg_catalog')"]
        params = []
        if schema.strip():
            where.append("table_schema = ?")
            params.append(schema.strip())
        sql = f"""
            SELECT table_schema AS schema_name, table_name, table_type
            FROM information_schema.tables
            WHERE {' AND '.join(where)}
            ORDER BY table_schema, table_name
        """
        rows = con.execute(sql, params).fetchall()
        return [{"schema": r[0], "name": r[1], "type": r[2]} for r in rows]
    finally:
        con.close()


@mcp.tool()
def describe_tables(tables: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Get the column definitions and data types for one or more tables or views.
    
    Args:
        tables: List of table names (optionally schema-qualified, e.g. ['unified.variant', 'caris.report']).
    """
    con = get_db()
    result = {}
    try:
        for t in tables:
            t = t.strip()
            if not re.match(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?$", t):
                result[t] = [{"error": f"Invalid table name format: {t}"}]
                continue
            try:
                cols = con.execute(f"DESCRIBE {t}").fetchall()
                result[t] = [
                    {"column_name": c[0], "column_type": c[1], "nullable": c[2] == "YES"}
                    for c in cols
                ]
            except Exception as e:
                result[t] = [{"error": str(e)}]
        return result
    finally:
        con.close()


@mcp.tool()
def query(sql: str, limit: int = 100) -> dict[str, Any]:
    """Execute a read-only SQL query against the de-identified DuckDB database.
    
    Args:
        sql: The SQL query to execute (SELECT / WITH only).
        limit: Maximum number of rows to return (default: 100, max: 1000).
    """
    cleaned = sql.strip().strip(";").strip()
    # Basic safety check to ensure read-only execution
    first_word = cleaned.split()[0].upper() if cleaned else ""
    if first_word not in ("SELECT", "WITH", "DESCRIBE", "EXPLAIN", "SHOW"):
        return {"error": "Only read-only queries (SELECT, WITH, DESCRIBE, EXPLAIN, SHOW) are allowed."}

    forbidden_patterns = [
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|INSTALL|LOAD)\b",
        r"\bCOPY\b.*\bTO\b",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return {"error": "Write, schema modification, or external file export operations are not permitted."}

    max_limit = min(max(1, limit), 1000)
    wrapped_sql = f"SELECT * FROM ({cleaned}) LIMIT {max_limit}"

    con = get_db()
    try:
        cur = con.execute(wrapped_sql)
        col_names = [d[0] for d in cur.description]
        raw_rows = cur.fetchall()
        rows = [dict(zip(col_names, row)) for row in raw_rows]
        return {
            "columns": col_names,
            "row_count": len(rows),
            "rows": rows,
            "truncated": len(rows) == max_limit,
        }
    except Exception as e:
        return {"error": f"Query execution failed: {e}"}
    finally:
        con.close()


@mcp.tool()
def get_documentation(topic: str = "overview") -> str:
    """Retrieve database schema documentation and example queries.
    
    Use this to understand available fields and query patterns without bloating context.
    
    Args:
        topic: One of 'overview', 'unified', 'vendor_schemas', 'examples', or 'all'.
    """
    topic = topic.strip().lower()
    if topic == "all":
        return "\n\n---\n\n".join(DOCS.values())
    if topic in DOCS:
        return DOCS[topic]
    return f"Unknown topic '{topic}'. Available topics: {list(DOCS.keys())} or 'all'."


def main(argv=None):
    parser = argparse.ArgumentParser(description="UCCC Genomics MCP (v2) Server")
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "sse", "stdio"],
        default="streamable-http",
        help="MCP transport (default: streamable-http)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind for network transports (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8088,
        help="Port for network transports (default: 8088)",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="Path for Streamable HTTP transport (default: /mcp)",
    )
    args = parser.parse_args(argv)

    sec = TransportSecuritySettings(
        allowed_hosts=["*"],
        allowed_origins=["*"],
        enable_dns_rebinding_protection=False,
    )

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "streamable-http":
        print(f"Starting UCCC Genomics MCP v2 Server (Streamable HTTP) on http://{args.host}:{args.port}{args.path}", file=sys.stderr)
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=args.path,
            transport_security=sec,
        )
    elif args.transport == "sse":
        print(f"Starting UCCC Genomics MCP Server (SSE) on http://{args.host}:{args.port}/sse", file=sys.stderr)
        mcp.run(
            transport="sse",
            host=args.host,
            port=args.port,
            transport_security=sec,
        )


if __name__ == "__main__":
    main()
