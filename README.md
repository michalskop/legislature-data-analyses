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
└─ vote-corrections/
   ├─ vote_corrections.py          # main analysis script
   ├─ outputs/
   │  └─ output_flourish_table.py  # Flourish CSV formatter
   └─ tests/
      └─ test_vote_corrections.py
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
