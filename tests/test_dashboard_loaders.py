"""Governance checks on the dashboard data loaders, run against the real de-identified DB.

Skipped when the DB is not on this host; tests/test_pipeline.py covers the pipeline itself
with synthetic data.
"""
import json
import os
import subprocess

import pytest

from uccc_genomics.config import DEID_DB

pytestmark = pytest.mark.skipif(not os.path.exists(DEID_DB), reason=f"no {DEID_DB} on this host")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SECTIONS = {
    "summary": {"meta", "reports_by_year", "assays", "status", "disease", "denom", "gene_alt", "tmb_hist",
                "biomarker_call", "pdl1", "loh_hist", "vaf_hist", "purity_hist", "coverage", "panels", "quality"},
}


@pytest.fixture(scope="module")
def loaders():
    def run(name):
        out = subprocess.run(["uv", "run", "python", f"dashboard/src/data/{name}.json.py"],
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        return json.loads(out)
    return {name: run(name) for name in SECTIONS}


def test_no_small_cells_and_no_row_level_ids(loaders):
    for name, data in loaders.items():
        min_cell = data["meta"]["min_cell"]
        assert min_cell == 5
        for key, val in data.items():
            for row in val if isinstance(val, list) else [val]:
                assert not ({"report_id", "research_id"} & row.keys()), (name, key, row)
                for col in ("n", "n_patients"):
                    assert row.get(col) is None or row[col] >= min_cell, (name, key, row)


def test_sections_present(loaders):
    for name, expected in SECTIONS.items():
        data = loaders[name]
        assert expected <= data.keys(), name
        assert all(len(data[k]) > 0 for k in expected - {"meta"}), name
