#!/usr/bin/env python3
"""
Attendance analysis: calculates attendance (presence at voting) per member.

Inputs (all named CLI parameters):
  --definition   path to attendance-definition.dt.analyses JSON
  --votes        path to votes.csv (votes-table.dt format)
  --vote_events  path to vote-events.dt JSON
  --persons      path to all-members.dt.analyses JSON or CSV
  --output       path to write the attendance.dt.analyses output JSON
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

import jsonschema


# ── Schema paths ──────────────────────────────────────────────────────────────

_SCHEMA_BASE = Path(__file__).parent.parent.parent / "legislature-data-standard" / "dist"

SCHEMA_PATHS = {
    "definition": _SCHEMA_BASE / "dt.analyses" / "attendance-definition" / "latest" / "schemas" / "attendance-definition.dt.analyses.json",
    "votes_row":  _SCHEMA_BASE / "dt" / "latest" / "schemas" / "votes-table.dt.json",
    "vote_events": _SCHEMA_BASE / "dt" / "latest" / "schemas" / "vote-events.dt.json",
    "persons":    _SCHEMA_BASE / "dt.analyses" / "all-members" / "latest" / "schemas" / "all-members.dt.analyses.json",
    "output":     _SCHEMA_BASE / "dt.analyses" / "attendance" / "latest" / "schemas" / "attendance.dt.analyses.json",
}


def load_schema(key: str) -> dict:
    path = SCHEMA_PATHS[key]
    with open(path) as f:
        return json.load(f)


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_json_or_csv(path: str) -> list | dict:
    """Load a file as JSON or CSV based on extension."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        with open(p) as f:
            return json.load(f)
    elif suffix == ".csv":
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    else:
        raise ValueError(f"Unsupported file extension '{suffix}' for {path}. Expected .json or .csv")


def load_definition(path: str) -> dict:
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise ValueError(f"Definition file must be JSON, got: {path}")
    with open(p) as f:
        data = json.load(f)
    schema = load_schema("definition")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"Definition file '{path}' failed schema validation: {e.message}")
    return data


def load_vote_events(path: str) -> list[dict]:
    data = load_json_or_csv(path)
    if not isinstance(data, list):
        sys.exit(f"vote_events file '{path}' must contain a JSON array")
    schema = load_schema("vote_events")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"vote_events file '{path}' failed schema validation: {e.message}")
    return data


def load_votes(path: str) -> list[dict]:
    """Load votes from CSV (or JSON). Validates each row against votes-table schema."""
    data = load_json_or_csv(path)
    if not isinstance(data, list):
        sys.exit(f"votes file '{path}' must be a list/array of rows")
    row_schema = load_schema("votes_row")
    for i, row in enumerate(data):
        try:
            jsonschema.validate(instance=dict(row), schema=row_schema)
        except jsonschema.ValidationError as e:
            sys.exit(f"votes file '{path}' row {i} failed schema validation: {e.message}")
    return data


def _parse_memberships_csv(raw: str) -> dict:
    """Parse memberships field from CSV (stored as JSON string)."""
    if not raw or raw.strip() in ("", "{}"):
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def load_persons(path: str) -> list[dict]:
    """Load persons from JSON or CSV (all-members.dt.analyses format)."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                person = dict(row)
                # Parse JSON-encoded fields
                for field in ("identifiers", "sources", "other_names"):
                    if field in person and person[field]:
                        try:
                            person[field] = json.loads(person[field])
                        except (json.JSONDecodeError, TypeError):
                            person[field] = []
                if "memberships" in person:
                    person["memberships"] = _parse_memberships_csv(person["memberships"])
                # Clean empty strings to None
                for k, v in person.items():
                    if v == "":
                        person[k] = None
                rows.append(person)
        data = rows
    else:
        with open(p) as f:
            data = json.load(f)

    if not isinstance(data, list):
        sys.exit(f"persons file '{path}' must contain an array of persons")

    schema = load_schema("persons")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"persons file '{path}' failed schema validation: {e.message}")
    return data


# ── Date helpers ──────────────────────────────────────────────────────────────

def parse_date_prefix(s: str | None) -> date | None:
    """Extract a date from an ISO date or datetime string, or return None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def in_date_range(event_date: date | None, since: date | None, until: date | None) -> bool:
    """Check whether event_date falls within [since, until] (inclusive, open bounds = no limit)."""
    if event_date is None:
        # No date info: include (don't exclude on missing data)
        return True
    if since is not None and event_date < since:
        return False
    if until is not None and event_date > until:
        return False
    return True


# ── Core calculation ──────────────────────────────────────────────────────────

