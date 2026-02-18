#!/usr/bin/env python3
"""
Convert attendance.dt.analyses JSON to a Flourish-ready CSV table.

Columns: id, name, candidate_list, group, constituency,
         present_share, present_share_percent, vote_events_total, present, absent

Usage:
    python output_flourish_table.py --input path/to/attendance.json --output path/to/table.csv
"""

import argparse
import csv
import json
import sys


def newest_name(organizations: list[dict], classification: str) -> str:
    """Return the name of the most recently started org of the given classification."""
    matches = [o for o in organizations if o.get("classification") == classification]
    if not matches:
        return ""
    # Sort by since descending; entries without a date treated as oldest
    matches.sort(key=lambda o: o.get("since") or "", reverse=True)
    return matches[0].get("name") or ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert attendance JSON to a Flourish-ready CSV."
    )
    parser.add_argument("--input",  required=True, help="Path to attendance.dt.analyses JSON")
    parser.add_argument("--output", required=True, help="Path to write output CSV")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    fieldnames = [
        "id",
        "name",
        "candidate_list",
        "group",
        "constituency",
        "present_share",
        "present_share_percent",
        "vote_events_total",
        "present",
        "absent",
    ]

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            orgs = row.get("organizations") or []
            ps = row.get("present_share")
            writer.writerow({
                "id":                   row["person_id"],
                "name":                 row.get("name") or "",
                "candidate_list":       newest_name(orgs, "candidate_list"),
                "group":                newest_name(orgs, "group"),
                "constituency":         newest_name(orgs, "constituency"),
                "present_share":        ps if ps is not None else "",
                "present_share_percent": round(ps * 100) if ps is not None else "",
                "vote_events_total":    row["vote_events_total"],
                "present":              row["present"],
                "absent":               row["absent"],
            })

    print(f"Wrote {len(data)} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
