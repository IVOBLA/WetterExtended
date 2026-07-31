# P105 forecast verification storage

The authoritative closed-loop ledger uses SQLite in WAL mode at
`train_data/evaluation/forecast_verification.sqlite`. A case identity contains
forecast creation and target time, horizon, origin object/cell/radar-track IDs,
and source-frame ID. Actual coordinates, matcher result and verification run time
are intentionally excluded. Variants add their forecast variant ID.

Only final `exact_id`, `exact_cell_id`, and timestamp-evidenced
`lineage_confirmed` revisions enter `final_actuals`. Geometric nearest neighbours
remain diagnostic `ambiguous_nearest` records. Reprocessing is idempotent;
revisions are retained while the single case-level active actual is replaced.
The JSONL latest/revision files are atomic debug views, not write authorities.

On a Raspberry Pi 5, SQLite adds one small indexed row per revision plus the
case/variant rows. WAL transactions serialize writers and avoid loading the
ledger into RAM; exports load the current ledger into memory and should therefore
be scheduled rather than requested per API read once histories become large.
No matcher, tolerance, radius, lineage or alarm threshold is made tunable here.
