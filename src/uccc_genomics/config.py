"""Paths shared by every step. Override with DATA=/some/dir.

Site-specific values (CARIS_BUCKET, FMI_SRC) come from the environment or from the
gitignored repo-root .env (KEY=value lines), per infrastructure/SCHEDULING.md."""
import os
from importlib.resources import files

_ENV = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
if os.path.exists(_ENV):
    for _line in open(_ENV):
        _k, _, _v = _line.strip().partition("=")
        if _k and not _k.startswith("#"):
            os.environ.setdefault(_k, _v)

DATA = os.environ.get("DATA", "/data/davsean/genomics")
RAW = f"{DATA}/raw"
PHI_DB = f"{DATA}/genomics_phi.duckdb"
DEID_DB = f"{DATA}/genomics.duckdb"
KEY_FILE = f"{DATA}/.deid_key"          # hashing key for research_id / report_id
PHI_DB_KEY = f"{DATA}/.db_key_phi"      # AES key for genomics_phi.duckdb
DEID_DB_KEY = f"{DATA}/.db_key"         # AES key for genomics.duckdb (share with the file, never the phi one)

CARIS_BUCKET = os.environ.get("CARIS_BUCKET", "")  # s3://bucket/ holding the Caris deliveries
FMI_SRC = os.environ.get("FMI_SRC", "")            # host:dir holding the FMI XMLs


def sql(name: str) -> str:
    return files("uccc_genomics.sql").joinpath(name).read_text()


def data_file(name: str) -> str:
    return str(files("uccc_genomics.data").joinpath(name))


def read_key(path: str) -> str:
    """Hex key from a mode-600 file, created on first use."""
    import secrets
    if not os.path.exists(path):
        with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


def connect(**dbs):
    """connect(phi=(PHI_DB, PHI_DB_KEY), deid=(DEID_DB, DEID_DB_KEY)) -> in-memory connection with each
    file ATTACHed under its alias, AES-256-GCM encrypted; first alias becomes the default catalog.
    Pass a 3-tuple (path, keyfile, 'READ_ONLY') to attach read-only."""
    import duckdb
    con = duckdb.connect()
    for alias, spec in dbs.items():
        path, keyfile, *opts = spec
        con.execute(f"ATTACH '{path}' AS {alias} (ENCRYPTION_KEY '{read_key(keyfile)}'{''.join(', ' + o for o in opts)})")
    con.execute(f"USE {next(iter(dbs))}")
    return con
