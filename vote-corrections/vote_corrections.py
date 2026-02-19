#!/usr/bin/env python3
"""
Vote-corrections analysis: per member counts of announced voting corrections
and resulting vote-event invalidations.

Inputs (all named CLI parameters):
  --objections   path to vote-event-objections.dt.analyses JSON
  --votes        path to votes.csv (votes-table.dt format)
  --vote_events  path to vote-events.dt JSON
  --persons      path to all-members.dt.analyses JSON or CSV
  --output       path to write the output JSON

Optional filters:
  --since        ISO date (YYYY-MM-DD) — ignore vote events before this date
  --until        ISO date (YYYY-MM-DD) — ignore vote events after this date

Output (one row per person):
  person_id, name, given_names, family_names, organizations,
  corrections_total        — times the MP raised a vote_correction
  corrections_invalidated  — subset where the vote event was invalidated
  corrections_announced    — subset where it was only noted (outcome=announced)
  vote_events_total        — valid vote events the MP participated in
  since, until, extras
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

import jsonschema


# ── Schema paths ───────────────────────────────────────────────────────────────

_SCHEMA_BASE = Path(__file__).parent.parent.parent / "legislature-data-standard" / "dist"

SCHEMA_PATHS = {
    "objections":  _SCHEMA_BASE / "dt" / "latest" / "schemas" / "vote-event-objections.dt.json",
    "votes_row":   _SCHEMA_BASE / "dt" / "latest" / "schemas" / "votes-table.dt.json",
    "vote_events": _SCHEMA_BASE / "dt" / "latest" / "schemas" / "vote-events.dt.json",
    "persons":     _SCHEMA_BASE / "dt.analyses" / "all-members" / "latest" / "schemas" / "all-members.dt.analyses.json",
}


def load_schema(key: str) -> dict:
    path = SCHEMA_PATHS[key]
    with open(path) as f:
        return json.load(f)


# ── Loaders ────────────────────────────────────────────────────────────────────

def load_json_or_csv(path: str) -> list | dict:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        with open(p) as f:
            return json.load(f)
    elif suffix == ".csv":
        with open(p, newline="") as f:
            return list(csv.DictReader(f))
    else:
        raise ValueError(f"Unsupported file extension '{suffix}' for {path}. Expected .json or .csv")


def load_objections(path: str) -> list[dict]:
    data = load_json_or_csv(path)
    if not isinstance(data, list):
        sys.exit(f"objections file '{path}' must contain a JSON array")
    schema = load_schema("objections")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"objections file '{path}' failed schema validation: {e.message}")
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
    if not raw or raw.strip() in ("", "{}"):
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def load_persons(path: str) -> list[dict]:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                person = dict(row)
                for field in ("identifiers", "sources", "other_names"):
                    if field in person and person[field]:
                        try:
                            person[field] = json.loads(person[field])
                        except (json.JSONDecodeError, TypeError):
                            person[field] = []
                if "memberships" in person:
                    person["memberships"] = _parse_memberships_csv(person["memberships"])
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


# ── Date helpers ───────────────────────────────────────────────────────────────

def parse_date_prefix(s: str | None) -> date | None:
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
    if event_date is None:
        return True
    if since is not None and event_date < since:
        return False
    if until is not None and event_date > until:
        return False
    return True


# ── Core calculation ───────────────────────────────────────────────────────────

def calculate_vote_corrections(
    objections: list[dict],
    vote_events: list[dict],
    votes: list[dict],
    persons: list[dict],
    since_date: date | None,
    until_date: date | None,
) -> list[dict]:

    # Valid vote event IDs within the date range
    valid_event_ids: set[str] = set()
    for event in vote_events:
        status = event.get("status", "valid")
        if status in ("invalid", "test"):
            continue
        event_date = parse_date_prefix(event.get("start_date"))
        if in_date_range(event_date, since_date, until_date):
            valid_event_ids.add(event["id"])

    # vote_events_total per person: distinct valid event IDs the person voted in
    person_events: dict[str, set[str]] = {}
    for row in votes:
        vid = row["vote_event_id"]
        if vid not in valid_event_ids:
            continue
        pid = row["voter_id"]
        person_events.setdefault(pid, set()).add(vid)

    # Filter objections: only vote_correction type, by date range
    # Group by raised_by_id
    corrections: dict[str, dict] = {}  # pid -> {total, invalidated, announced}
    for obj in objections:
        if obj.get("type") != "vote_correction":
            continue
        pid = obj.get("raised_by_id")
        if not pid:
            continue
        obj_date = parse_date_prefix(obj.get("date"))
        if not in_date_range(obj_date, since_date, until_date):
            continue
        if pid not in corrections:
            corrections[pid] = {"total": 0, "invalidated": 0, "announced": 0}
        corrections[pid]["total"] += 1
        outcome = obj.get("outcome")
        if outcome == "invalidated":
            corrections[pid]["invalidated"] += 1
        elif outcome == "announced":
            corrections[pid]["announced"] += 1

    # Build output rows — one per person from the persons list
    output: list[dict] = []
    for person in persons:
        person_id = person["id"]
        c = corrections.get(person_id, {"total": 0, "invalidated": 0, "announced": 0})
        vote_events_total = len(person_events.get(person_id, set()))

        row: dict = {
            "person_id": person_id,
            "corrections_total":       c["total"],
            "corrections_invalidated": c["invalidated"],
            "corrections_announced":   c["announced"],
            "vote_events_total":       vote_events_total,
        }

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
                start = g.get("start_date")
                end   = g.get("end_date")
                if start:
                    org["since"] = start[:10]
                if end:
                    org["until"] = end[:10]
                orgs.append(org)
        if orgs:
            row["organizations"] = orgs

        if since_date is not None:
            row["since"] = since_date.isoformat()
        if until_date is not None:
            row["until"] = until_date.isoformat()

        extras: dict = {}
        if person.get("image"):
            extras["image"] = person["image"]
        if extras:
            row["extras"] = extras

        output.append(row)

    return output


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate vote-correction counts per member."
    )
    parser.add_argument("--objections",  required=True, help="Path to vote-event-objections JSON")
    parser.add_argument("--votes",       required=True, help="Path to votes CSV or JSON")
    parser.add_argument("--vote_events", required=True, help="Path to vote-events JSON")
    parser.add_argument("--persons",     required=True, help="Path to all-members JSON or CSV")
    parser.add_argument("--output",      required=True, help="Path to write output JSON")
    parser.add_argument("--since",       default=None,  help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--until",       default=None,  help="End date filter (YYYY-MM-DD)")
    args = parser.parse_args()

    since_date = parse_date_prefix(args.since)
    until_date = parse_date_prefix(args.until)

    print("Loading and validating objections...", file=sys.stderr)
    objections = load_objections(args.objections)

    print("Loading and validating vote_events...", file=sys.stderr)
    vote_events = load_vote_events(args.vote_events)

    print("Loading and validating votes...", file=sys.stderr)
    votes = load_votes(args.votes)

    print("Loading and validating persons...", file=sys.stderr)
    persons = load_persons(args.persons)

    print("Calculating vote corrections...", file=sys.stderr)
    output = calculate_vote_corrections(
        objections, vote_events, votes, persons, since_date, until_date
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Done. Wrote {len(output)} records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
