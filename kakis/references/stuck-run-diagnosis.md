# Stuck-run diagnosis

Use when a Kakis run appears stalled: no progress for hours, a gate that appears to still be waiting, or a notification arrived but the pipeline did not move.

**First rule: trust `kakis_state.json` over the reported symptom.** Verify the true phase/gate before diagnosing what was described — a run reported as 'waiting at Gate 1' may already be past it, with the real stall one phase later.

## Evidence, in order (each step is cheap; stop when the answer is in)

1. **State** — `~/.hermes/kakis-runs/<run>/kakis_state.json`: `phase`, `gate`, `gate_waiting`, `gate_timestamp` (UTC), `gate_auto_proceeded`, poller `job_id`. Pins the true position.
2. **Notification log** — `notification.log` in the run workspace: `[AUTO-PROCEED]` / `[GATE BYPASS]` / `[TELEGRAM BYPASS]` lines with UTC timestamps.
3. **Sentinels** — `.gate_decided_<gate>` (per gate; a bare `.gate_decided` is a legacy bug). Present = the poller decided that gate.
4. **Cron job** — `cronjob_manage` list: job state (`scheduled`/`completed`), `repeat` n/m (n/m = exhausted — no further fires), `last_run_at` (local time).
5. **Cron executions** — `~/.hermes/cron/executions.db` (SQLite, table `executions`), rows for the job id: `claimed_at`, `status`, `delivery_outcome` per fire. `suppressed` = the fire produced no output (a no-op poller tick — normal, not a failure); `delivered` = stdout was sent to the job's delivery target. `deliveries.db` holds the delivery rows.
6. **Next-phase artifacts** — e.g. `bob_dispatch.log` / `bob_plan.md` in the run workspace; a fresh `~/.hermes/bob-workspaces/bob_*` directory. Absent even though state names the phase started = the phase never actually executed.
7. **Call trace** — `calls.jsonl`: the last record shows where the pipeline actually stopped (open vs closed records).
8. **Orchestrator session** — `~/.hermes/state.db`, `sessions` table (`started_at`/`timestamp` are epoch seconds — convert to local): which session ran the run and when it last acted. No turns after the gate send = the session never woke.

## Interpretation

- **State advanced, next-phase artifacts absent** — wake gap: a `no_agent` poller auto-proceeded the state but nothing ran the next phase (the poller never wakes the orchestrator; continuation depends on a user reply). Present the position; resume on the user's instruction.
- **`gate_waiting: true` with the poller job repeat-exhausted** — the timeout window closed with no fire after the deadline (6 ticks land ON the 3600 s deadline with zero slack). The gate will not auto-proceed; resume manually or re-schedule a poller.
- **Gate message arrived with no attachment** — check the `gateN_message.txt` on disk: `hermes send` attaches only `MEDIA:<path>` lines in the body; `gate.py` has no attachment path of its own. Judge from the file, not from memory of what was sent.
- **Timestamp mismatches** — state / `notification.log` are UTC; cron records and filesystem mtimes are local (host is UTC+8). Convert before comparing.

## Boundary

Diagnosis is read-only: do not auto-resume a stuck run, dispatch a phase, or mutate state. Present the verified position with the evidence trail and let the user decide.
