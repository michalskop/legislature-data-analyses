"""
Tests for the attendance analysis.

Run with:
    python -m pytest legislature-data-analyses/attendance/tests/
or from the attendance directory:
    python -m pytest tests/
"""

import csv
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import pytest

# ── Path constants ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # legislature-data/
ATTENDANCE_SCRIPT = Path(__file__).parent.parent / "attendance.py"

# Test data paths (CZ PSP 2025-202x)
_LEGISLATURE = REPO_ROOT / "legislatures" / "cz-psp-data-2025-202x"
TEST_DEFINITION = _LEGISLATURE / "analyses" / "attendance" / "attendance_definition.json"
TEST_VOTES      = _LEGISLATURE / "work" / "standard" / "votes.csv"
TEST_VOTE_EVENTS = _LEGISLATURE / "work" / "standard" / "vote_events.json"
TEST_PERSONS    = _LEGISLATURE / "analyses" / "all-members" / "outputs" / "all_members.json"

# Output schema path
_SCHEMA_BASE = REPO_ROOT / "legislature-data-standard" / "dist"
OUTPUT_SCHEMA_PATH = _SCHEMA_BASE / "dt.analyses" / "attendance" / "latest" / "schemas" / "attendance.dt.analyses.json"

# ── Helpers ────────────────────────────────────────────────────────────────────

def run_script(*extra_args, output_path: Path | None = None) -> tuple[int, str, str, list[dict] | None]:
    """Run the attendance script and return (returncode, stdout, stderr, parsed_output)."""
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
def output_data() -> list[dict]:
    """Run the script once and return the output for all tests in this module."""
    rc, stdout, stderr, data = run_script()
    assert rc == 0, f"Script failed:\nSTDOUT: {stdout}\nSTDERR: {stderr}"
    assert data is not None, "No output data produced"
    return data


@pytest.fixture(scope="module")
def definition() -> dict:
    with open(TEST_DEFINITION) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def vote_options() -> set[str]:
    """All distinct vote options found in votes.csv."""
    options = set()
    with open(TEST_VOTES, newline="") as f:
        for row in csv.DictReader(f):
            options.add(row["option"])
    return options


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestOutputNotEmpty:
    def test_has_persons(self, output_data):
        """Output must contain at least one person."""
        assert len(output_data) > 0, "Output is empty – expected at least one attendance record"

    def test_has_many_persons(self, output_data):
        """Sanity check: Czech parliament has ~200 members."""
        assert len(output_data) >= 100, f"Expected >=100 records, got {len(output_data)}"


class TestVoteOptionsCoverage:
    def test_all_options_covered(self, definition, vote_options):
        """Every option found in votes.csv must be in present_options OR absent_options."""
        present_set = set(definition["present_options"])
        absent_set  = set(definition["absent_options"])
        known_options = present_set | absent_set
        uncovered = vote_options - known_options
        assert uncovered == set(), (
            f"Vote options not in present_options nor absent_options: {uncovered}\n"
            "All options must be explicitly classified."
        )

    def test_no_overlap_between_option_sets(self, definition):
        """An option cannot be both present and absent."""
        present_set = set(definition["present_options"])
        absent_set  = set(definition["absent_options"])
        overlap = present_set & absent_set
        assert overlap == set(), f"Options appear in both present and absent sets: {overlap}"


