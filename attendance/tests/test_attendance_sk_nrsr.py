"""Tests for the attendance analysis using sk-nrsr-data-2023-202x data.

Run with:
    python -m pytest legislature-data-analyses/attendance/tests/test_attendance_sk_nrsr.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
ATTENDANCE_SCRIPT = Path(__file__).parent.parent / "attendance.py"

_LEGISLATURE = REPO_ROOT / "legislatures" / "sk-nrsr-data-2023-202x"
TEST_DEFINITION  = _LEGISLATURE / "analyses" / "attendance" / "attendance_definition.json"
TEST_VOTES       = _LEGISLATURE / "work" / "standard" / "votes.csv"
TEST_VOTE_EVENTS = _LEGISLATURE / "work" / "standard" / "vote_events.json"
TEST_PERSONS     = _LEGISLATURE / "analyses" / "all-members" / "outputs" / "all_members.json"

_SCHEMA_BASE = REPO_ROOT / "legislature-data-standard" / "dist"
OUTPUT_SCHEMA_PATH = _SCHEMA_BASE / "dt.analyses" / "attendance" / "latest" / "schemas" / "attendance.dt.analyses.json"

pytestmark = pytest.mark.skipif(
    not TEST_VOTES.exists(),
    reason="sk-nrsr work/standard/votes.csv not present — run scrape+standardize first",
)


def run_script(*extra_args, output_path: Path | None = None):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = Path(tmp.name) if output_path is None else output_path
    cmd = [
        sys.executable, str(ATTENDANCE_SCRIPT),
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


@pytest.fixture(scope="module")
def definition():
    with open(TEST_DEFINITION) as f:
        return json.load(f)


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
            for field in ("person_id", "present", "absent", "vote_events_total"):
                assert field in row, f"Row {i} missing '{field}'"


class TestOutputValues:
    def test_counts_non_negative(self, output_data):
        for row in output_data:
            assert row["present"] >= 0
            assert row["absent"] >= 0

    def test_total_le_possible(self, output_data):
        for row in output_data:
            assert row["present"] <= row["vote_events_total"]

    def test_no_duplicate_person_ids(self, output_data):
        ids = [r["person_id"] for r in output_data]
        assert len(ids) == len(set(ids))

    def test_all_persons_in_output(self, output_data):
        with open(TEST_PERSONS) as f:
            persons = json.load(f)
        input_ids = {p["id"] for p in persons}
        output_ids = {r["person_id"] for r in output_data}
        assert input_ids == output_ids
