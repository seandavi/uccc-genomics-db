"""The MCP `query` tool must not let a tailnet client read or write anything outside the de-id DB."""
import duckdb
import pytest

from uccc_genomics_mcp import server


@pytest.fixture
def sandbox(monkeypatch):
    # Same hardening as get_db(), on an empty in-memory DB so the test needs no data files.
    monkeypatch.setattr(server, "get_db", lambda: server.harden(duckdb.connect()))


def test_select_works(sandbox):
    r = server.query("SELECT 1 AS one")
    assert r["rows"] == [{"one": 1}] and r["truncated"] is False


def test_limit_is_capped(sandbox):
    r = server.query("SELECT * FROM range(5000)", limit=100_000)
    assert r["row_count"] == 1000 and r["truncated"] is True


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_text('/etc/hostname')",       # not on the keyword denylist; DuckDB itself must refuse
    "SELECT * FROM read_blob('/etc/hostname')",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM '/etc/passwd'",
    "SELECT 1; SET enable_external_access = true",
])
def test_file_access_is_refused(sandbox, sql):
    r = server.query(sql)
    assert "error" in r and "rows" not in r


@pytest.mark.parametrize("sql", [
    "CREATE TABLE x AS SELECT 1",
    "INSERT INTO x VALUES (1)",
    "ATTACH '/tmp/x.duckdb' AS y",
    "COPY (SELECT 1) TO '/tmp/out.csv'",
    "INSTALL httpfs",
    "select 1; drop table x",
])
def test_writes_are_refused(sandbox, sql):
    assert "error" in server.query(sql)