class TestOutputSchema:
    def test_validates_against_schema(self, output_data):
        """Output must validate against attendance.dt.analyses JSON schema."""
        with open(OUTPUT_SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(instance=output_data, schema=schema)

    def test_required_fields_present(self, output_data):
        """Every row must have person_id, vote_events_total, present, absent."""
        for i, row in enumerate(output_data):
            for field in ("person_id", "vote_events_total", "present", "absent"):
                assert field in row, f"Row {i} missing required field '{field}'"


class TestAttendanceCounts:
    def test_counts_non_negative(self, output_data):
        """present, absent, vote_events_total must all be non-negative integers."""
        for row in output_data:
            assert row["vote_events_total"] >= 0
            assert row["present"] >= 0
            assert row["absent"] >= 0

    def test_present_plus_absent_le_total(self, output_data):
        """present + absent must not exceed vote_events_total."""
        for row in output_data:
            assert row["present"] + row["absent"] <= row["vote_events_total"], (
                f"Person {row['person_id']}: present ({row['present']}) + absent ({row['absent']}) "
                f"> total ({row['vote_events_total']})"
            )

    def test_vote_events_total_varies_across_persons(self, output_data):
        """vote_events_total should differ across persons (members who served only part of
        the period have a lower total than full-term members)."""
        totals = {row["vote_events_total"] for row in output_data}
        assert len(totals) > 1, (
            "vote_events_total is identical for all persons – expected it to vary "
            "because some members serve only part of the term."
        )

    def test_total_le_global_event_count(self, output_data):
        """No person's vote_events_total should exceed the maximum observed total."""
        max_total = max(row["vote_events_total"] for row in output_data)
        for row in output_data:
            assert row["vote_events_total"] <= max_total

    def test_vote_events_total_positive(self, output_data):
        """There should be at least one vote event in the data."""
        assert output_data[0]["vote_events_total"] > 0, "vote_events_total is 0 – no vote events found"


class TestPresentShare:
    def test_present_share_range(self, output_data):
        """present_share must be between 0 and 1 (inclusive)."""
        for row in output_data:
            ps = row.get("present_share")
            if ps is not None:
                assert 0.0 <= ps <= 1.0, f"Person {row['person_id']}: present_share {ps} out of [0,1]"

    def test_present_share_consistent(self, output_data):
        """present_share must equal present / vote_events_total (within float tolerance)."""
        for row in output_data:
            total = row["vote_events_total"]
            ps = row.get("present_share")
            if total == 0:
                assert ps is None, f"Person {row['person_id']}: expected null present_share when total=0"
            else:
                expected = row["present"] / total
                assert ps is not None, f"Person {row['person_id']}: present_share is None but total={total}"
                assert abs(ps - expected) < 1e-9, (
                    f"Person {row['person_id']}: present_share {ps} != {expected}"
                )

    def test_present_share_null_when_total_zero(self, output_data):
        """If vote_events_total == 0, present_share must be null/omitted."""
        for row in output_data:
            if row["vote_events_total"] == 0:
                assert row.get("present_share") is None


class TestPersonCoverage:
    def test_all_input_persons_in_output(self, output_data):
        """Every person from the persons input must appear in the output."""
        with open(TEST_PERSONS) as f:
            persons = json.load(f)
        input_ids = {p["id"] for p in persons}
        output_ids = {row["person_id"] for row in output_data}
        missing = input_ids - output_ids
        assert missing == set(), f"These persons are missing from output: {missing}"

    def test_no_duplicate_person_ids(self, output_data):
        """Each person_id must appear at most once in the output."""
        ids = [row["person_id"] for row in output_data]
        duplicates = {pid for pid in ids if ids.count(pid) > 1}
        assert duplicates == set(), f"Duplicate person_ids in output: {duplicates}"

    def test_no_extra_persons_in_output(self, output_data):
        """Output should not contain persons that were not in the persons input."""
        with open(TEST_PERSONS) as f:
            persons = json.load(f)
        input_ids = {p["id"] for p in persons}
        output_ids = {row["person_id"] for row in output_data}
        extra = output_ids - input_ids
        assert extra == set(), f"Output contains persons not in input: {extra}"


class TestOrganizations:
    def test_organization_ids_are_strings(self, output_data):
        """All organization entries must have a non-empty string id."""
        for row in output_data:
            for org in row.get("organizations", []):
                assert isinstance(org["id"], str) and org["id"], (
                    f"Person {row['person_id']}: org with invalid id: {org}"
                )
