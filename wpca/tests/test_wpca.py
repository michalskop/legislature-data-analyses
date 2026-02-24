"""
Tests for the WPCA analysis.

Run with:
    pytest wpca/tests/
or from the repo root:
    python -m pytest wpca/tests/
"""

import csv
import io
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ── Path constants ─────────────────────────────────────────────────────────────

REPO_ROOT      = Path(__file__).parent.parent.parent.parent   # legislature-data/
WPCA_SCRIPT    = Path(__file__).parent.parent / "wpca.py"

# Paths to real test data (CZ PSP 2025-202x) — tests are skipped if absent
_LEGISLATURE      = REPO_ROOT / "legislatures" / "cz-psp-data-2025-202x"
_STANDARD_DIST    = REPO_ROOT / "legislature-data-standard" / "dist"

REAL_VOTES        = _LEGISLATURE / "work" / "standard" / "votes.csv"
REAL_VOTE_EVENTS  = _LEGISLATURE / "work" / "standard" / "vote_events.json"
REAL_PERSONS      = _LEGISLATURE / "analyses" / "all-members" / "outputs" / "all_members.json"

OUTPUT_SCHEMA_PATH      = _STANDARD_DIST / "dt.analyses" / "wpca" / "latest" / "schemas" / "wpca.dt.analyses.json"
OUTPUT_TIME_SCHEMA_PATH = _STANDARD_DIST / "dt.analyses" / "wpca-time" / "latest" / "schemas" / "wpca-time.dt.analyses.json"

real_data_available = (
    REAL_VOTES.exists() and REAL_VOTE_EVENTS.exists() and REAL_PERSONS.exists()
)
schemas_available = OUTPUT_SCHEMA_PATH.exists()


# ── Minimal synthetic fixtures ─────────────────────────────────────────────────

MINIMAL_DEFINITION = {
    "lo_limit": 0.1,
    "yes_options": ["yes"],
    "no_options": ["no", "abstain"],
    "absent_options": ["absent"],
}

MINIMAL_VOTES = [
    # vote_event_id, voter_id, option
    {"vote_event_id": "ve1", "voter_id": "p1", "option": "yes"},
    {"vote_event_id": "ve1", "voter_id": "p2", "option": "no"},
    {"vote_event_id": "ve1", "voter_id": "p3", "option": "yes"},
    {"vote_event_id": "ve2", "voter_id": "p1", "option": "no"},
    {"vote_event_id": "ve2", "voter_id": "p2", "option": "yes"},
    {"vote_event_id": "ve2", "voter_id": "p3", "option": "no"},
    {"vote_event_id": "ve3", "voter_id": "p1", "option": "yes"},
    {"vote_event_id": "ve3", "voter_id": "p2", "option": "no"},
    {"vote_event_id": "ve3", "voter_id": "p3", "option": "absent"},
]

MINIMAL_VOTE_EVENTS = [
    {"id": "ve1", "start_date": "2024-01-15"},
    {"id": "ve2", "start_date": "2024-02-20"},
    {"id": "ve3", "start_date": "2024-03-10"},
]

MINIMAL_PERSONS = [
    {
        "id": "p1",
        "name": "Alice Smith",
        "given_names": ["Alice"],
        "family_names": ["Smith"],
    },
    {
        "id": "p2",
        "name": "Bob Jones",
        "given_names": ["Bob"],
        "family_names": ["Jones"],
    },
    {
        "id": "p3",
        "name": "Carol White",
        "given_names": ["Carol"],
        "family_names": ["White"],
    },
]


def _write_votes_csv(votes: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["vote_event_id", "voter_id", "option"])
        writer.writeheader()
        writer.writerows(votes)


