# legislature-data-analyses

Shared analysis scripts for legislature data repositories.

Each analysis is a self-contained directory with a main Python script, an `outputs/` sub-directory for output formatters, and a `tests/` sub-directory with a pytest suite. Scripts accept all file paths as explicit CLI arguments — no relative-path assumptions are made between this repo and the data repo.

## Structure

```
legislature-data-analyses/
├─ attendance/
│  ├─ attendance.py               # main analysis script
│  ├─ outputs/
│  │  └─ output_flourish_table.py # Flourish CSV formatter
│  └─ tests/
│     └─ test_attendance.py
├─ vote-corrections/
│  ├─ vote_corrections.py          # main analysis script
│  ├─ outputs/
│  │  └─ output_flourish_table.py  # Flourish CSV formatter
│  └─ tests/
│     └─ test_vote_corrections.py
└─ wpca/
   ├─ wpca.py                      # main analysis script
   ├─ outputs/
   │  └─ output_flourish_table.py  # Flourish CSV formatter
   └─ tests/
      └─ test_wpca.py
```

## Analyses

### Attendance

Per-member attendance counts derived from votes, vote-events, and an attendance definition.

**Inputs (all CLI arguments):**

| Argument | Description |
|---|---|
| `--attendance-definition` | JSON file defining which vote-event types count as attendance |
| `--votes` | `votes-table.dt` CSV |
| `--vote-events` | `vote-events.dt` JSON |
| `--persons` | `all-members.dt.analyses` JSON or CSV |
| `--output` | output JSON path |

**Output fields per person:** `person_id`, `name`, `given_names`, `family_names`, `organizations`, `present`, `present_share`, `absent`, `excused`, `vote_events_total`, `extras`

**Flourish output:** `id`, `name`, `photo`, `candidate_list`, `group`, `constituency`, `present_share`, `present_share_percent`, `present`, `absent`, `excused`, `vote_events_total`

```bash
python attendance/attendance.py \
  --attendance-definition /path/to/attendance_definition.json \
  --votes /path/to/votes.csv \
  --vote-events /path/to/vote_events.json \
  --persons /path/to/all_members.csv \
  --output /path/to/attendance.json

python attendance/outputs/output_flourish_table.py \
  --input /path/to/attendance.json \
  --output /path/to/attendance_flourish_table.csv
```

**Tests:**

```bash
pytest attendance/tests/
```

---

### Vote corrections

Per-member counts of announced voting corrections (*zmatečná hlasování*) — cases where a member declared they voted differently from their intention, the chamber agreed to repeat the vote, and the original vote event was invalidated.

**Inputs (all CLI arguments):**

| Argument | Description |
|---|---|
| `--objections` | `vote-event-objections.dt` JSON |
| `--votes` | `votes-table.dt` CSV |
| `--vote_events` | `vote-events.dt` JSON |
| `--persons` | `all-members.dt.analyses` JSON or CSV |
| `--output` | output JSON path |
| `--since` | optional ISO date filter (start) |
| `--until` | optional ISO date filter (end) |

**Output fields per person:** `person_id`, `name`, `given_names`, `family_names`, `organizations`, `corrections_total`, `corrections_invalidated`, `corrections_announced`, `vote_events_total`, `extras`

**Flourish output:** `id`, `name`, `photo`, `candidate_list`, `group`, `constituency`, `corrections_total`, `corrections_invalidated`, `corrections_announced`, `vote_events_total`, `correction_rate`

```bash
python vote-corrections/vote_corrections.py \
  --objections /path/to/vote_event_objections.json \
  --votes /path/to/votes.csv \
  --vote_events /path/to/vote_events.json \
  --persons /path/to/all_members.csv \
  --output /path/to/vote_corrections.json

python vote-corrections/outputs/output_flourish_table.py \
  --input /path/to/vote_corrections.json \
  --output /path/to/vote_corrections_flourish_table.csv
```

**Tests:**

```bash
pytest vote-corrections/tests/
```

---

### WPCA (Weighted PCA)

Per-member ideological positions derived from weighted principal component analysis of the full voting record. Two vote-event weights are applied before PCA: **w1** (participation fraction) and **w2** (split balance, 1 = 50/50, 0 = unanimous). Optionally computes rolling time-interval projections using the global eigenbasis.

**Inputs (all CLI arguments):**

| Argument | Description |
|---|---|
| `--definition` | `wpca-definition.dt.analyses` JSON (lo_limit, vote option encoding, optional rotation and time_interval) |
| `--votes` | `votes-table.dt` CSV |
| `--vote-events` | `vote-events.dt` JSON |
| `--persons` | `all-members.dt.analyses` JSON or CSV |
| `--output` | output `wpca.dt.analyses` JSON path |
| `--output-time` | (optional) output `wpca-time.dt.analyses` JSON path; requires `time_interval` in definition |

**Output fields per person (`wpca.dt.analyses`):** `person_id`, `name`, `given_names`, `family_names`, `organizations`, `dims` (array, length = n_dims), `weight`, `included`, `since`, `until`, `extras`

**Time output fields per person-period (`wpca-time.dt.analyses`):** `person_id`, `period_index`, `period_start`, `period_end`, `period_label`, `dims`, `included`

**Flourish output:** `person_id`, `name`, `given_names`, `family_names`, `group`, `candidate_list`, `constituency`, `dim1`, `dim2`, `dim3`, `weight`, `included`

```bash
# Run from the legislature-data/ monorepo root
python legislature-data-analyses/wpca/wpca.py \
  --definition /path/to/wpca_definition.json \
  --votes /path/to/votes.csv \
  --vote-events /path/to/vote_events.json \
  --persons /path/to/all_members.json \
  --output /path/to/wpca.json \
  --output-time /path/to/wpca_time.json   # optional

python legislature-data-analyses/wpca/outputs/output_flourish_table.py \
  --input /path/to/wpca.json \
  --output /path/to/wpca_flourish.csv

python legislature-data-analyses/wpca/outputs/output_flourish_table.py \
  --input /path/to/wpca_time.json \
  --output /path/to/wpca_time_flourish.csv \
  --time
```

**Example definition file:**

```json
{
  "lo_limit": 0.1,
  "yes_options": ["yes"],
  "no_options": ["no", "abstain"],
  "absent_options": ["absent", "before oath"],
  "rotate": { "voter_id": "6074", "dims": [1, 1, 1] },
  "time_interval": "half-year",
  "n_dims": 3
}
```

**Tests:**

```bash
pytest wpca/tests/
```