def calculate_attendance(definition: dict, vote_events: list[dict], votes: list[dict], persons: list[dict]) -> list[dict]:
    """Compute attendance for each person and return the output array."""

    since_date = parse_date_prefix(definition.get("since"))
    until_date = parse_date_prefix(definition.get("until"))
    present_options = set(definition["present_options"])
    absent_options = set(definition["absent_options"])

    # Filter vote events: only valid ones within the date range
    filtered_event_ids: set[str] = set()
    for event in vote_events:
        status = event.get("status", "valid")
        if status in ("invalid", "test"):
            continue
        event_date = parse_date_prefix(event.get("start_date"))
        if in_date_range(event_date, since_date, until_date):
            filtered_event_ids.add(event["id"])

    # Build per-person lookup from votes table
    # person_id -> {present, absent, total (distinct vote_event_ids seen)}
    counts: dict[str, dict] = {}
    for row in votes:
        vid = row["vote_event_id"]
        if vid not in filtered_event_ids:
            continue
        person_id = row["voter_id"]
        option = row["option"]
        if person_id not in counts:
            counts[person_id] = {"present": 0, "absent": 0, "events": set()}
        counts[person_id]["events"].add(vid)
        if option in present_options:
            counts[person_id]["present"] += 1
        elif option in absent_options:
            counts[person_id]["absent"] += 1
        # options not in either set are silently ignored in the count

    # Build output rows
    output: list[dict] = []
    for person in persons:
        person_id = person["id"]
        c = counts.get(person_id, {"present": 0, "absent": 0, "events": set()})
        present = c["present"]
        absent = c["absent"]
        # vote_events_total = how many vote events this person appears in (any option)
        vote_events_total = len(c["events"])
        present_share = (present / vote_events_total) if vote_events_total > 0 else None

        row: dict = {
            "person_id": person_id,
            "vote_events_total": vote_events_total,
            "present": present,
            "absent": absent,
        }

        # Optional name fields
        if person.get("name"):
            row["name"] = person["name"]
        if person.get("given_names") or person.get("given_name"):
            given = person.get("given_names") or [person["given_name"]]
            if isinstance(given, str):
                given = [g.strip() for g in given.split(",") if g.strip()]
            if given:
                row["given_names"] = given
        if person.get("family_names") or person.get("family_name"):
            family = person.get("family_names") or [person["family_name"]]
            if isinstance(family, str):
                family = [f.strip() for f in family.split(",") if f.strip()]
            if family:
                row["family_names"] = family

        # Organizations from all membership types (groups, candidate_list, constituency)
        memberships = person.get("memberships") or {}
        orgs = []
        for classification, key in [
            ("group",          "groups"),
            ("candidate_list", "candidate_list"),
            ("constituency",   "constituency"),
        ]:
            for g in (memberships.get(key) or []):
                if not g.get("id"):
                    continue
                org: dict = {"id": g["id"], "classification": classification}
                if g.get("name"):
                    org["name"] = g["name"]
                # Map start_date/end_date → since/until (date portion only; skip if empty)
                start = g.get("start_date")
                end   = g.get("end_date")
                if start:
                    org["since"] = start[:10]
                if end:
                    org["until"] = end[:10]
                orgs.append(org)
        if orgs:
            row["organizations"] = orgs

        # Date range
        if definition.get("since") is not None:
            row["since"] = definition["since"]
        if definition.get("until") is not None:
            row["until"] = definition["until"]

        if present_share is not None:
            row["present_share"] = round(present_share, 10)

        if person.get("image"):
            row["extras"] = {"image": person["image"]}

        output.append(row)

    return output


# ── Validation ────────────────────────────────────────────────────────────────

def validate_output(data: list[dict]) -> None:
    schema = load_schema("output")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"Output failed schema validation: {e.message}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate attendance from vote data for each member."
    )
    parser.add_argument("--definition",  required=True, help="Path to attendance-definition JSON")
    parser.add_argument("--votes",       required=True, help="Path to votes CSV or JSON")
    parser.add_argument("--vote_events", required=True, help="Path to vote-events JSON")
    parser.add_argument("--persons",     required=True, help="Path to all-members JSON or CSV")
    parser.add_argument("--output",      required=True, help="Path to write output JSON")
    args = parser.parse_args()

    print("Loading and validating definition...", file=sys.stderr)
    definition = load_definition(args.definition)

    print("Loading and validating vote_events...", file=sys.stderr)
    vote_events = load_vote_events(args.vote_events)

    print("Loading and validating votes...", file=sys.stderr)
    votes = load_votes(args.votes)

    print("Loading and validating persons...", file=sys.stderr)
    persons = load_persons(args.persons)

    print("Calculating attendance...", file=sys.stderr)
    output = calculate_attendance(definition, vote_events, votes, persons)

    print("Validating output...", file=sys.stderr)
    validate_output(output)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Done. Wrote {len(output)} attendance records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
