#!/usr/bin/env python3
"""
Convert wpca.dt.analyses JSON output to a Flourish-compatible CSV.

Usage:
    python wpca/outputs/output_flourish_table.py \
        --input /path/to/wpca.json \
        --output /path/to/wpca_flourish.csv

    # For time-interval output:
    python wpca/outputs/output_flourish_table.py \
        --input /path/to/wpca_time.json \
        --output /path/to/wpca_time_flourish.csv \
        --time
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def flatten_orgs(orgs: list | None) -> str:
    """Return a comma-separated string of organisation names (or IDs if no name)."""
    if not orgs:
        return ""
    return ", ".join(o.get("name") or o.get("id", "") for o in orgs)


def orgs_by_classification(orgs: list | None, cls: str) -> str:
    """Return first matching org name for the given classification."""
    if not orgs:
        return ""
    for o in orgs:
        if o.get("classification") == cls:
            return o.get("name") or o.get("id", "")
    return ""


def write_global(records: list[dict], output_path: str) -> None:
    """Write global (per-person) WPCA positions as a Flourish-compatible CSV."""
    if not records:
        sys.exit("No records in input file.")

    n_dims = len(records[0].get("dims", []))
    dim_cols = [f"dim{i + 1}" for i in range(n_dims)]

    fieldnames = [
        "person_id", "name", "given_names", "family_names",
        "group", "candidate_list", "constituency",
        *dim_cols,
        "weight", "included",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            orgs = r.get("organizations") or []
            dims = r.get("dims") or []
            row: dict = {
                "person_id":    r.get("person_id", ""),
                "name":         r.get("name", ""),
                "given_names":  " ".join(r.get("given_names") or []),
                "family_names": " ".join(r.get("family_names") or []),
                "group":        orgs_by_classification(orgs, "groups"),
                "candidate_list": orgs_by_classification(orgs, "candidate_list"),
                "constituency": orgs_by_classification(orgs, "constituency"),
                "weight":       r.get("weight", ""),
                "included":     r.get("included", ""),
            }
            for i, col in enumerate(dim_cols):
                row[col] = dims[i] if i < len(dims) else ""
            writer.writerow(row)


def write_time(records: list[dict], output_path: str) -> None:
    """Write time-interval WPCA projections as a Flourish-compatible CSV."""
    if not records:
        sys.exit("No records in input file.")

    n_dims = len(records[0].get("dims", []))
    dim_cols = [f"dim{i + 1}" for i in range(n_dims)]

    fieldnames = [
        "person_id", "period_label", "period_start", "period_end", "period_index",
        *dim_cols,
        "included",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            dims = r.get("dims") or []
            row: dict = {
                "person_id":    r.get("person_id", ""),
                "period_label": r.get("period_label", ""),
                "period_start": r.get("period_start", ""),
                "period_end":   r.get("period_end", ""),
                "period_index": r.get("period_index", ""),
                "included":     r.get("included", ""),
            }
            for i, col in enumerate(dim_cols):
                row[col] = dims[i] if i < len(dims) else ""
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert wpca.dt.analyses JSON to a Flourish-compatible CSV."
    )
    parser.add_argument("--input",  required=True, help="Path to wpca.dt.analyses JSON file")
    parser.add_argument("--output", required=True, help="Path to write Flourish CSV")
    parser.add_argument("--time",   action="store_true",
                        help="Input is wpca-time.dt.analyses (time-interval projections)")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    if not isinstance(data, list):
        sys.exit(f"Input file must contain a JSON array, got: {type(data)}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    if args.time:
        write_time(data, args.output)
    else:
        write_global(data, args.output)

    print(f"Wrote {len(data)} rows to {args.output}")


if __name__ == "__main__":
    main()
