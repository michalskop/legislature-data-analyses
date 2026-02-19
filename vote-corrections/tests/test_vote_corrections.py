"""
Tests for the vote-corrections analysis.

All tests use synthetic in-memory data — no external files required.
When a real objections dataset exists (e.g. cz-psp-data-2025-202x),
integration tests can be added following the attendance test pattern.

Run with:
    python -m pytest legislature-data-analyses/vote-corrections/tests/
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Import the analysis module directly
sys.path.insert(0, str(Path(__file__).parent.parent))
from vote_corrections import calculate_vote_corrections, parse_date_prefix


# ── Fixtures ───────────────────────────────────────────────────────────────────

PERSONS = [
    {"id": "p1", "name": "Alice Novak",   "memberships": {"groups": [{"id": "g1", "name": "Group A"}]}},
    {"id": "p2", "name": "Bob Dvorak",    "memberships": {"groups": [{"id": "g2", "name": "Group B"}]}},
    {"id": "p3", "name": "Carol Kratka",  "memberships": {}},
]

VOTE_EVENTS = [
    {"id": "ve1", "status": "valid",   "start_date": "2025-01-10"},
    {"id": "ve2", "status": "invalid", "start_date": "2025-01-11"},  # invalidated
    {"id": "ve3", "status": "valid",   "start_date": "2025-01-12"},
    {"id": "ve4", "status": "valid",   "start_date": "2025-01-13"},
    {"id": "ve5"},                                                    # no status → valid
]

VOTES = [
    # p1 voted in ve1, ve2, ve3, ve4
    {"voter_id": "p1", "vote_event_id": "ve1", "option": "yes"},
    {"voter_id": "p1", "vote_event_id": "ve2", "option": "yes"},
    {"voter_id": "p1", "vote_event_id": "ve3", "option": "no"},
    {"voter_id": "p1", "vote_event_id": "ve4", "option": "yes"},
    # p2 voted in ve1, ve3
    {"voter_id": "p2", "vote_event_id": "ve1", "option": "no"},
    {"voter_id": "p2", "vote_event_id": "ve3", "option": "abstain"},
    # p3 voted in ve5 only
    {"voter_id": "p3", "vote_event_id": "ve5", "option": "yes"},
]

OBJECTIONS = [
    # p1 corrected ve1 — only announced
    {"id": "obj1", "vote_event_id": "ve1", "type": "vote_correction",
     "raised_by_id": "p1", "raised_by_type": "person",
     "outcome": "announced", "date": "2025-01-10"},
    # p1 corrected ve2 — led to invalidation
    {"id": "obj2", "vote_event_id": "ve2", "type": "vote_correction",
     "raised_by_id": "p1", "raised_by_type": "person",
     "outcome": "invalidated", "date": "2025-01-11"},
    # p2 corrected ve3 — announced
    {"id": "obj3", "vote_event_id": "ve3", "type": "vote_correction",
     "raised_by_id": "p2", "raised_by_type": "person",
     "outcome": "announced", "date": "2025-01-12"},
    # event_objection (not a personal correction) — must be ignored
    {"id": "obj4", "vote_event_id": "ve4", "type": "event_objection",
     "raised_by_id": "p1", "raised_by_type": "person",
     "outcome": "rejected", "date": "2025-01-13"},
    # correction without raised_by_id — must be ignored
    {"id": "obj5", "vote_event_id": "ve3", "type": "vote_correction",
     "outcome": "announced", "date": "2025-01-12"},
]


@pytest.fixture
def result():
    return calculate_vote_corrections(
        OBJECTIONS, VOTE_EVENTS, VOTES, PERSONS,
        since_date=None, until_date=None,
    )


@pytest.fixture
def by_id(result):
    return {r["person_id"]: r for r in result}


# ── Basic structure ────────────────────────────────────────────────────────────

class TestOutputStructure:
    def test_one_row_per_person(self, result):
        assert len(result) == len(PERSONS)

    def test_required_fields_present(self, result):
        for row in result:
            for field in ("person_id", "corrections_total",
                          "corrections_invalidated", "corrections_announced",
                          "vote_events_total"):
                assert field in row, f"Missing field '{field}' in row {row}"

    def test_no_duplicate_person_ids(self, result):
        ids = [r["person_id"] for r in result]
        assert len(ids) == len(set(ids))

    def test_all_persons_present(self, result):
        output_ids = {r["person_id"] for r in result}
        input_ids  = {p["id"] for p in PERSONS}
        assert output_ids == input_ids


# ── Correction counts ──────────────────────────────────────────────────────────

class TestCorrectionCounts:
    def test_p1_total(self, by_id):
        # obj1 (announced) + obj2 (invalidated); obj4 is event_objection → excluded
        assert by_id["p1"]["corrections_total"] == 2

    def test_p1_invalidated(self, by_id):
        assert by_id["p1"]["corrections_invalidated"] == 1

    def test_p1_announced(self, by_id):
        assert by_id["p1"]["corrections_announced"] == 1

    def test_p2_total(self, by_id):
        assert by_id["p2"]["corrections_total"] == 1

    def test_p2_announced(self, by_id):
        assert by_id["p2"]["corrections_announced"] == 1

    def test_p3_zero_corrections(self, by_id):
        assert by_id["p3"]["corrections_total"] == 0
        assert by_id["p3"]["corrections_invalidated"] == 0
        assert by_id["p3"]["corrections_announced"] == 0

    def test_event_objection_excluded(self, by_id):
        # obj4 is type=event_objection — must NOT count for p1
        assert by_id["p1"]["corrections_total"] == 2  # not 3

    def test_correction_without_raised_by_excluded(self, by_id):
        # obj5 has no raised_by_id — total for p2 stays 1
        assert by_id["p2"]["corrections_total"] == 1

    def test_counts_non_negative(self, result):
        for row in result:
            assert row["corrections_total"] >= 0
            assert row["corrections_invalidated"] >= 0
            assert row["corrections_announced"] >= 0

    def test_invalidated_plus_announced_le_total(self, result):
        for row in result:
            assert row["corrections_invalidated"] + row["corrections_announced"] <= row["corrections_total"]


# ── Vote events total ──────────────────────────────────────────────────────────

class TestVoteEventsTotal:
    def test_p1_vote_events_total(self, by_id):
        # ve1, ve3, ve4 are valid; ve2 is invalid → excluded
        assert by_id["p1"]["vote_events_total"] == 3

    def test_p2_vote_events_total(self, by_id):
        # ve1, ve3 valid
        assert by_id["p2"]["vote_events_total"] == 2

    def test_p3_vote_events_total(self, by_id):
        # ve5 has no status → treated as valid
        assert by_id["p3"]["vote_events_total"] == 1

    def test_invalid_events_excluded(self, by_id):
        # ve2 is invalid; p1 voted there but it must not count
        assert by_id["p1"]["vote_events_total"] == 3  # not 4

    def test_counts_non_negative(self, result):
        for row in result:
            assert row["vote_events_total"] >= 0


# ── Date filtering ─────────────────────────────────────────────────────────────

class TestDateFiltering:
    def test_since_excludes_earlier_events(self):
        # since 2025-01-12: only ve3 (2025-01-12) and ve4 (2025-01-13) are valid
        result = calculate_vote_corrections(
            OBJECTIONS, VOTE_EVENTS, VOTES, PERSONS,
            since_date=parse_date_prefix("2025-01-12"),
            until_date=None,
        )
        by_id = {r["person_id"]: r for r in result}
        # p1 voted in ve3, ve4 → 2
        assert by_id["p1"]["vote_events_total"] == 2
        # obj1 (2025-01-10) is before since → excluded; obj2 (2025-01-11) excluded
        assert by_id["p1"]["corrections_total"] == 0

    def test_until_excludes_later_events(self):
        # until 2025-01-11: ve1 (valid) and ve2 (invalid) are in range
        result = calculate_vote_corrections(
            OBJECTIONS, VOTE_EVENTS, VOTES, PERSONS,
            since_date=None,
            until_date=parse_date_prefix("2025-01-11"),
        )
        by_id = {r["person_id"]: r for r in result}
        # p1: ve1 valid, ve2 invalid → total=1
        assert by_id["p1"]["vote_events_total"] == 1
        # obj1 (2025-01-10 ≤ 2025-01-11) + obj2 (2025-01-11 ≤ 2025-01-11) → 2
        assert by_id["p1"]["corrections_total"] == 2

    def test_since_until_written_to_output(self):
        result = calculate_vote_corrections(
            OBJECTIONS, VOTE_EVENTS, VOTES, PERSONS,
            since_date=parse_date_prefix("2025-01-01"),
            until_date=parse_date_prefix("2025-12-31"),
        )
        for row in result:
            assert row.get("since") == "2025-01-01"
            assert row.get("until") == "2025-12-31"

    def test_no_dates_no_since_until_in_output(self, result):
        for row in result:
            assert "since" not in row
            assert "until" not in row


# ── Person metadata pass-through ───────────────────────────────────────────────

class TestPersonMetadata:
    def test_name_passed_through(self, by_id):
        assert by_id["p1"]["name"] == "Alice Novak"

    def test_organizations_passed_through(self, by_id):
        orgs = by_id["p1"].get("organizations", [])
        assert any(o["id"] == "g1" for o in orgs)

    def test_person_with_no_memberships(self, by_id):
        # p3 has empty memberships
        assert by_id["p3"].get("organizations", []) == []

    def test_image_in_extras(self):
        persons_with_image = [
            {"id": "px", "name": "Test MP",
             "image": "https://example.com/photo.jpg", "memberships": {}}
        ]
        result = calculate_vote_corrections([], VOTE_EVENTS, [], persons_with_image, None, None)
        row = result[0]
        assert row.get("extras", {}).get("image") == "https://example.com/photo.jpg"
