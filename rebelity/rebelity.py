#!/usr/bin/env python3
"""
Rebelity analysis: per-member rate of voting against own group's majority.

Inputs (all named CLI parameters):
  --definition   path to rebelity-definition.dt.analyses JSON
  --votes        path to votes.csv (votes-table.dt format)
  --vote_events  path to vote-events.dt JSON
  --persons      path to all-members.dt.analyses JSON or CSV
  --output       path to write the rebelity.dt.analyses output JSON

Optional:
  --since        ISO date (YYYY-MM-DD) — overrides definition's since
  --until        ISO date (YYYY-MM-DD) — overrides definition's until

Output (one row per person):
  person_id, name, given_names, family_names, organizations,
  rebelity_total, rebelity_possible, rebelity,
  since, until, extras

Vote semantics (from definition):
  yes_options     → vote_value = +1, active = +1
  no_options      → vote_value = -1, active = -1
  other present   → vote_value = -1 (counts against for direction), active = 0
  absent_options  → vote_value =  0, not present

Group direction = sign(sum of vote_values for group members in that event).
Rebelity denominator = vote events where group had a clear direction (≠ 0),
  regardless of whether the MP was present.
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
    "definition":  _SCHEMA_BASE / "dt.analyses" / "rebelity-definition" / "latest" / "schemas" / "rebelity-definition.dt.analyses.json",
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
        raise ValueError(f"Unsupported extension '{suffix}' for {path}")


def load_definition(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    schema = load_schema("definition")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"Definition '{path}' failed schema validation: {e.message}")
    return data


def load_vote_events(path: str) -> list[dict]:
    data = load_json_or_csv(path)
    if not isinstance(data, list):
        sys.exit(f"vote_events '{path}' must be a JSON array")
    schema = load_schema("vote_events")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"vote_events '{path}' failed schema validation: {e.message}")
    return data


def load_votes(path: str) -> list[dict]:
    data = load_json_or_csv(path)
    if not isinstance(data, list):
        sys.exit(f"votes '{path}' must be a list/array")
    row_schema = load_schema("votes_row")
    for i, row in enumerate(data):
        try:
            jsonschema.validate(instance=dict(row), schema=row_schema)
        except jsonschema.ValidationError as e:
            sys.exit(f"votes '{path}' row {i} failed schema validation: {e.message}")
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
            rows = []
            for row in csv.DictReader(f):
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
        sys.exit(f"persons '{path}' must be an array")
    schema = load_schema("persons")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"persons '{path}' failed schema validation: {e.message}")
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


def in_date_range(d: date | None, since: date | None, until: date | None) -> bool:
    if d is None:
        return True
    if since is not None and d < since:
        return False
    if until is not None and d > until:
        return False
    return True


# ── Group membership lookup ────────────────────────────────────────────────────

def build_group_memberships(persons: list[dict]) -> dict[str, list[tuple]]:
    """Returns {person_id: [(group_id, start_date, end_date), ...]} sorted by start desc."""
    result: dict[str, list[tuple]] = {}
    for p in persons:
        pid = p.get("id") or p.get("person_id", "")
        groups = (p.get("memberships") or {}).get("groups") or []
        entries = []
        for g in groups:
            gid = g.get("id")
            if not gid:
                continue
            entries.append((gid, parse_date_prefix(g.get("start_date")), parse_date_prefix(g.get("end_date"))))
        entries.sort(key=lambda t: t[1] or date.min, reverse=True)
        result[pid] = entries
    return result


def get_group_at_date(person_id: str, event_date: date | None,
                      group_memberships: dict[str, list[tuple]]) -> str | None:
    for (gid, start, end) in group_memberships.get(person_id, []):
        if event_date is not None:
            if start is not None and event_date < start:
                continue
            if end is not None and event_date > end:
                continue
        return gid
    return None


# ── Vote value helpers ─────────────────────────────────────────────────────────

def vote_value(option: str, yes_opts: set[str], no_opts: set[str], present_opts: set[str]) -> int:
    """
    +1 for yes, -1 for no or other-present (abstain), 0 for absent.
    Abstaining counts against for group direction purposes.
    """
    if option in yes_opts:
        return 1
    if option in no_opts:
        return -1
    if option in present_opts:
        return -1
    return 0


def vote_value_active(option: str, yes_opts: set[str], no_opts: set[str]) -> int:
    """Active vote: +1 yes, -1 no, 0 anything else."""
    if option in yes_opts:
        return 1
    if option in no_opts:
        return -1
    return 0


# ── Core calculation ───────────────────────────────────────────────────────────

def calculate_rebelity(
    definition: dict,
    vote_events: list[dict],
    votes: list[dict],
    persons: list[dict],
    since_override: date | None,
    until_override: date | None,
) -> list[dict]:

    since_date = since_override or parse_date_prefix(definition.get("since"))
    until_date = until_override or parse_date_prefix(definition.get("until"))
    present_opts = set(definition["present_options"])
    yes_opts = set(definition["yes_options"])
    no_opts  = set(definition["no_options"])

    # Filter valid vote events in date range
    valid_events: dict[str, date | None] = {}
    for ev in vote_events:
        if ev.get("status", "valid") in ("invalid", "test"):
            continue
        ev_date = parse_date_prefix(ev.get("start_date"))
        if in_date_range(ev_date, since_date, until_date):
            valid_events[ev["id"]] = ev_date

    # Index votes by event and by person
    votes_by_event: dict[str, list[tuple[str, str]]] = {}
    person_vote: dict[str, dict[str, str]] = {}
    for row in votes:
        eid = row["vote_event_id"]
        if eid not in valid_events:
            continue
        pid, opt = row["voter_id"], row["option"]
        votes_by_event.setdefault(eid, []).append((pid, opt))
        person_vote.setdefault(pid, {})[eid] = opt

    group_memberships = build_group_memberships(persons)

    # Compute group direction per (event, group)
    group_direction: dict[tuple[str, str], int] = {}
    for eid, ev_date in valid_events.items():
        group_sums: dict[str, int] = {}
        for (pid, opt) in votes_by_event.get(eid, []):
            val = vote_value(opt, yes_opts, no_opts, present_opts)
            gid = get_group_at_date(pid, ev_date, group_memberships)
            if gid:
                group_sums[gid] = group_sums.get(gid, 0) + val
        for gid, s in group_sums.items():
            group_direction[(eid, gid)] = 1 if s > 0 else (-1 if s < 0 else 0)

    # Build output
    output: list[dict] = []
    for person in persons:
        pid = person.get("id") or person.get("person_id", "")
        rebelity_total = 0
        rebelity_possible = 0
        p_votes = person_vote.get(pid, {})

        for eid, ev_date in valid_events.items():
            gid = get_group_at_date(pid, ev_date, group_memberships)
            if not gid:
                continue
            gdir = group_direction.get((eid, gid), 0)
            if gdir == 0:
                continue
            rebelity_possible += 1
            opt = p_votes.get(eid)
            if opt is not None:
                active = vote_value_active(opt, yes_opts, no_opts)
                if active * gdir == -1:
                    rebelity_total += 1

        row: dict = {
            "person_id":         pid,
            "rebelity_total":    rebelity_total,
            "rebelity_possible": rebelity_possible,
            "rebelity":          round(rebelity_total / rebelity_possible, 6) if rebelity_possible > 0 else None,
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
        for classification, key in [("group", "groups"), ("candidate_list", "candidate_list"), ("constituency", "constituency")]:
            for g in (memberships.get(key) or []):
                if not g.get("id"):
                    continue
                org: dict = {"id": g["id"], "classification": classification}
                if g.get("name"):
                    org["name"] = g["name"]
                if g.get("start_date"):
                    org["since"] = g["start_date"][:10]
                if g.get("end_date"):
                    org["until"] = g["end_date"][:10]
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--definition",  required=True)
    parser.add_argument("--votes",       required=True)
    parser.add_argument("--vote_events", required=True)
    parser.add_argument("--persons",     required=True)
    parser.add_argument("--output",      required=True)
    parser.add_argument("--since",       default=None)
    parser.add_argument("--until",       default=None)
    args = parser.parse_args()

    since_override = parse_date_prefix(args.since)
    until_override = parse_date_prefix(args.until)

    print("Loading definition...",  file=sys.stderr)
    definition = load_definition(args.definition)
    print("Loading vote_events...", file=sys.stderr)
    vote_events = load_vote_events(args.vote_events)
    print("Loading votes...",       file=sys.stderr)
    votes = load_votes(args.votes)
    print("Loading persons...",     file=sys.stderr)
    persons = load_persons(args.persons)
    print("Calculating...",         file=sys.stderr)
    output = calculate_rebelity(definition, vote_events, votes, persons, since_override, until_override)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Done. Wrote {len(output)} records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
