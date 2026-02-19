"""
Tests for rebelity_govity.calculate_rebelity_govity.

All synthetic — no external files required.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rebelity_govity import (
    calculate_rebelity_govity,
    parse_date_prefix,
    get_group_at_date,
    build_group_memberships,
    vote_value,
    vote_value_active,
)

# ── Shared synthetic data ──────────────────────────────────────────────────────

DEFINITION = {
    "present_options": ["yes", "no", "abstain"],
    "absent_options":  ["absent"],
    "yes_option":      "yes",
    "no_option":       "no",
}

DEFINITION_GOV = {
    **DEFINITION,
    "government_groups":  ["org:gov"],
    "government_members": [],
}

def _events(*ids_and_dates):
    """Build vote-events list: [(id, date_str), ...]"""
    return [{"id": eid, "start_date": d, "status": "valid"} for eid, d in ids_and_dates]

def _votes(*rows):
    """Build votes list: [(event_id, voter_id, option), ...]"""
    return [{"vote_event_id": e, "voter_id": v, "option": o} for e, v, o in rows]

def _person(pid, groups=None, image=None):
    mems = {}
    if groups:
        mems["groups"] = [{"id": g, "name": g, "start_date": None, "end_date": None} for g in groups]
    p = {"id": pid, "name": pid, "memberships": mems}
    if image:
        p["image"] = image
    return p


# ── parse_date_prefix ──────────────────────────────────────────────────────────

class TestParseDatePrefix:
    def test_date_string(self):
        assert parse_date_prefix("2025-01-15") == date(2025, 1, 15)

    def test_datetime_string(self):
        assert parse_date_prefix("2025-01-15T10:30:00") == date(2025, 1, 15)

    def test_none(self):
        assert parse_date_prefix(None) is None

    def test_empty(self):
        assert parse_date_prefix("") is None


# ── vote_value helpers ─────────────────────────────────────────────────────────

class TestVoteValue:
    def test_yes(self):
        assert vote_value("yes", "yes", "no", {"yes", "no", "abstain"}) == 1

    def test_no(self):
        assert vote_value("no", "yes", "no", {"yes", "no", "abstain"}) == -1

    def test_abstain_counts_against(self):
        assert vote_value("abstain", "yes", "no", {"yes", "no", "abstain"}) == -1

    def test_absent_zero(self):
        assert vote_value("absent", "yes", "no", {"yes", "no", "abstain"}) == 0

    def test_active_yes(self):
        assert vote_value_active("yes", "yes", "no") == 1

    def test_active_no(self):
        assert vote_value_active("no", "yes", "no") == -1

    def test_active_abstain_zero(self):
        assert vote_value_active("abstain", "yes", "no") == 0

    def test_active_absent_zero(self):
        assert vote_value_active("absent", "yes", "no") == 0


# ── get_group_at_date ──────────────────────────────────────────────────────────

class TestGetGroupAtDate:
    def test_single_group_no_dates(self):
        persons = [_person("p1", groups=["grp1"])]
        gm = build_group_memberships(persons)
        assert get_group_at_date("p1", date(2025, 6, 1), gm) == "grp1"

    def test_group_changed(self):
        persons = [{
            "id": "p1",
            "memberships": {"groups": [
                {"id": "grp1", "start_date": "2025-01-01", "end_date": "2025-06-30"},
                {"id": "grp2", "start_date": "2025-07-01", "end_date": None},
            ]},
        }]
        gm = build_group_memberships(persons)
        assert get_group_at_date("p1", date(2025, 3, 1), gm) == "grp1"
        assert get_group_at_date("p1", date(2025, 8, 1), gm) == "grp2"

    def test_no_group(self):
        persons = [_person("p1")]
        gm = build_group_memberships(persons)
        assert get_group_at_date("p1", date(2025, 1, 1), gm) is None


# ── Basic rebelity ─────────────────────────────────────────────────────────────

class TestRebelityBasic:
    def test_mp_votes_with_group(self):
        """MP always votes with their group → rebelity = 0."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"])]
        events = _events(("ev1", "2025-01-01"), ("ev2", "2025-01-02"))
        votes = _votes(
            ("ev1", "p1", "yes"), ("ev1", "p2", "yes"),
            ("ev2", "p1", "no"),  ("ev2", "p2", "no"),
        )
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_total"] == 0
        assert p1["rebelity_possible"] == 2
        assert p1["rebelity"] == 0.0

    def test_mp_always_rebels(self):
        """MP always votes opposite to their group."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"]), _person("p3", ["grpA"])]
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "p1", "no"),   # rebel
            ("ev1", "p2", "yes"),
            ("ev1", "p3", "yes"),
        )
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_total"] == 1
        assert p1["rebelity_possible"] == 1
        assert p1["rebelity"] == 1.0

    def test_abstain_not_active_rebel(self):
        """Abstaining is not active rebellion (active=0, not -1)."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"])]
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "p1", "abstain"),
            ("ev1", "p2", "yes"),
        )
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_total"] == 0   # abstain is not active rebellion

    def test_tied_group_not_counted(self):
        """When group is tied (direction=0), no rebelity_possible increment."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"])]
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "p1", "yes"),
            ("ev1", "p2", "no"),
        )
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_possible"] == 0
        assert p1["rebelity"] is None

    def test_absent_mp_counted_in_possible(self):
        """MP absent: rebelity_possible still increments (group still had direction)."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"]), _person("p3", ["grpA"])]
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "p2", "yes"),
            ("ev1", "p3", "yes"),
            # p1 absent — no vote row at all
        )
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_possible"] == 1   # group voted clearly
        assert p1["rebelity_total"] == 0      # absence ≠ rebellion
        assert p1["rebelity"] == 0.0

    def test_no_group_rebelity_null(self):
        """MP with no group gets rebelity=None."""
        persons = [_person("p1")]   # no group
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(("ev1", "p1", "yes"))
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = rows[0]
        assert p1["rebelity_possible"] == 0
        assert p1["rebelity"] is None

    def test_invalid_events_excluded(self):
        """Vote events with status=invalid are excluded."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"])]
        events = [
            {"id": "ev1", "start_date": "2025-01-01", "status": "invalid"},
            {"id": "ev2", "start_date": "2025-01-02", "status": "valid"},
        ]
        votes = _votes(
            ("ev1", "p1", "no"), ("ev1", "p2", "yes"),
            ("ev2", "p1", "yes"), ("ev2", "p2", "yes"),
        )
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_possible"] == 1   # only ev2 counted
        assert p1["rebelity_total"] == 0


# ── Date filtering ─────────────────────────────────────────────────────────────

class TestDateFiltering:
    def test_since_filter(self):
        """Events before since are excluded."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"])]
        events = _events(("ev1", "2025-01-01"), ("ev2", "2025-06-01"))
        votes = _votes(
            ("ev1", "p1", "no"), ("ev1", "p2", "yes"),
            ("ev2", "p1", "yes"), ("ev2", "p2", "yes"),
        )
        defn = {**DEFINITION, "since": "2025-03-01"}
        rows = calculate_rebelity_govity(defn, events, votes, persons, None, None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_possible"] == 1   # only ev2
        assert p1["rebelity_total"] == 0

    def test_since_override(self):
        """CLI --since overrides definition since."""
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpA"])]
        events = _events(("ev1", "2025-01-01"), ("ev2", "2025-06-01"))
        votes = _votes(
            ("ev1", "p1", "no"), ("ev1", "p2", "yes"),
            ("ev2", "p1", "yes"), ("ev2", "p2", "yes"),
        )
        defn = {**DEFINITION, "since": "2024-01-01"}  # definition says include all
        rows = calculate_rebelity_govity(defn, events, votes, persons,
                                         since_override=date(2025, 3, 1), until_override=None)
        p1 = next(r for r in rows if r["person_id"] == "p1")
        assert p1["rebelity_possible"] == 1


# ── Govity ─────────────────────────────────────────────────────────────────────

class TestGovity:
    def _setup(self):
        """Two groups: gov (A, B) and opposition (C)."""
        persons = [
            _person("pA", ["org:gov"]),
            _person("pB", ["org:gov"]),
            _person("pC", ["org:opp"]),
        ]
        return persons

    def test_mp_always_with_gov(self):
        """pC always votes with government → govity=1."""
        persons = self._setup()
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "pA", "yes"),
            ("ev1", "pB", "yes"),
            ("ev1", "pC", "yes"),  # votes with gov
        )
        rows = calculate_rebelity_govity(DEFINITION_GOV, events, votes, persons, None, None)
        pC = next(r for r in rows if r["person_id"] == "pC")
        assert pC["govity_total"] == 1
        assert pC["govity_possible"] == 1
        assert pC["govity"] == 1.0

    def test_mp_always_against_gov(self):
        """pC always votes against government → govity=0."""
        persons = self._setup()
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "pA", "yes"),
            ("ev1", "pB", "yes"),
            ("ev1", "pC", "no"),  # actively against gov
        )
        rows = calculate_rebelity_govity(DEFINITION_GOV, events, votes, persons, None, None)
        pC = next(r for r in rows if r["person_id"] == "pC")
        assert pC["govity_total"] == 0
        assert pC["govity_possible"] == 1
        assert pC["govity"] == 0.0

    def test_abstain_counts_toward_govity(self):
        """Abstaining is 'not actively against' → counts as with-gov."""
        persons = self._setup()
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "pA", "yes"),
            ("ev1", "pB", "yes"),
            ("ev1", "pC", "abstain"),
        )
        rows = calculate_rebelity_govity(DEFINITION_GOV, events, votes, persons, None, None)
        pC = next(r for r in rows if r["person_id"] == "pC")
        assert pC["govity_total"] == 1   # abstain = present, not actively against

    def test_absent_not_in_govity_possible(self):
        """Absent MP is not counted in govity_possible."""
        persons = self._setup()
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "pA", "yes"),
            ("ev1", "pB", "yes"),
            # pC absent — no vote row
        )
        rows = calculate_rebelity_govity(DEFINITION_GOV, events, votes, persons, None, None)
        pC = next(r for r in rows if r["person_id"] == "pC")
        assert pC["govity_possible"] == 0
        assert pC["govity"] is None

    def test_no_gov_definition_no_govity_fields(self):
        """Without government definition, govity fields are absent."""
        persons = self._setup()
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(("ev1", "pA", "yes"), ("ev1", "pB", "yes"))
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        pC = next(r for r in rows if r["person_id"] == "pC")
        assert "govity" not in pC
        assert "govity_total" not in pC

    def test_gov_member_by_person_id(self):
        """government_members list (independents) is honoured."""
        defn = {**DEFINITION, "government_groups": [], "government_members": ["pA"]}
        persons = [_person("pA", ["org:ind"]), _person("pB", ["org:opp"])]
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(
            ("ev1", "pA", "yes"),
            ("ev1", "pB", "yes"),
        )
        rows = calculate_rebelity_govity(defn, events, votes, persons, None, None)
        pB = next(r for r in rows if r["person_id"] == "pB")
        assert pB["govity_total"] == 1
        assert pB["govity_possible"] == 1


