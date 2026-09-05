"""Tests for dashboard cohort data loader and privacy rules."""
import subprocess
import json
import pytest


@pytest.fixture(scope="module")
def cohort_data():
    """Run dashboard/src/data/cohort.json.py and parse output JSON."""
    result = subprocess.run(
        ["uv", "run", "python", "dashboard/src/data/cohort.json.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_cohort_data_keys(cohort_data):
    """Verify all 10 required top-level keys exist."""
    required_keys = [
        "meta",
        "diseases",
        "genes",
        "annual_disease_denoms",
        "annual_overall_denoms",
        "annual_disease_gene_alt",
        "annual_overall_gene_alt",
        "disease_gene_totals",
        "top_comutations",
        "assays",
    ]
    for key in required_keys:
        assert key in cohort_data, f"Missing key {key}"


def test_cohort_meta(cohort_data):
    """Verify metadata contains required fields and valid counts."""
    meta = cohort_data["meta"]
    assert meta["min_cell"] == 5
    assert meta["min_year"] == 2014
    assert meta["max_year"] == 2026
    assert meta["total_reports"] >= meta["total_patients"] > 0


def test_privacy_governance_rules(cohort_data):
    """Verify strictly no small cells (< 5) and zero row-level identifiers."""
    min_cell = cohort_data["meta"]["min_cell"]
    assert min_cell == 5

    for key, val in cohort_data.items():
        items = val if isinstance(val, list) else [val]
        for row in items:
            # Zero row-level records
            assert not ({"report_id", "research_id"} & row.keys()), (
                f"Row-level identifier found in {key}: {row}"
            )
            # Min cell threshold
            for col, v in row.items():
                if col in ("n", "n_patients", "count") and isinstance(v, int):
                    assert v >= min_cell, (
                        f"Small cell violation in {key}.{col} = {v}: {row}"
                    )


def test_diseases_and_genes_format(cohort_data):
    """Verify diseases and genes lists."""
    diseases = cohort_data["diseases"]
    assert len(diseases) > 0
    for d in diseases:
        assert "disease" in d
        assert d["n"] >= 5
        assert d["disease"] not in ("", "N/A")

    genes = cohort_data["genes"]
    assert len(genes) > 0
    for g in genes:
        assert "gene" in g
        assert g["n"] >= 5
        assert g["gene"] not in ("", "N/A", "NULL")


def test_top_comutations(cohort_data):
    """Verify pairwise co-mutations."""
    comut = cohort_data["top_comutations"]
    assert len(comut) > 0
    for r in comut:
        assert "gene_a" in r and "gene_b" in r
        assert r["gene_a"] != r["gene_b"]
        assert r["n"] >= 5


def test_assays(cohort_data):
    """Verify assay list."""
    assays = cohort_data["assays"]
    assert len(assays) > 0
    for a in assays:
        assert a["vendor"] in ("caris", "fmi")
        assert a["assay_class"] in ("tissue", "liquid", "heme")
        assert a["n"] >= 5
