#!/usr/bin/env python3
"""
Convert vote-corrections analysis JSON to a Flourish-ready CSV table.

Columns: id, name, photo, candidate_list, group, constituency,
         corrections_total, corrections_invalidated, corrections_announced,
         vote_events_total, correction_rate

Usage:
    python output_flourish_table.py --input path/to/vote_corrections.json --output path/to/table.csv
"""

import argparse
import csv
import json
import sys


def newest_name(organizations: list[dict], classification: str) -> str:
    matches = [o for o in organizations if o.get("classification") == classification]
    if not matches:
        return ""
    matches.sort(key=lambda o: o.get("since") or "", reverse=True)
    return matches[0].get("name") or ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert vote-corrections JSON to a Flourish-ready CSV."
    )
    parser.add_argument("--input",  required=True, help="Path to vote-corrections JSON")
    parser.add_argument("--output", required=True, help="Path to write output CSV")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    fieldnames = [
        "id",
        "name",
        "photo",
        "candidate_list",
        "group",
        "constituency",
        "corrections_total",
        "corrections_invalidated",
        "corrections_announced",
        "vote_events_total",
        "correction_rate",
    ]

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            orgs = row.get("organizations") or []
            total = row["corrections_total"]
            vote_total = row["vote_events_total"]
            correction_rate = round(total / vote_total, 6) if vote_total > 0 else ""
            writer.writerow({
                "id":                     row["person_id"],
                "name":                   row.get("name") or "",
                "photo":                  (row.get("extras") or {}).get("image") or "",
                "candidate_list":         newest_name(orgs, "candidate_list"),
                "group":                  newest_name(orgs, "group"),
                "constituency":           newest_name(orgs, "constituency"),
                "corrections_total":      total,
                "corrections_invalidated": row["corrections_invalidated"],
                "corrections_announced":  row["corrections_announced"],
                "vote_events_total":      vote_total,
                "correction_rate":        correction_rate,
            })

    print(f"Wrote {len(data)} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
