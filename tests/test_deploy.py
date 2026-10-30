"""Pins what keeps PHI and /mcp off the public route of the production container (#129)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "compose.yaml"

needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker compose")


def _service() -> dict:
    out = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "--env-file", str(ROOT / "deploy" / ".env.example"),
         "config", "--format", "json"],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)["services"]["genomics-app"]


@needs_docker
def test_compose_mounts_only_the_deid_file_and_its_key_read_only():
    volumes = _service()["volumes"]
    assert len(volumes) == 2
    assert all(v["type"] == "bind" and v["read_only"] is True for v in volumes)
    assert sorted((v["source"].rsplit("/", 1)[1], v["target"]) for v in volumes) == [
        (".db_key", "/data/.db_key"),
        ("genomics.duckdb", "/data/genomics.duckdb"),
    ]
    text = COMPOSE.read_text()
    for forbidden in ("genomics_phi", "db_key_phi", "deid_key", "/raw"):
        assert forbidden not in text


@needs_docker
def test_compose_routes_no_mcp_and_publishes_no_port():
    service = _service()
    assert "ports" not in service
    labels = service["labels"]
    assert "!PathPrefix(`/mcp`)" in labels["traefik.http.routers.uccc-genomics.rule"]
    assert labels["traefik.http.routers.uccc-genomics.tls.certresolver"] == "cloudflare"
    assert labels["traefik.http.routers.uccc-genomics.middlewares"] == "uccc-genomics-rl"
    assert int(labels["traefik.http.middlewares.uccc-genomics-rl.ratelimit.average"]) > 0
    assert int(labels["traefik.http.middlewares.uccc-genomics-rl.ratelimit.burst"]) > 0


@needs_docker
def test_compose_uses_https_base_url_and_authentik_env():
    service = _service()
    env = service["environment"]
    assert env["APP_BASE_URL"].startswith("https://")
    for name in ("SESSION_SECRET", "AUTHENTIK_CLIENT_SECRET", "DATABASE_URL"):
        assert env[name]
    assert "env_file" not in service


def test_dockerignore_is_an_allowlist():
    lines = [ln for ln in (ROOT / ".dockerignore").read_text().splitlines() if ln and not ln.startswith("#")]
    assert lines[0] == "*"
    assert {ln for ln in lines if ln.startswith("!")} == {
        "!pyproject.toml", "!uv.lock", "!.python-version", "!src/", "!mcp/pyproject.toml", "!mcp/src/", "!web/",
    }


def test_dockerfile_runs_authentik_as_non_root():
    text = (ROOT / "Dockerfile").read_text()
    assert "\nUSER 10001\n" in text
    cmd = next(ln for ln in text.splitlines() if ln.startswith("CMD "))
    assert '"--auth", "authentik"' in cmd
