"""Tests for the govity analysis using sk-nrsr-data-2023-202x data."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
GOVITY_SCRIPT = Path(__file__).parent.parent / "govity.py"

_LEGISLATURE = REPO_ROOT / "legislatures" / "sk-nrsr-data-2023-202x"
TEST_DEFINITION  = _LEGISLATURE / "analyses" / "govity" / "govity_definition.json"
TEST_VOTES       = _LEGISLATURE / "work" / "standard" / "votes.csv"
TEST_VOTE_EVENTS = _LEGISLATURE / "work" / "standard" / "vote_events.json"
TEST_PERSONS     = _LEGISLATURE / "analyses" / "all-members" / "outputs" / "all_members.json"

_SCHEMA_BASE = REPO_ROOT / "legislature-data-standard" / "dist"
OUTPUT_SCHEMA_PATH = _SCHEMA_BASE / "dt.analyses" / "govity" / "latest" / "schemas" / "govity.dt.analyses.json"

pytestmark = pytest.mark.skipif(
    not TEST_VOTES.exists(),
    reason="sk-nrsr work/standard/votes.csv not present",
)


def run_script(*extra_args, output_path: Path | None = None):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = Path(tmp.name) if output_path is None else output_path
    cmd = [
        sys.executable, str(GOVITY_SCRIPT),
        "--definition",  str(TEST_DEFINITION),
        "--votes",       str(TEST_VOTES),
        "--vote_events", str(TEST_VOTE_EVENTS),
        "--persons",     str(TEST_PERSONS),
        "--output",      str(out),
        *extra_args,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = None
    if result.returncode == 0 and out.exists():
        with open(out) as f:
            data = json.load(f)
    return result.returncode, result.stdout, result.stderr, data


@pytest.fixture(scope="module")
def output_data():
    rc, stdout, stderr, data = run_script()
    assert rc == 0, f"Script failed:\nSTDOUT: {stdout}\nSTDERR: {stderr}"
    assert data is not None
    return data


class TestOutputNotEmpty:
    def test_has_persons(self, output_data):
        assert len(output_data) > 0

    def test_has_many_persons(self, output_data):
        assert len(output_data) >= 100, f"Expected >=100 records, got {len(output_data)}"


class TestOutputSchema:
    def test_validates_against_schema(self, output_data):
        with open(OUTPUT_SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(instance=output_data, schema=schema)

    def test_required_fields_present(self, output_data):
        for i, row in enumerate(output_data):
            for field in ("person_id", "govity_total", "govity_possible"):
                assert field in row, f"Row {i} missing '{field}'"


class TestOutputValues:
    def test_counts_non_negative(self, output_data):
        for row in output_data:
            assert row["govity_total"] >= 0
            assert row["govity_possible"] >= 0

    def test_total_le_possible(self, output_data):
        for row in output_data:
            assert row["govity_total"] <= row["govity_possible"]

    def test_no_duplicate_person_ids(self, output_data):
        ids = [r["person_id"] for r in output_data]
        assert len(ids) == len(set(ids))

    def test_coalition_MPs_have_govity(self, output_data):
        """Coalition MPs should have govity_possible > 0 (they voted on government motions)."""
        with open(TEST_PERSONS) as f:
            persons = json.load(f)
        import json as _json
        coalition_org_ids = {
            "nrsr:org:club:8", "nrsr:org:club:9",   # SMER variants
            "nrsr:org:club:1", "nrsr:org:club:2",   # HLAS variants
            "nrsr:org:club:10", "nrsr:org:club:13",  # SNS variants
        }
        coalition_person_ids = set()
        for p in persons:
            memb = p.get("memberships", {})
            groups = memb.get("groups", [])
            if any(g.get("id") in coalition_org_ids for g in groups):
                coalition_person_ids.add(p["id"])
        by_id = {r["person_id"]: r for r in output_data}
        has_govity = sum(
            1 for pid in coalition_person_ids
            if pid in by_id and by_id[pid]["govity_possible"] > 0
        )
        assert has_govity > 0, "No coalition MP has govity_possible > 0"
