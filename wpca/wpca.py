#!/usr/bin/env python3
"""
Weighted PCA (WPCA) analysis: positions each member in a low-dimensional
ideological space derived from their voting record.

Inputs (all named CLI parameters):
  --definition     path to wpca-definition.dt.analyses JSON
  --votes          path to votes-table.dt CSV (voter_id, vote_event_id, option)
  --vote-events    path to vote-events.dt JSON
  --persons        path to all-members.dt.analyses JSON or CSV
  --output         path to write wpca.dt.analyses output JSON (global positions)

Optional:
  --output-time    path to write wpca-time.dt.analyses output JSON
                   (time-interval projections; requires time_interval in definition)

Algorithm:
  1. Encode votes: yes_options → +1, no_options → -1, absent_options → NA.
  2. Compute vote-event weights w1 (participation) and w2 (balance).
  3. Build weighted scaled matrix X0 (NA → 0).
  4. Compute weighted covariance C = X0'X0 / (Iw'Iw) * sum(w1²w2²).
  5. Eigendecompose C; project persons into n_dims dimensions (unit-scaled).
  6. Apply optional rotation to orient axes consistently.
  7. (If time_interval set) project each time window into the global eigenbasis.
"""

import argparse
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd


# ── Schema paths ───────────────────────────────────────────────────────────────

_SCHEMA_BASE = Path(__file__).parent.parent.parent / "legislature-data-standard" / "dist"

