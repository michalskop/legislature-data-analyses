"""Tests for the wpca analysis using sk-nrsr-data-2023-202x data."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
WPCA_SCRIPT = Path(__file__).parent.parent / "wpca.py"

_LEGISLATURE = REPO_ROOT / "legislatures" / "sk-nrsr-data-2023-202x"
TEST_DEFINITION  = _LEGISLATURE / "analyses" / "wpca" / "wpca_definition.json"
TEST_VOTES       = _LEGISLATURE / "work" / "standard" / "votes.csv"
TEST_VOTE_EVENTS = _LEGISLATURE / "work" / "standard" / "vote_events.json"
TEST_PERSONS     = _LEGISLATURE / "analyses" / "all-members" / "outputs" / "all_members.json"

pytestmark = pytest.mark.skipif(
    not TEST_VOTES.exists(),
    reason="sk-nrsr work/standard/votes.csv not present",
)


def run_script(*extra_args, output_path: Path | None = None):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = Path(tmp.name) if output_path is None else output_path
    cmd = [
        sys.executable, str(WPCA_SCRIPT),
        "--definition",   str(TEST_DEFINITION),
        "--votes",        str(TEST_VOTES),
        "--vote-events",  str(TEST_VOTE_EVENTS),
        "--persons",      str(TEST_PERSONS),
        "--output",       str(out),
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


def test_real_data_run_succeeds(output_data):
    assert len(output_data) > 0


def test_output_has_persons(output_data):
    assert len(output_data) >= 100, f"Expected >=100 records, got {len(output_data)}"


def test_output_fields(output_data):
    for i, row in enumerate(output_data):
        for field in ("person_id", "dims", "weight", "included"):
            assert field in row, f"Row {i} missing '{field}'"


def test_dims_have_correct_length(output_data):
    with open(TEST_DEFINITION) as f:
        definition = json.load(f)
    n_dims = definition.get("n_dims", 2)
    for i, row in enumerate(output_data):
        assert len(row["dims"]) == n_dims, (
            f"Row {i}: expected {n_dims} dims, got {len(row['dims'])}"
        )


def test_multiple_periods(output_data):
    # 'since' field distinguishes half-year periods
    periods = {r.get("since") for r in output_data}
    assert len(periods) > 1, "Expected multiple half-year periods (distinct 'since' values)"


def test_no_duplicate_person_period(output_data):
    seen = set()
    for row in output_data:
        key = (row["person_id"], row.get("since"))
        assert key not in seen, f"Duplicate (person_id, since): {key}"
        seen.add(key)
