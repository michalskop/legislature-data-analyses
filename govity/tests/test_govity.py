"""
Tests for the govity analysis.

Run with:
    python -m pytest legislature-data-analyses/govity/tests/
or from the govity directory:
    python -m pytest tests/
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import pytest

# ── Path constants ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # legislature-data/
GOVITY_SCRIPT = Path(__file__).parent.parent / "govity.py"

# Test data paths (CZ PSP 2025-202x)
_LEGISLATURE    = REPO_ROOT / "legislatures" / "cz-psp-data-2025-202x"
TEST_DEFINITION  = _LEGISLATURE / "analyses" / "govity" / "govity_definition.json"
TEST_VOTES       = _LEGISLATURE / "work" / "standard" / "votes.csv"
TEST_VOTE_EVENTS = _LEGISLATURE / "work" / "standard" / "vote_events.json"
TEST_PERSONS     = _LEGISLATURE / "analyses" / "all-members" / "outputs" / "all_members.json"

# Output schema path
_SCHEMA_BASE = REPO_ROOT / "legislature-data-standard" / "dist"
OUTPUT_SCHEMA_PATH = _SCHEMA_BASE / "dt.analyses" / "govity" / "latest" / "schemas" / "govity.dt.analyses.json"


# ── Helpers ────────────────────────────────────────────────────────────────────

def run_script(*extra_args, output_path: Path | None = None) -> tuple[int, str, str, list[dict] | None]:
    """Run the govity script and return (returncode, stdout, stderr, parsed_output)."""
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


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestOutputNotEmpty:
    def test_has_persons(self, output_data):
        """Output must contain at least one person."""
        assert len(output_data) > 0, "Output is empty – expected at least one govity record"

    def test_has_many_persons(self, output_data):
        """Sanity check: Czech parliament has ~200 members."""
        assert len(output_data) >= 100, f"Expected >=100 records, got {len(output_data)}"


class TestOutputSchema:
    def test_validates_against_schema(self, output_data):
        """Output must validate against govity.dt.analyses JSON schema."""
        with open(OUTPUT_SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(instance=output_data, schema=schema)

    def test_required_fields_present(self, output_data):
        """Every row must have person_id, govity_total, govity_possible."""
        for i, row in enumerate(output_data):
            for field in ("person_id", "govity_total", "govity_possible"):
                assert field in row, f"Row {i} missing required field '{field}'"


class TestGovityCounts:
    def test_counts_non_negative(self, output_data):
        """govity_total and govity_possible must be non-negative integers."""
        for row in output_data:
            assert row["govity_total"] >= 0
            assert row["govity_possible"] >= 0

    def test_total_le_possible(self, output_data):
        """govity_total must not exceed govity_possible."""
        for row in output_data:
            assert row["govity_total"] <= row["govity_possible"], (
                f"Person {row['person_id']}: govity_total ({row['govity_total']}) "
                f"> govity_possible ({row['govity_possible']})"
            )

    def test_govity_rate_range(self, output_data):
        """govity must be between 0 and 1 inclusive (or null when possible=0)."""
        for row in output_data:
            gv = row.get("govity")
            if gv is not None:
                assert 0.0 <= gv <= 1.0, (
                    f"Person {row['person_id']}: govity {gv} out of [0,1]"
                )

    def test_govity_null_when_possible_zero(self, output_data):
        """If govity_possible == 0, govity must be null."""
        for row in output_data:
            if row["govity_possible"] == 0:
                assert row.get("govity") is None, (
                    f"Person {row['person_id']}: govity should be null when possible=0"
                )

    def test_govity_consistent(self, output_data):
        """govity must equal govity_total / govity_possible (within tolerance)."""
        for row in output_data:
            possible = row["govity_possible"]
            gv = row.get("govity")
            if possible > 0:
                expected = row["govity_total"] / possible
                assert gv is not None
                assert abs(gv - round(expected, 6)) < 1e-9, (
                    f"Person {row['person_id']}: govity {gv} != {expected}"
                )

    def test_possible_varies_across_persons(self, output_data):
        """govity_possible should differ across persons (MPs absent from some events)."""
        possibles = {row["govity_possible"] for row in output_data}
        assert len(possibles) > 1, (
            "govity_possible is identical for all persons – expected variation"
        )


class TestGovernmentMembers:
    def test_government_members_have_high_govity(self, output_data, definition):
        """Government group members should have govity > 0.9 on average."""
        gov_groups = set(definition.get("government_groups") or [])
        gov_rows = [
            row for row in output_data
            if any(
                o.get("id") in gov_groups and o.get("classification") == "group"
                for o in (row.get("organizations") or [])
            )
            and row.get("govity") is not None
        ]
        if gov_rows:
            avg = sum(r["govity"] for r in gov_rows) / len(gov_rows)
            assert avg > 0.9, (
                f"Government members' average govity is {avg:.3f}, expected > 0.9"
            )


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


class TestExtras:
    def test_image_url_when_present(self, output_data):
        """If extras.image is set it must be a non-empty string."""
        for row in output_data:
            extras = row.get("extras") or {}
            image = extras.get("image")
            if image is not None:
                assert isinstance(image, str) and image, (
                    f"Person {row['person_id']}: extras.image must be a non-empty string"
                )

    def test_some_persons_have_image(self, output_data):
        """At least one person should carry an image URL from the persons input."""
        images = [
            row["extras"]["image"]
            for row in output_data
            if (row.get("extras") or {}).get("image")
        ]
        assert len(images) > 0, "No person has an image URL – check that persons input includes 'image' fields"


class TestDateOverride:
    def test_since_override_filters_events(self):
        """--since flag should reduce or maintain the number of vote events counted."""
        _, _, _, data_all = run_script()
        _, _, _, data_since = run_script("--since", "2026-01-01")
        assert data_since is not None

        id_to_all = {r["person_id"]: r for r in data_all}
        for row in data_since:
            pid = row["person_id"]
            if pid in id_to_all:
                assert row["govity_possible"] <= id_to_all[pid]["govity_possible"], (
                    f"Person {pid}: govity_possible increased with --since filter"
                )