SCHEMA_PATHS = {
    "definition":  _SCHEMA_BASE / "dt.analyses" / "wpca-definition" / "latest" / "schemas" / "wpca-definition.dt.analyses.json",
    "votes_row":   _SCHEMA_BASE / "dt" / "latest" / "schemas" / "votes-table.dt.json",
    "vote_events": _SCHEMA_BASE / "dt" / "latest" / "schemas" / "vote-events.dt.json",
    "persons":     _SCHEMA_BASE / "dt.analyses" / "all-members" / "latest" / "schemas" / "all-members.dt.analyses.json",
    "output":      _SCHEMA_BASE / "dt.analyses" / "wpca" / "latest" / "schemas" / "wpca.dt.analyses.json",
    "output_time": _SCHEMA_BASE / "dt.analyses" / "wpca-time" / "latest" / "schemas" / "wpca-time.dt.analyses.json",
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


def _parse_json_field(raw: str) -> object:
    if not raw or raw.strip() in ("", "{}", "[]"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def load_persons(path: str) -> list[dict]:
    """Load persons from JSON or CSV (all-members.dt.analyses format)."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                person = dict(row)
                for field in ("identifiers", "sources", "other_names"):
                    if field in person and person[field]:
                        person[field] = _parse_json_field(person[field]) or []
                if "memberships" in person:
                    person["memberships"] = _parse_json_field(person["memberships"]) or {}
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


# ── Vote encoding ──────────────────────────────────────────────────────────────

def encode_option(option: str, yes_options: list, no_options: list, absent_options: list) -> float | None:
    """Map a vote option string to +1.0, -1.0, or None (absent/NA)."""
    if option in yes_options:
        return 1.0
    if option in no_options:
        return -1.0
    # Unknown options and absent_options both map to NA
    return None


# ── Time interval helpers ──────────────────────────────────────────────────────

def generate_periods(first: date, last: date, interval: str) -> list[tuple[date, date, int]]:
    """Return (period_start, period_end, period_index) covering [first, last]."""
    periods: list[tuple[date, date, int]] = []
    idx = 0

    if interval == "half-year":
        year, half = first.year, (1 if first.month <= 6 else 2)
        while True:
            start = date(year, 1 if half == 1 else 7, 1)
            end   = date(year, 6, 30) if half == 1 else date(year, 12, 31)
            periods.append((start, end, idx))
            if end >= last:
                break
            idx += 1
            half, year = (2, year) if half == 1 else (1, year + 1)

    elif interval == "quarter":
        q_starts = [1, 4, 7, 10]
        q_ends   = [(3, 31), (6, 30), (9, 30), (12, 31)]
        year, q = first.year, (first.month - 1) // 3 + 1
        while True:
            start = date(year, q_starts[q - 1], 1)
            end   = date(year, q_ends[q - 1][0], q_ends[q - 1][1])
            periods.append((start, end, idx))
            if end >= last:
                break
            idx += 1
            q += 1
            if q > 4:
                q, year = 1, year + 1

    elif interval == "year":
        year = first.year
        while True:
            start = date(year, 1, 1)
            end   = date(year, 12, 31)
            periods.append((start, end, idx))
            if end >= last:
                break
            idx += 1
            year += 1

    else:
        raise ValueError(f"Unknown time_interval: {interval!r}")

    return periods


def period_label(start: date, end: date, interval: str) -> str:
    if interval == "half-year":
        return f"{1 if start.month <= 6 else 2}. pol. {start.year}"
    if interval == "quarter":
        return f"Q{(start.month - 1) // 3 + 1} {start.year}"
    return str(start.year)


# ── Person metadata ────────────────────────────────────────────────────────────

def extract_person_meta(person: dict) -> dict:
    """Extract name and organization fields from an all-members person record."""
    given_names  = person.get("given_names") or []
    family_names = person.get("family_names") or []
    if not given_names and person.get("given_name"):
        given_names = [person["given_name"]]
    if not family_names and person.get("family_name"):
        family_names = [person["family_name"]]

    name = person.get("name")
    if not name and (given_names or family_names):
        name = " ".join(given_names + family_names)

    memberships = person.get("memberships") or {}
    orgs = []
    if isinstance(memberships, dict):
        for classification, mems in memberships.items():
            if isinstance(mems, list):
                for m in mems:
                    if isinstance(m, dict) and m.get("id"):
                        orgs.append({
                            "id": m["id"],
                            "name": m.get("name"),
                            "classification": classification,
                            "since": m.get("start_date"),
                            "until": m.get("end_date"),
                        })

    # since/until from parliament membership
    parl_mems = memberships.get("parliament", []) if isinstance(memberships, dict) else []
    since = parl_mems[0].get("start_date") if parl_mems else None
    until = parl_mems[0].get("end_date")   if parl_mems else None

    return {
        "name":         name or None,
        "given_names":  given_names or None,
        "family_names": family_names or None,
        "organizations": orgs or None,
        "since": since,
        "until": until,
    }


# ── WPCA core ─────────────────────────────────────────────────────────────────

def run_wpca(
    Xraw: pd.DataFrame,   # vote_event_id × voter_id, values +1 / -1 / nan
    n_dims: int,
) -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame, pd.Series, pd.Series]:
    """
    Run weighted PCA on the raw vote matrix.

    Returns
    -------
    Xproju_df : DataFrame (voter_id × n_dims)  — unit-scaled global projections
    eigvecs   : ndarray  (n_voters × n_voters) — full eigenvector matrix
    Z         : DataFrame (vote_event_id × n_voters) — rotation matrix for time projections
    pw        : Series (voter_id) — weighted attendance share ∈ [0, 1]
    w1w2      : Series (vote_event_id) — combined event weight
    """
    n_voters = Xraw.shape[1]

    # Standardise rows (zero-mean, unit-variance per vote event)
    row_std  = Xraw.std(axis=1, ddof=0).replace(0, np.nan)
    Xstand   = Xraw.sub(Xraw.mean(axis=1), axis=0).div(row_std, axis=0)

    # w1 — participation weight (fraction of max voters per event)
    w1 = (np.abs(Xraw) == 1).sum(axis=1, skipna=True)
    w1_max = w1.max()
    w1 = (w1 / w1_max if w1_max > 0 else w1).fillna(0)

    # w2 — balance weight (1 = 50/50 split, 0 = unanimous)
    yes_cnt   = (Xraw == 1).sum(axis=1, skipna=True)
    no_cnt    = (Xraw == -1).sum(axis=1, skipna=True)
    present   = (~Xraw.isna()).sum(axis=1, skipna=True).replace(0, np.nan)
    w2        = (1 - np.abs(yes_cnt - no_cnt) / present).fillna(0)

    w1w2 = w1 * w2

    # Weighted scaled matrix (NA stays NA), fill-NA version
    X  = Xstand.mul(w1, axis=0).mul(w2, axis=0)
    X0 = X.fillna(0)

    # Weighted attendance per voter
    I   = X.notna().astype(float)
    Iw  = I.mul(w1, axis=0).mul(w2, axis=0)
    w_total = w1w2.sum()
    pw  = Iw.sum(axis=0) / w_total if w_total > 0 else pd.Series(0.0, index=Iw.columns)

    # Weighted covariance matrix  C = X0'X0 / (Iw'Iw) * sum(w1²w2²)
    IwTIw = Iw.T.dot(Iw).replace(0, np.nan)
    C = (X0.T.dot(X0) / IwTIw * (w1w2 ** 2).sum()).fillna(0)

    # Eigendecomposition (use real parts; C is symmetric so should be real)
    eigvals_raw, eigvecs_raw = np.linalg.eig(C.values)
    eigvals = eigvals_raw.real
    eigvecs = eigvecs_raw.real
    order   = eigvals.argsort()[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    # Lambda (sqrt of eigenvalues, floored at 0)
    sigma  = np.sqrt(np.maximum(eigvals, 0))
    lmbda  = np.diag(sigma)
    lmbda2 = lmbda @ lmbda
    lmbda2_sum = lmbda2.sum()
    lambdau = np.sqrt(lmbda2 / lmbda2_sum) if lmbda2_sum > 0 else np.zeros_like(lmbda)

    # Unit-scaled projection of persons (voter_id × n_voters)
    Xproju    = eigvecs @ lambdau * np.sqrt(n_voters)
    Xproju_df = pd.DataFrame(Xproju, index=X0.columns)

    # Z rotation matrix for time projections (vote_event_id × n_voters)
    lambda_1 = np.diag(np.where(sigma > 0, 1.0 / sigma, 0.0))
    Z = pd.DataFrame(X0.values @ eigvecs @ lambda_1, index=X0.index, columns=X0.columns)

    return Xproju_df.iloc[:, :n_dims], eigvecs, Z, pw, w1w2


def apply_rotation(df: pd.DataFrame, rotate: dict | None) -> pd.DataFrame:
    """Flip dimension signs so the reference person has positive coordinates."""
    if not rotate:
        return df
    voter_id = rotate.get("voter_id")
    signs    = rotate.get("dims", [])
    if voter_id is None:
        return df

    # Look up the reference row (try both str and original type)
    ref = None
    for key in (voter_id, str(voter_id)):
        if key in df.index:
            ref = df.loc[key]
            break

    if ref is None:
        print(f"Warning: rotation reference voter_id={voter_id!r} not found; skipping rotation.", file=sys.stderr)
        return df

    result = df.copy()
    for i, sign in enumerate(signs):
        if i >= result.shape[1]:
            break
        if sign * ref.iloc[i] < 0:
            result.iloc[:, i] = result.iloc[:, i] * -1
    return result


def _float_or_none(v: float) -> float | None:
    return None if (isinstance(v, float) and math.isnan(v)) else float(v)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Weighted PCA analysis for legislature data.")
    parser.add_argument("--definition",  required=True,
                        help="Path to wpca-definition.dt.analyses JSON")
    parser.add_argument("--votes",       required=True,
                        help="Path to votes-table.dt CSV")
    parser.add_argument("--vote-events", required=True, dest="vote_events",
                        help="Path to vote-events.dt JSON")
    parser.add_argument("--persons",     required=True,
                        help="Path to all-members.dt.analyses JSON or CSV")
    parser.add_argument("--output",      required=True,
                        help="Path to write wpca.dt.analyses output JSON")
    parser.add_argument("--output-time", dest="output_time", default=None,
                        help="Path to write wpca-time.dt.analyses output JSON "
                             "(requires time_interval in definition)")
    args = parser.parse_args()

    # ── Load and validate inputs ───────────────────────────────────────────────
    definition       = load_definition(args.definition)
    vote_events_list = load_vote_events(args.vote_events)
    votes_list       = load_votes(args.votes)
    persons_list     = load_persons(args.persons)

    # ── Unpack definition ──────────────────────────────────────────────────────
    lo_limit       = definition["lo_limit"]
    lo_limit_time  = definition.get("lo_limit_time", lo_limit)
    yes_options    = definition.get("yes_options", ["yes"])
    no_options     = definition.get("no_options", ["no", "abstain"])
    absent_options = definition.get("absent_options", ["absent", "before oath"])
    rotate_cfg     = definition.get("rotate")
    time_interval  = definition.get("time_interval")
    n_dims         = int(definition.get("n_dims") or 3)
    since_filter   = definition.get("since")
    until_filter   = definition.get("until")

    # ── Index vote events by ID, extract dates ─────────────────────────────────
    ve_dates: dict[str, date | None] = {}
    for ve in vote_events_list:
        ve_id    = ve.get("id")
        raw_date = ve.get("start_date")
        if not ve_id:
            continue
        parsed = None
        if raw_date:
            try:
                parsed = date.fromisoformat(str(raw_date)[:10])
            except (ValueError, TypeError):
                pass
        ve_dates[str(ve_id)] = parsed

    # Apply date filters
    valid_ve_ids: set[str] = set()
    for ve_id, ve_date in ve_dates.items():
        if ve_date is None:
            valid_ve_ids.add(ve_id)
            continue
        if since_filter and ve_date < date.fromisoformat(since_filter):
            continue
        if until_filter and ve_date > date.fromisoformat(until_filter):
            continue
        valid_ve_ids.add(ve_id)

    # ── Encode votes into pivot matrix ─────────────────────────────────────────
    rows = []
    for v in votes_list:
        ve_id    = str(v.get("vote_event_id", ""))
        voter_id = str(v.get("voter_id", ""))
        option   = str(v.get("option", ""))
        if ve_id not in valid_ve_ids:
            continue
        rows.append({
            "vote_event_id": ve_id,
            "voter_id":      voter_id,
            "value":         encode_option(option, yes_options, no_options, absent_options),
        })

    if not rows:
        sys.exit("No valid votes found after filtering.")

    Xraw = pd.pivot_table(
        pd.DataFrame(rows),
        values="value",
        columns="voter_id",
        index="vote_event_id",
        aggfunc="first",
    )

    # ── Run WPCA ──────────────────────────────────────────────────────────────
    Xproju_df, eigvecs, Z, pw, w1w2 = run_wpca(Xraw, n_dims)
    Xproju_df = apply_rotation(Xproju_df, rotate_cfg)

    # ── Person metadata index ──────────────────────────────────────────────────
    persons_by_id: dict[str, dict] = {str(p["id"]): p for p in persons_list}

    # ── Build global output ────────────────────────────────────────────────────
    output = []
    for voter_id in pw.index:
        weight   = float(pw[voter_id])
        included = weight > lo_limit

        dims_vals: list[float | None] = [None] * n_dims
        if voter_id in Xproju_df.index:
            dims_vals = [_float_or_none(v) for v in Xproju_df.loc[voter_id].tolist()]

        meta = extract_person_meta(persons_by_id.get(voter_id, {}))

        record: dict = {
            "person_id": str(voter_id),
            "dims":      dims_vals,
            "weight":    weight,
            "included":  included,
        }
        if meta["name"]:          record["name"]          = meta["name"]
        if meta["given_names"]:   record["given_names"]   = meta["given_names"]
        if meta["family_names"]:  record["family_names"]  = meta["family_names"]
        if meta["organizations"]: record["organizations"] = meta["organizations"]
        if meta["since"]:         record["since"]         = meta["since"]
        if meta["until"]:         record["until"]         = meta["until"]
        output.append(record)

    # Validate and write
    out_schema = load_schema("output")
    try:
        jsonschema.validate(instance=output, schema=out_schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"Output failed schema validation: {e.message}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(output)} person records to {args.output}")

    # ── Time-interval projections ──────────────────────────────────────────────
    if not args.output_time:
        return

    if not time_interval:
        sys.exit("--output-time requires time_interval to be set in the definition.")

    dated_ids = {ve_id: d for ve_id, d in ve_dates.items() if d is not None and ve_id in valid_ve_ids}
    if not dated_ids:
        sys.exit("No dated vote events found for time-interval projections.")

    first_date = min(dated_ids.values())
    last_date  = max(dated_ids.values())
    periods    = generate_periods(first_date, last_date, time_interval)

    # Only voters included in the global result
    selected_voters = [vid for vid in pw.index if pw[vid] > lo_limit]
    if not selected_voters:
        sys.exit("No voters passed lo_limit; cannot compute time projections.")

    Xraw_sel = Xraw.reindex(columns=selected_voters)

    # Global standardisation parameters (reused for every period)
    row_std   = Xraw.std(axis=1, ddof=0).replace(0, np.nan)
    Xstand    = Xraw.sub(Xraw.mean(axis=1), axis=0).div(row_std, axis=0)

    # Global event weights (reused for every period)
    w1_full = (np.abs(Xraw) == 1).sum(axis=1, skipna=True)
    w1_max  = w1_full.max()
    w1_s    = (w1_full / w1_max if w1_max > 0 else w1_full).fillna(0)
    yes_cnt = (Xraw == 1).sum(axis=1, skipna=True)
    no_cnt  = (Xraw == -1).sum(axis=1, skipna=True)
    present = (~Xraw.isna()).sum(axis=1, skipna=True).replace(0, np.nan)
    w2_s    = (1 - np.abs(yes_cnt - no_cnt) / present).fillna(0)

    # aZ: absolute value of Z matrix (vote_event_id × n_voters)
    aZ        = np.abs(Z.values)           # shape (n_ve, n_full_voters)
    aZ_colsum = aZ.sum(axis=0)             # shape (n_full_voters,)

    # We only project into the n_dims columns of eigvecs that matter
    # Z columns correspond to all voters (full eigvec space); we use :n_dims
    Z_np = Z.values  # (n_ve × n_full_voters)

    time_output: list[dict] = []

    for period_start, period_end, period_idx in periods:
        label    = period_label(period_start, period_end, time_interval)
        in_period = {vid for vid, d in dated_ids.items() if period_start <= d <= period_end}

        # Standardised matrix for this period (out-of-period rows → NaN), selected voters
        XTc = Xstand.reindex(columns=selected_voters).copy()
        out_mask = ~XTc.index.isin(in_period)
        XTc[out_mask] = np.nan

        # Indicator: 1 where voter was present in-period, 0 otherwise
        I_period = XTc.notna().astype(float)

        # Per-voter weight in this period
        Iw_p  = I_period.mul(w1_s, axis=0).mul(w2_s, axis=0)
        s     = Iw_p.sum(axis=0)
        s_max = s.max()
        pTW   = s / s_max if s_max > 0 else s * 0

        sel_this = pTW[pTW > lo_limit_time].index.tolist()

        # Projection of selected voters into global eigenbasis
        proj_df: pd.DataFrame | None = None
        if sel_this:
            # Weighted period matrix, NaN → 0
            XTw0 = XTc[sel_this].mul(w1_s, axis=0).mul(w2_s, axis=0).fillna(0)

            # aZ restricted to selected voters' columns in the full voter space
            # Z columns are indexed by full voter set (Xraw.columns order)
            full_voter_order = list(Z.columns)
            sel_idx = [full_voter_order.index(v) for v in sel_this if v in full_voter_order]
            aZ_sel   = aZ[:, sel_idx]              # (n_ve, n_sel)
            colsum_s = aZ_colsum[sel_idx]           # (n_sel,)

            # Dimension weights: fraction of each dimension explained by in-period events
            # dweights[i, k] = sum_e(aZ[e,k] * I_period[e,i]) / sum_e(aZ[e,k])
            TIcc     = I_period[sel_this].values    # (n_ve, n_sel)
            dweights = (aZ_sel.T @ TIcc).T / colsum_s[np.newaxis, :]  # (n_sel, n_sel full)

            # Use only the first n_dims columns (matching the global projection)
            dweights_nd = dweights[:, :n_dims]                         # (n_sel, n_dims)
            Z_nd        = Z_np[:, :n_dims]                             # (n_ve, n_dims)

            raw_proj = XTw0.values.T @ Z_nd                            # (n_sel, n_dims)
            with np.errstate(divide="ignore", invalid="ignore"):
                proj_vals = np.where(dweights_nd > 0, raw_proj / dweights_nd, np.nan)

            proj_df = pd.DataFrame(proj_vals, index=sel_this)
            proj_df = apply_rotation(proj_df, rotate_cfg)

        for voter_id in selected_voters:
            if proj_df is not None and voter_id in proj_df.index:
                dims_vals = [_float_or_none(v) for v in proj_df.loc[voter_id].tolist()]
                inc = True
            else:
                dims_vals = [None] * n_dims
                inc = False

            time_output.append({
                "person_id":    str(voter_id),
                "period_index": period_idx,
                "period_start": period_start.isoformat(),
                "period_end":   period_end.isoformat(),
                "period_label": label,
                "dims":         dims_vals,
                "included":     inc,
            })

    # Validate and write time output
    time_schema = load_schema("output_time")
    try:
        jsonschema.validate(instance=time_output, schema=time_schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"Time output failed schema validation: {e.message}")

    Path(args.output_time).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_time, "w") as f:
        json.dump(time_output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(time_output)} time-interval records to {args.output_time}")


if __name__ == "__main__":
    main()