def run_script(
    definition: dict,
    votes: list[dict],
    vote_events: list[dict],
    persons: list[dict],
    extra_args: list[str] | None = None,
) -> tuple[int, str, str, list[dict] | None]:
    """Run wpca.py with synthetic data; return (returncode, stdout, stderr, output_json)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        def_path    = tmp / "definition.json"
        votes_path  = tmp / "votes.csv"
        ve_path     = tmp / "vote_events.json"
        pers_path   = tmp / "persons.json"
        out_path    = tmp / "output.json"

        def_path.write_text(json.dumps(definition))
        _write_votes_csv(votes, votes_path)
        ve_path.write_text(json.dumps(vote_events))
        pers_path.write_text(json.dumps(persons))

        cmd = [
            sys.executable, str(WPCA_SCRIPT),
            "--definition",  str(def_path),
            "--votes",       str(votes_path),
            "--vote-events", str(ve_path),
            "--persons",     str(pers_path),
            "--output",      str(out_path),
            *(extra_args or []),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        output_data = None
        if out_path.exists():
            with open(out_path) as f:
                output_data = json.load(f)

        return result.returncode, result.stdout, result.stderr, output_data


# ── Unit tests for internal functions ──────────────────────────────────────────

def test_encode_option_import():
    from wpca.wpca import encode_option
    assert encode_option("yes", ["yes"], ["no"], ["absent"]) == 1.0
    assert encode_option("no", ["yes"], ["no"], ["absent"]) == -1.0
    assert encode_option("absent", ["yes"], ["no"], ["absent"]) is None
    assert encode_option("unknown", ["yes"], ["no"], ["absent"]) is None


def test_generate_periods_half_year():
    from wpca.wpca import generate_periods
    from datetime import date as d
    periods = generate_periods(d(2024, 3, 1), d(2024, 9, 15), "half-year")
    assert len(periods) == 2
    assert periods[0] == (d(2024, 1, 1), d(2024, 6, 30), 0)
    assert periods[1] == (d(2024, 7, 1), d(2024, 12, 31), 1)


def test_generate_periods_quarter():
    from wpca.wpca import generate_periods
    from datetime import date as d
    periods = generate_periods(d(2024, 1, 5), d(2024, 6, 30), "quarter")
    assert len(periods) == 2
    assert periods[0][0] == d(2024, 1, 1)
    assert periods[1][0] == d(2024, 4, 1)


def test_generate_periods_year():
    from wpca.wpca import generate_periods
    from datetime import date as d
    periods = generate_periods(d(2022, 6, 1), d(2024, 3, 1), "year")
    assert len(periods) == 3
    assert [p[2] for p in periods] == [0, 1, 2]


def test_period_label():
    from wpca.wpca import period_label
    from datetime import date as d
    assert period_label(d(2024, 1, 1), d(2024, 6, 30), "half-year") == "1. pol. 2024"
    assert period_label(d(2024, 7, 1), d(2024, 12, 31), "half-year") == "2. pol. 2024"
    assert period_label(d(2024, 4, 1), d(2024, 6, 30), "quarter")   == "Q2 2024"
    assert period_label(d(2023, 1, 1), d(2023, 12, 31), "year")      == "2023"


def test_run_wpca_basic():
    """WPCA should return one row per voter with n_dims coordinates."""
    import numpy as np
    import pandas as pd
    from wpca.wpca import run_wpca

    data = {
        "p1": {"ve1": 1.0,  "ve2": -1.0, "ve3": 1.0},
        "p2": {"ve1": -1.0, "ve2": 1.0,  "ve3": -1.0},
        "p3": {"ve1": 1.0,  "ve2": 1.0,  "ve3": float("nan")},
    }
    Xraw = pd.DataFrame(data).T   # voter × vote_event
    Xraw = Xraw.T                 # vote_event × voter

    Xproju_df, eigvecs, Z, pw, w1w2 = run_wpca(Xraw, n_dims=2)

    assert Xproju_df.shape == (3, 2), "One row per voter, two columns for n_dims=2"
    assert set(Xproju_df.index) == {"p1", "p2", "p3"}
    assert not any(math.isnan(v) for v in pw.values)


def test_apply_rotation():
    """Rotation should flip dim signs so the reference person is positive."""
    import pandas as pd
    from wpca.wpca import apply_rotation

    df = pd.DataFrame({"dim1": [-1.0, 0.5], "dim2": [0.3, -0.2]}, index=["ref", "other"])
    rotated = apply_rotation(df, {"voter_id": "ref", "dims": [1, 1]})
    # ref had dim1=-1.0 → should be flipped to +1.0
    assert rotated.loc["ref", "dim1"] > 0
    # ref dim2 was already positive → no flip
    assert rotated.loc["ref", "dim2"] > 0


# ── Integration tests ──────────────────────────────────────────────────────────

def test_minimal_run_succeeds():
    """Script should exit 0 with minimal synthetic data."""
    rc, stdout, stderr, output = run_script(
        MINIMAL_DEFINITION, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS
    )
    assert rc == 0, f"Script failed:\nstdout: {stdout}\nstderr: {stderr}"
    assert output is not None
    assert isinstance(output, list)
    assert len(output) == 3   # one row per voter


def test_output_fields():
    """Each output record must have person_id, dims, weight, included."""
    _, _, _, output = run_script(
        MINIMAL_DEFINITION, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS
    )
    for r in output:
        assert "person_id" in r
        assert "dims" in r
        assert isinstance(r["dims"], list)
        assert len(r["dims"]) == 3   # default n_dims
        assert "weight" in r
        assert "included" in r
        assert isinstance(r["included"], bool)


def test_n_dims_respected():
    """n_dims in definition must control length of dims array."""
    defn = {**MINIMAL_DEFINITION, "n_dims": 2}
    _, _, _, output = run_script(
        defn, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS
    )
    for r in output:
        assert len(r["dims"]) == 2


def test_lo_limit_filters_included():
    """Persons below lo_limit must have included=False."""
    defn = {**MINIMAL_DEFINITION, "lo_limit": 0.99}
    _, _, _, output = run_script(
        defn, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS
    )
    assert any(not r["included"] for r in output), "Expected at least one excluded person"


def test_rotation_reference_in_positive_dim():
    """After rotation the reference person should have a positive dim1 coordinate."""
    defn = {
        **MINIMAL_DEFINITION,
        "rotate": {"voter_id": "p1", "dims": [1, 1, 1]},
    }
    _, _, _, output = run_script(
        defn, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS
    )
    p1 = next(r for r in output if r["person_id"] == "p1")
    assert p1["dims"][0] is None or p1["dims"][0] > 0, \
        f"p1 dim1 should be positive after rotation, got {p1['dims'][0]}"


def test_date_filter():
    """since/until in definition should exclude vote events outside the range."""
    defn = {**MINIMAL_DEFINITION, "since": "2024-02-01", "until": "2024-02-28"}
    rc, stdout, stderr, output = run_script(
        defn, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS
    )
    assert rc == 0, f"Script failed:\nstderr: {stderr}"
    # Only ve2 is in Feb 2024 — we should still get output (albeit from 1 event)
    assert output is not None


def test_time_interval_output():
    """--output-time with time_interval='half-year' should produce per-period rows."""
    defn = {**MINIMAL_DEFINITION, "time_interval": "half-year"}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        time_out = tmp / "time_output.json"

        rc, stdout, stderr, _ = run_script(
            defn, MINIMAL_VOTES, MINIMAL_VOTE_EVENTS, MINIMAL_PERSONS,
            extra_args=["--output-time", str(time_out)],
        )
        assert rc == 0, f"Script failed:\nstderr: {stderr}"
        assert time_out.exists(), "Time output file was not created"

        with open(time_out) as f:
            time_data = json.load(f)

        assert isinstance(time_data, list)
        assert len(time_data) > 0

        for row in time_data:
            assert "person_id" in row
            assert "period_index" in row
            assert "period_start" in row
            assert "period_end" in row
            assert "dims" in row
            assert isinstance(row["dims"], list)
            assert "included" in row


def test_missing_required_arg_fails():
    """Script must exit non-zero when a required argument is missing."""
    result = subprocess.run(
        [sys.executable, str(WPCA_SCRIPT), "--votes", "x.csv"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


# ── Real-data tests (skipped if data not available) ───────────────────────────

@pytest.mark.skipif(not real_data_available, reason="Real legislature data not available")
@pytest.mark.skipif(not schemas_available, reason="Built schemas not available (run npm run build:schemas first)")
def test_real_data_run():
    """Script should succeed and validate output against the published schema."""
    import jsonschema as jschema

    definition = {
        "lo_limit": 0.1,
        "yes_options": ["yes"],
        "no_options": ["no", "abstain"],
        "absent_options": ["absent", "before oath", "not voting"],
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        def_path = tmp / "definition.json"
        out_path = tmp / "wpca.json"
        def_path.write_text(json.dumps(definition))

        result = subprocess.run(
            [
                sys.executable, str(WPCA_SCRIPT),
                "--definition",  str(def_path),
                "--votes",       str(REAL_VOTES),
                "--vote-events", str(REAL_VOTE_EVENTS),
                "--persons",     str(REAL_PERSONS),
                "--output",      str(out_path),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, \
            f"Script failed on real data:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert out_path.exists()

        with open(out_path) as f:
            output = json.load(f)

        schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
        jschema.validate(instance=output, schema=schema)

        assert len(output) > 0
        included = [r for r in output if r["included"]]
        assert len(included) > 0