# ── Output structure ───────────────────────────────────────────────────────────

class TestOutputStructure:
    def test_all_persons_returned(self):
        persons = [_person("p1", ["grpA"]), _person("p2", ["grpB"])]
        events = _events(("ev1", "2025-01-01"))
        votes = _votes(("ev1", "p1", "yes"), ("ev1", "p2", "no"))
        rows = calculate_rebelity_govity(DEFINITION, events, votes, persons, None, None)
        assert {r["person_id"] for r in rows} == {"p1", "p2"}

    def test_since_until_in_output(self):
        defn = {**DEFINITION, "since": "2025-01-01", "until": "2025-12-31"}
        persons = [_person("p1", ["grpA"])]
        rows = calculate_rebelity_govity(defn, [], [], persons, None, None)
        p1 = rows[0]
        assert p1["since"] == "2025-01-01"
        assert p1["until"] == "2025-12-31"

    def test_extras_image(self):
        persons = [_person("p1", ["grpA"], image="http://example.com/photo.jpg")]
        rows = calculate_rebelity_govity(DEFINITION, [], [], persons, None, None)
        assert rows[0]["extras"]["image"] == "http://example.com/photo.jpg"

    def test_organizations_in_output(self):
        persons = [{
            "id": "p1",
            "name": "Test Person",
            "memberships": {
                "groups": [{"id": "org:grpA", "name": "Group A",
                            "start_date": "2025-01-01", "end_date": None}],
            },
        }]
        rows = calculate_rebelity_govity(DEFINITION, [], [], persons, None, None)
        orgs = rows[0].get("organizations", [])
        assert any(o["id"] == "org:grpA" for o in orgs)
