#!/usr/bin/env python3
"""
Convert govity.dt.analyses JSON to a Flourish-ready CSV table.

Columns: id, name, photo, candidate_list, group, constituency,
         govity, govity_percent, govity_total, govity_possible

Usage:
    python output_flourish_table.py --input path/to/govity.json --output path/to/table.csv
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
    matches.sort(key=lambda o: o.get("since") or "", reverse=True)
    return matches[0].get("name") or ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert govity JSON to a Flourish-ready CSV."
    )
    parser.add_argument("--input",  required=True, help="Path to govity.dt.analyses JSON")
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
        "govity",
        "govity_percent",
        "govity_total",
        "govity_possible",
    ]

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            orgs = row.get("organizations") or []
            gv = row.get("govity")
            writer.writerow({
                "id":             row["person_id"],
                "name":           row.get("name") or "",
                "photo":          (row.get("extras") or {}).get("image") or "",
                "candidate_list": newest_name(orgs, "candidate_list"),
                "group":          newest_name(orgs, "group"),
                "constituency":   newest_name(orgs, "constituency"),
                "govity":         gv if gv is not None else "",
                "govity_percent": round(gv * 100, 1) if gv is not None else "",
                "govity_total":    row["govity_total"],
                "govity_possible": row["govity_possible"],
            })

    print(f"Wrote {len(data)} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
