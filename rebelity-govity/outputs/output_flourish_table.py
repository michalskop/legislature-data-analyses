#!/usr/bin/env python3
"""
Convert rebelity-govity analysis JSON to a Flourish-ready CSV table.

Columns: id, name, photo, candidate_list, group, constituency,
         rebelity_total, rebelity_possible, rebelity, rebelity_percent,
         govity_total, govity_possible, govity, govity_percent

govity columns are empty when no government definition was provided.

Usage:
    python output_flourish_table.py --input path/to/rebelity_govity.json --output path/to/table.csv
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
    parser = argparse.ArgumentParser(description="Convert rebelity-govity JSON to Flourish CSV.")
    parser.add_argument("--input",  required=True)
    parser.add_argument("--output", required=True)
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
        "rebelity_total",
        "rebelity_possible",
        "rebelity",
        "rebelity_percent",
        "govity_total",
        "govity_possible",
        "govity",
        "govity_percent",
    ]

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            orgs = row.get("organizations") or []
            reb = row.get("rebelity")
            gov = row.get("govity")
            writer.writerow({
                "id":                row["person_id"],
                "name":              row.get("name") or "",
                "photo":             (row.get("extras") or {}).get("image") or "",
                "candidate_list":    newest_name(orgs, "candidate_list"),
                "group":             newest_name(orgs, "group"),
                "constituency":      newest_name(orgs, "constituency"),
                "rebelity_total":    row["rebelity_total"],
                "rebelity_possible": row["rebelity_possible"],
                "rebelity":          reb if reb is not None else "",
                "rebelity_percent":  round(reb * 100, 2) if reb is not None else "",
                "govity_total":      row.get("govity_total", ""),
                "govity_possible":   row.get("govity_possible", ""),
                "govity":            gov if gov is not None else "",
                "govity_percent":    round(gov * 100, 2) if gov is not None else "",
            })

    print(f"Wrote {len(data)} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
