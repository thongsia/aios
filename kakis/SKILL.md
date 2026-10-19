---
name: Kakis
description: "Research→Dory→Bob→execute orchestration with Telegram gates."
version: 0.7.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [planning, multi-agent, delegation, orchestration, workflow]
    related_skills: [Igor, Dory, Bob]
---

# Kakis Workflow Skill

Chains four phases — feasibility research, iterative planning, best-of-breed synthesis, and step-by-step execution — separated by three Telegram decision gates where the user approves or aborts. Resumes on interruption. Gates 1 and 2 auto-proceed after 1 hour of silence; Gate 0 (feasibility) has no timeout and waits indefinitely for an explicit proceed/abort.

## When to Use

- The user provides a goal that benefits from multi-stage refinement: first assess feasibility (research agent), then plan iteratively (Dory), then synthesize across AI agents (Bob), then execute step by step.
- The user wants a quick feasibility verdict (blockers, dependencies, go/no-go risk) before committing to full planning.
- The user wants human-in-the-loop approval gates via Telegram before each major phase transition.
- The task is complex enough that a single-pass plan would be insufficient.

Don't use for:
- Simple tasks where one planning pass suffices — use `delegate_task` directly.
- When the user wants immediate execution without gates — follow the plan skill instead.

## Prerequisites

- Igor skill installed and functional (`skill_view(name='Igor')`).
- Dory skill installed and functional (`skill_view(name='Dory')`).
- Bob skill installed at `~/.hermes/skills/aios/bob/` with at least one working harness (`skill_view(name='Bob')`).
- Telegram configured in `~/.hermes/.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`).
- `hermes send --to telegram` delivers messages (exit code 0).
- OpenSearch memory mirror (best-effort, never a prerequisite): the cluster (base URL from `AIOS_OPENSEARCH` in the process env or `~/.hermes/.env` — no built-in default; if unset, the export no-ops) reachable so `kakis_export.py` can mirror run artifacts for other agents. The pipeline must never depend on it — see Memory export.

## Memory export (best-effort — never blocks the pipeline)

A copy of every run artifact, plus the sub-module call trace, is mirrored into OpenSearch on a private-network cluster (aliases `kakis_runs`, `kakis_artifacts`, `kakis_calls`) so other agents can use pipeline history as long-term memory. The schema and query recipes are self-described in the `kakis_meta` index (see the `kakis_memory` skill for the access protocol). Two mechanisms:

1. **`calls.jsonl`** — for EVERY `delegate_task` dispatch and Bob harness run, append one JSON line to `<run_workspace>/calls.jsonl`:
   ```json
   {"seq": 3, "ts": "<ISO8601>", "module": "dory_planner|dory_reviewer|bob_harness|bob_synth|execution_batch|compress", "variant": "<harness|batch label|null>", "iteration": 2, "goal_head": "<first 200 chars of the delegation goal>", "input_refs": ["dory/prompt_2.txt"], "status": "ok|failed|timeout", "ended_ts": "<ISO8601, null while open>", "result_summary_head": "<first 300 chars of the result>", "output_refs": ["dory/plan_2.txt"]}
   ```
   `seq` is per-run monotonic. On the delegation's result return, append a CLOSED record with the same `seq`+`module` (status/ended_ts/summary/output_refs filled in) — the exporter keeps the latest record per (seq, module). A failed append is logged to `notification.log`; never block the pipeline on it.
2. **`kakis_export.py`** — after every `kakis_state.json` phase update (end of Phase 0.5, Phase 1, Phase 2, Phase 3) and once more after the Phase 4 notification, run:
   ```
   python3 ~/.hermes/skills/aios/kakis/scripts/kakis_export.py <run_workspace>
   ```
   Non-zero exit → append the error to `notification.log` and continue. The pipeline NEVER aborts on export failure (local files stay canonical; re-export is idempotent). The cluster base URL comes from `AIOS_OPENSEARCH` (process env or `~/.hermes/.env`) or the `--opensearch` flag; with neither set, the script exits 4 with a clear not-configured message and the run is simply not mirrored. On a machine that cannot reach the cluster the export simply no-ops — runs there work normally but are not mirrored unless they can reach it.

## Procedure

Follow these phases in order. The orchestrator agent is the one running this skill.

### Phase 0 — Resume Check

1. Scan `~/.hermes/kakis-runs/` for `kakis_state.json` files where `phase` is not `completed` or `aborted`.
2. If exactly one incomplete run exists, present its run_id, goal, and current phase to the user and ask whether to resume.
3. If multiple exist, list them and ask the user to pick one.
4. If none exist, proceed with a fresh run.
5. On resume, skip already-completed steps (check `completed_steps` in the state file).
6. **Gate reply handling**: If `gate_waiting: true` in state, the user's current message IS the gate reply. Strip any `/kakis` prefix (e.g., "/kakis proceed" → "proceed"), then classify:
   - Load `gate.py` (or use inline keyword matching with the APPROVE/REJECT sets below).
   - If `proceed`: set `gate_waiting: false`, advance to the next phase (gate0 → dory, gate1 → bob, gate2 → execute). If the reply carries an appended instruction after the keyword (e.g. "proceed, focus on X"), record it in state (e.g. `gate_N_scope`) and fold it into the next phase's subagent contexts — gate replies are where this user steers scope; a bare keyword match that drops the note loses the steer.
   - If `abort`: set phase `aborted`, notify the user, and stop.
   - If `unrecognized`: send "I did not understand '...'. Reply with '/kakis proceed' to continue or '/kakis stop' to abort." and stop again (leaving `gate_waiting: true`).

   APPROVE keywords: proceed, yes, go, continue, ok, okay, sure, do it, agree, approve, forward, next, yep, yea, yup
   REJECT keywords: stop, no, abort, cancel, halt, skip, nah, decline, reject, dont, don't, later, not now, pass

**Completion:** User has chosen a run path (fresh or resume) and `kakis_state.json` is loaded.

### Phase 0.5 — Feasibility Research (Gate 0)

Before invoking Dory, quickly assess whether the goal is feasible. Research ONLY: no planning, no code, no execution. This phase delegates to the **Igor** skill (orchestrated mode). Unlike Gates 1 and 2, this gate has NO timeout and NO auto-proceed — it waits indefinitely for the user's explicit proceed/abort.

1. Derive a task slug from the goal (lowercase, hyphens, max 40 chars). Create the run workspace `~/.hermes/kakis-runs/<slug>_<timestamp>/` and initialize `kakis_state.json` with `phase: "research"`, empty `completed_steps`, and the original goal.
2. **Invoke Igor in orchestrated mode**: load the Igor skill (`skill_view(name='Igor')`) and run its workflow, passing the run workspace path as Igor's `<workspace>`. Igor delegates the research subagent and writes `feasibility.md` into the run workspace, returning a GO / RISKY / NO-GO verdict and the report path. Igor does NOT send a Telegram message in orchestrated mode — Kakis owns the gate below. (The research prompt template, strict rules, and the researcher's recursion guard all live in the Igor skill, not here.)
3. Confirm `feasibility.md` exists in the run workspace with a valid `=== FEASIBILITY: <GO|RISKY|NO-GO> ===` verdict line (Igor verifies this; re-check before the gate). Spot-check a few of the report's cited code locations (file names, function names, line anchors) against the real repo before the gate — research facts drift (phantom directories, wrong function names, stale line numbers), and unverified facts get inherited by Dory and Bob, forcing re-anchoring hours later in execution.
4. Write the gate message (verdict, key unknowns, top risks) to `<run_workspace>/gate0_message.txt`, appending the reply line below — never build a multi-line gate message as an inline shell string. Send it via `gate.py gate` (same as Gate 1) with `--message "$(cat <run_workspace>/gate0_message.txt)"` and confirm the command prints `sent` (a `bypass` means the send failed — fix and resend before waiting):
   ```
   Reply with '/kakis proceed' to continue or '/kakis stop' to abort.
   ```
5. Update `kakis_state.json`: set `phase: "gate0"`, `gate: "gate0"`, `gate_waiting: true`. Run the memory export (Memory export section).
6. **No cron poller, no timeout**: do NOT schedule a `gate_poller.py` job for Gate 0. The gate waits indefinitely.
7. The agent STOPS. On reply (handled by Phase 0):
   - `proceed`: set `gate_waiting: false`, `phase: "dory"`, continue to Phase 1.
   - `abort`: set phase `aborted`, notify the user, and stop.
8. If the research subagent fails: record `research_failure_cause` in state, notify the user that feasibility research failed, and ask whether to proceed without the report or abort — same gate, no timeout. If proceeding, continue to Phase 1 without `feasibility.md`.

**Completion:** Gate 0 decision recorded; pipeline proceeds to Dory or aborts.

### Phase 1 — Dory Planning

1. Verify the run workspace exists (created in Phase 0.5). If it is missing (should only happen on a manual resume), derive the slug and create it.
2. Set `kakis_state.json` phase to `"dory"` (workspace and state were initialized in Phase 0.5).
3. Create a Dory sub-workspace: `~/workspace/kakis_<timestamp>/` — this directory is the Dory task folder for the run: pass it to Dory as the task folder (Dory's own slug derivation is overridden when an orchestrator supplies one — see its Initialization step).
4. Run the full Dory iterative planning loop on the user's goal statement. Follow the Dory skill exactly, with the step-3 sub-workspace as the task folder — delegate subplanner and subreviewer, check saturation, iterate until convergence. In sessions where `delegate_task` results re-enter as async messages, run one dispatch per turn (planner → end turn → reviewer → end turn → saturation check → next planner). Persist `current_prompt` to the Dory workspace as `prompt_0.txt` at loop start, and treat the on-disk `prompt_N.txt`/`review_N.txt` files as the sole source of truth between turns — they survive context compaction, and their full text must be inlined into each delegation context (see the inlined-text pitfall). Record each dispatch in `calls.jsonl` (module `dory_planner` for the subplanner, `dory_reviewer` for the subreviewer — see Memory export).
5. **Specification-level output**: Dory's subplanner must stay at SPECIFICATION level — architecture, requirements, and edge cases only. Do NOT let it write implementation code, CLI invocations, JSON schemas, or API signatures. Add this to the subplanner context:
   ```
   CRITICAL: Stay at SPECIFICATION level. Do NOT write implementation code,
   CLI invocations, JSON schemas, API signatures, or file layout diagrams.
   Describe WHAT is needed, not HOW to build it.
   ```
   For data-analysis goals, also pass VERIFIED source-data facts into the subplanner context (resource ids, actual date windows, when each series/label/value first appears, what each category truly means) and instruct it to confirm them against the data rather than assume the prompt's stated values — see the "Data-analysis runs carry extra discipline" pitfall (load `kakis/references/data-analysis-runs.md`). For code-fix goals, pass the analogous VERIFIED codebase facts — the exact rules, functions, and markup the plan will touch (with line anchors), the existing idioms to reuse, and the repo's test infrastructure — and instruct the subplanner to re-verify each against the working tree before planning (line numbers are hints and may have drifted). For goal types with strong domain constraints (e.g. mobile web on real devices), if a domain skill for that domain exists, load it and fold its workflow into the subplanner context so the plan is shaped by the domain constraints from the start.
6. After Dory saturate, discover its output artifacts by scanning the Dory workspace for the latest `plan_*.txt`, `prompt_*.txt`, and `review_*.txt` (sort filenames to find the highest N). Copy them to the Kakis run workspace as `final_prompt.txt`, `final_plan.txt`, `final_review.txt`.
7. **Preemptive compression**: Read all Dory artifacts (`final_plan.txt`, `final_prompt.txt`, `final_review.txt`, and any prior `review_*.txt` that are still in the workspace). Delegate a subagent to compress them into `dory_brief.md` — a single, compact summary (max 60 lines) containing only: the goal statement, the final refined prompt, the key architectural decisions, and unresolved edge cases from the last review. The subagent should discard iteration history, repeated findings, and operational details.
8. Update `kakis_state.json`: set `phase: "gate1"`, record the Dory sub-workspace path as `dory_workspace`, plus Dory artifact paths and iteration count (the memory exporter resolves `dory/` artifacts from `dory_workspace` — omit it and they silently drop out of the mirror); run the memory export (Memory export section). Kakis owns the user-facing delivery: suppress Dory's standalone completion Telegram — Gate 1's message is the notification, and a double-send confuses the user (same rule as Igor's orchestrated mode).
9. If Dory fails: set `dory_failure_cause` in state, send failure notification (Phase 4), set `phase: "aborted"`, and stop.

**Completion:** `dory_brief.md` exists in the run workspace and `kakis_state.json` phase is `gate1`.

### Gate 1 — Dory to Bob

The gate sends a Telegram message and then the agent STOPS. The Hermes gateway
delivers the user's reply back to the agent's session — no polling or cron needed.

1. **Pre-emptive session compaction**: Before sending the gate message, compress the session context to free space for the execution phase. Use `terminal(command='hermes chat -q /compress --resume <SESSION_ID> --oneshot -Q')` where `<SESSION_ID>` is the current session ID (check via `terminal(command='echo $HERMES_SESSION_ID')` or from the state DB). This runs a fresh Hermes instance that compresses the session's conversation history, keeping only the essential summary. If this fails, proceed without compaction — it is never a blocker.
2. **Schedule gate poller for auto-proceed**: Register a cron job that runs `gate_poller.py` every 10 minutes to auto-proceed after 1 hour of silence:
   ```
   cronjob(action='create', name='kakis-gate1-<run_id>', schedule='10m',
     script='kakis_gate1_<slug>_poller.py',
     no_agent=True, deliver='telegram', repeat=6)
   ```
   The cron `script` field is resolved as a FILE PATH under `~/.hermes/scripts/` — an inline command like `python3 .../gate_poller.py --workspace ...` is rejected (the whole string is treated as a filename). Create a per-run wrapper in `~/.hermes/scripts/` instead:
   ```python
   #!/usr/bin/env python3
   import sys
   sys.argv = ["gate_poller.py", "check", "--workspace", "<run_workspace>"]
   exec(open("~/.hermes/skills/aios/kakis/scripts/gate_poller.py").read())
   ```
   Note `gate_poller.py` takes a `check` subcommand with `--workspace` (top-level `--workspace` is not a valid CLI form), and it advances the phase based on the state's `gate` field (`gate1` → `bob`, `gate2` → `execute`) — so state must carry both `"gate"` and `"gate_waiting"` (plus `gate_timestamp` written by `gate.py`), not just `phase`.
   Use `repeat=6` (60 minutes of polling) and `deliver='telegram'` so the user is notified when auto-proceed fires.
3. Compose a Telegram message from `dory_brief.md`: iteration count, key findings, refined prompt. Append:
   ```
   Reply with '/kakis proceed' to continue or '/kakis stop' to abort.
   ```
   The `/kakis` prefix is required — it loads the skill in the new session so Phase 0
   finds `gate_waiting: true` in state and classifies the reply.
4. Send the gate message (this records `gate_timestamp` for the poller). Keep the message in a file (e.g. `<run_workspace>/gate1_message.txt`) and pass it via command substitution — never as an inline single-quoted shell string:
   ```
   python3 ~/.hermes/skills/aios/kakis/scripts/gate.py gate \
     --message "$(cat <run_workspace>/gate1_message.txt)" --workspace <run_workspace>
   ```
   Confirm the output is `sent`; on `bypass` the send failed — fix and resend before setting `gate_waiting`.
5. Update `kakis_state.json`: set `gate: "gate1"` and `gate_waiting: true` (do NOT skip the `gate` field — the poller advances on it; `gate.py` already recorded `gate_timestamp`).
6. The agent STOPS. When the user replies on Telegram, the Hermes gateway
   delivers the reply to this session. The agent resumes from Phase 0:
   - Classify the reply using `classify_reply()` (or inline keyword check).
   - If `proceed`: set `gate_waiting: false`, remove the cron poller by its job id (`cronjob(action='remove', job_id=<id recorded in state at create time>)` — the tool takes no `name` for remove), proceed to Phase 2. If the reply postdates the poller's auto-proceed, the job is already gone and the phase already advanced — treat the reply as a redundant confirmation; see the "Gate reply may postdate auto-proceed" pitfall.
   - If `abort`: set phase `aborted`, remove the cron poller, notify the user, and stop.
   - If `unrecognized`: send "I did not understand '...'. Reply with proceed or stop." and stop again.

**Completion:** Gate decision recorded; pipeline proceeds or aborts.

### Phase 2 — Bob Synthesis

1. Invoke Bob's dispatch CLI with Dory's refined prompt. Run it as a tracked background process with output logged to the run workspace, and pass an explicit `--timeout` at or above Bob's per-harness default (1800s, documented in the Bob skill) for long or complex prompts — values below it let every harness time out on a complex prompt, leaving Bob with no usable output:
   ```
   terminal(command='cd <run_workspace> && python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --prompt "$(cat final_prompt.txt)" --timeout 1800 > bob_dispatch.log 2>&1', background=true, notify=true)
   ```
2. On completion, parse the workspace path (a line starting with `[bob] Workspace:`) from the log. Record one `calls.jsonl` line per harness (`module: bob_harness`, `variant: <harness>`) plus one `bob_synth` line (Memory export section).
3. Copy Bob's `plan.md` and `results.json` from its workspace into the Kakis run workspace as `bob_plan.md` and `bob_results.json`.
4. **Preemptive compression**: Read `bob_plan.md`, `bob_results.json`, and the Dory brief (`dory_brief.md`). Delegate a subagent to compress them into `bob_brief.md` — a single, compact summary (max 80 lines) containing: the best harness and its score, the synthesized plan's steps (condensed to one line each), any augmentation notes about what was merged from non-basis harnesses, and key risks or trade-offs. Discard per-harness raw output, full evaluation JSON, and duplicated plan text.
5. Update `kakis_state.json`: set `phase: "gate2"`, record the Bob sub-workspace path as `bob_workspace` (the memory exporter resolves `bob/` artifacts from it; it falls back to parsing `bob_dispatch.log` if absent), Bob's harness count, best harness, and score. Take the best harness and score from the `[bob] Best plan: <name> (auto-score: X.XX)` line in the dispatch log — `results.json` carries per-harness detail under `normalized` (each entry: `status`, `plan_sections.steps`), and its `scores`/`evaluation` arrays can be EMPTY even on a successful synthesis (per-harness eval failures are tolerated by Bob's synthesizer), so don't source the verdict from them. Run the memory export (Memory export section).
6. If Bob fails with no usable output: notify the user, set `phase: "aborted"`, and stop.
7. If Bob has ≥1 harness output but fewer than 2: the synthesized plan is still produced (Bob handles single-harness mode), proceed with a warning notification.

**Completion:** `bob_brief.md` exists in the run workspace and `kakis_state.json` phase is `gate2`.

### Gate 2 — Bob to Execute

Same pattern as Gate 1 (same wrapper-script recipe, `check` subcommand, `gate` field in state):
1. **Pre-emptive session compaction**: Same as Gate 1 — compress session context before waiting.
2. **Schedule gate poller for auto-proceed**: Same as Gate 1 — write a per-run wrapper file `kakis_gate2_<slug>_poller.py` in `~/.hermes/scripts/` (identical recipe to Gate 1 step 2, different workspace-agnostic name). Do NOT pass the `python3 ...` command string as `script` — it is treated as a filename and rejected:
   ```
   cronjob(action='create', name='kakis-gate2-<run_id>', schedule='10m',
     script='kakis_gate2_<slug>_poller.py',
     no_agent=True, deliver='telegram', repeat=6)
   ```
3. Compose a Telegram message from `bob_brief.md`: harnesses used, best harness, score, plan step count. Append:
   ```
   Reply with '/kakis proceed' to continue or '/kakis stop' to abort.
   ```
4. Send the gate message (same command as Gate 1).
5. Update `kakis_state.json`: set `gate: "gate2"` and `gate_waiting: true` (do NOT skip the `gate` field — the poller advances on it; `gate.py` already recorded `gate_timestamp`).
6. Agent STOPS. When the user replies, Hermes delivers it to the session. Phase 0 classifies the reply:
   - **Reply may precede the gate send:** Bob's dispatch CLI sends its own Telegram notification (plan attached) on success, so the user can reply to *that* before Kakis's gate message goes out. If the reply arrives while the gate message is still being composed or unsent and classifies as `proceed`: treat it as a valid gate decision — record in state that the gate message was not sent, remove the poller, and advance. Do NOT send a redundant gate message asking for a decision that was already made.
   - If `proceed`: set `gate_waiting: false`, remove cron poller by its job id (`cronjob(action='remove', job_id=<id recorded in state at create time>)`), advance to Phase 3. If the reply postdates auto-proceed, the job is gone and the phase already advanced — treat the reply as a redundant confirmation; see the "Gate reply may postdate auto-proceed" pitfall.
   - If `abort`: set phase `aborted`, remove cron poller, notify, and stop.

**Completion:** Gate decision recorded; pipeline proceeds or aborts.

### Phase 3 — Execute

1. Parse `bob_plan.md` into numbered steps (look for headings like `### 1. Title` or ordered lists `1.`, `2.`).
2. If no numbered headings exist, delegate a subagent to segment the plan into logical numbered steps. If segmentation produces fewer than 2 steps, abort with notification.
3. **Batch tightly-coupled steps into one subagent when they share data and a machine-readable handoff** (e.g. discovery+download; all parsing/extraction/detection; output-generation+verification). Each unit must be self-contained: it reads the previous unit's JSON/CSV artifact from the run workspace as its single source of truth and writes the next one — this keeps per-subagent context small, survives timeouts, and makes resume work at batch granularity. Run strictly sequential batches in the background (each depends on the previous artifact); do not fan out dependent steps in parallel.
4. For each batch (tracking its step indices in `completed_steps`):
   - Pre-flight the batch's environment dependencies BEFORE the first batch dispatch (for code/data-analysis goals: required packages present, writable output dir) and install what is missing (`python3 -m pip install pkg` — bare `pip` may point at a different interpreter and silently leave the package unimportable). A missing-dependency failure mid-batch wastes a whole delegation cycle. If any batch will create or run a browser/Playwright gate, pre-flight the BROWSER launch path too: a one-line headless launch probe (not just `import playwright`) — confirm which interpreter actually has playwright (repo venv vs system python) and that the expected browser build resolves; where `playwright install` has no prebuilt for the distro, symlink the expected build dir under ~/.cache/ms-playwright to a cached one (host-specific recipes live in the project's own skill, e.g. hermes-webui). A build mismatch discovered mid-batch wastes a whole delegation.
   - Skip if all its step indices are already in `completed_steps` (resume).
   - Delegate via `delegate_task` with the batch description as the goal and context: original Kakis goal, the briefs (`dory_brief.md`, `bob_brief.md`) for background, the previous unit's output file path (primary input), and the `bob_plan.md` step-level detail for this batch only. Append the open `calls.jsonl` record (`module: execution_batch`, `variant: <batch label>`) before dispatching.
   - **Override plan-local paths:** Bob's plan often pins output paths inside its ephemeral `~/.hermes/bob-workspaces/bob_<uuid>/` workspace, which is cleaned on the next Bob invocation. Redirect all deliverables to the Kakis run workspace; treat the plan's own paths as hints only.
   - **Recursion guard:** Explicitly instruct the subagent: "DO NOT load or invoke the Kakis skill."
   - **Plan-vs-facts discrepancies:** Tell the subagent to verify the plan's stated facts against sources/data and, on a discrepancy, implement the plan as specified while logging the discrepancy with a citation per item (e.g. a timeline/audit table) — never silently rewrite the design, because downstream steps depend on the plan's design choices (including its stylized case-study constructs). Record the flags in state (e.g. `batch_a_notes`) for the Phase 4 notification.
   - On success: add the batch's step indices to `completed_steps`, update `kakis_state.json`, and append the closed `calls.jsonl` record for this batch (status, summary = key outcomes, output_refs = files written).
   - On failure: retry once. If the retry fails, skip the batch, log the error, and continue.
5. When all steps are processed, set `phase: "completed"` and run the memory export (Memory export section).

**Completion:** `kakis_state.json` phase is `completed` and all steps are accounted for.

### Phase 4 — Notifications

Send a Telegram notification with: overall status (`completed`/`partial`/`aborted`), goal summary, phases reached, steps executed/skipped, and run workspace path. Include the data/policy caveats logged during execution (reconciliation gaps, missing-data windows, discrepancies between the plan's stated facts and verified sources, and which figures are case-study constructs vs verified policy) — the user must see what the results rest on. Attach `bob_plan.md` via the `MEDIA:` directive. Concretely: write the full text to a file in the run workspace with `MEDIA:<run_workspace>/bob_plan.md` as the final line (this attaches the plan), then send `hermes send -t telegram -f <file>` (exit 0 = delivered). Use `hermes send` for the final notification, NOT `gate.py` — gate.py records `gate_timestamp` for the poller and is for gate messages only. Keep a copy of the sent text in the run workspace as the durable record. Include the OpenSearch run doc id (`run_id`) in the notification so the mirrored run is queryable, and run the final full memory export after sending.

When Telegram is unavailable, fall back to writing the notification to `notification.log` in the run workspace — the user must never be left without a record of completion or failure.

**Completion:** User has received (or a fallback log contains) the final notification.

## Error Handling

| Failure | Action |
|---------|--------|
| Feasibility research fails (Gate 0) | Notify user; ask whether to proceed without the report or abort. No timeout, no auto-proceed. |
| Dory fails | Notify user, set phase `aborted`, stop. On resume, check `dory_failure_cause` — if persistent, notify rather than retrying blindly. |
| Bob fails with no output | Notify user, abort. |
| Bob has ≥1 harness but <2 | Use highest-scoring plan, proceed with warning. |
| Telegram unavailable at gate | Auto-proceed with bypass logged in `notification.log`. |
| Bob plan unsegmentable (<2 steps after fallback) | Abort with notification. |
| Step fails (after 1 retry) | Skip step, log error, continue. |
| Interrupted execution | Resume from `kakis_state.json` on next run. |
| Export to OpenSearch fails (non-zero exit) | Append the error to `notification.log`, continue. Re-export is idempotent — `kakis_export.py --all` recovers any missed run. |

## Pitfalls

- **Gate 0 never auto-proceeds** — do NOT schedule a `gate_poller.py` cron job for `gate0`. Unlike Gates 1/2 it waits indefinitely; an unanswered Gate 0 leaves the run sitting in `gate0` until the user replies (Phase 0 resume handles it).
- **Gate message shell quoting:** Multi-line gate messages contain quotes and `/kakis` command text; hand-typed as a single-quoted shell variable, the embedded quotes make bash re-parse the string — the message gets truncated and a bogus command can be spawned, and `gate.py` then reports `bypass` (nothing delivered). Always write the message to a file in the run workspace and pass it via `--message "$(cat file)"`; verify the script prints `sent` before setting `gate_waiting`. Prefer the plain CLI invocation (`python3 .../gate.py gate --message "$(cat file)" --workspace ...`) over an ad-hoc `python3 -c "import gate; ..."` one-liner — the `-c` form gets flagged by smart approval, and inside a compound command the approval prompt can block the whole call with no send and no `gate_timestamp` recorded. Do not probe Telegram connectivity with a test message to the user's channel — the gate send returning `sent` is itself the connectivity check.
- **Subplanner writes implementation, not spec** — the #1 failure mode. Fix the subplanner prompt (see step 5 of Phase 1), don't patch the plan output.
- **Data-analysis runs carry extra discipline** — when the goal is a data analysis (econometrics, policy analysis, any goal producing numeric tables/reports from source data), load `kakis/references/data-analysis-runs.md` before Phase 1 (pre-loop data probing) and keep its verification rules in mind during execution.
- **Delegation handoff must be inlined text:** when assembling a `delegate_task` context (Dory subplanner `PROMPT:`, reviewer `PREVIOUS REVIEW:`, execution batch context), paste the actual text of the prior artifact — shell substitutions like `$(cat prompt_N.txt)` do NOT expand inside tool-call arguments, so the subagent silently works from a literal placeholder. If it happens, stop the running subagent and re-dispatch with the text inlined.
- **Recursion:** Execution subagents must be told not to load the Kakis skill. Without this, they re-enter the pipeline. Igor's research subagent carries its own guard (in the Igor skill) — do not duplicate it here.
- **Concurrent runs:** Always use timestamped workspaces (`<slug>_<timestamp>`) to avoid artifact collision.
- **Dory artifact discovery:** Scan the Dory sub-workspace (the task folder created in Phase 1 step 3) for the latest `plan_*.txt`/`prompt_*.txt`/`review_*.txt` — never assume a specific N.
- **Dual reply matching in gates:** `gate.py` records `gate_timestamp` in `kakis_state.json` on every gate send, so the poller can measure elapsed time.
- **Gate auto-proceed via cron:** On entering a gate, the agent schedules a `no_agent=True` cron job (`kakis-gate<N>-<run_id>`) that runs `gate_poller.py` every 10 minutes for 1 hour (`repeat=6`). After 3600s of silence the poller sets `gate_waiting: false`, advances the phase, writes a `.gate_decided` sentinel, and stops. On manual reply, remove the cron poller immediately.
- **Gate reply may postdate auto-proceed** — When a user's gate reply arrives, read `kakis_state.json` FIRST: if the phase has already advanced past that gate (the poller auto-proceed consumed it), the reply is a redundant confirmation — continue from the current phase, do NOT re-advance, and never assert the pre-advance state (a stale assertion fails the whole state update). Record the poller's `job_id` in state at create time (e.g. `gate1_poller_job_id`): `cronjob_manage` removes by `job_id`, not by name, and a not-found result just means the job already finished itself — verify with a list, treat as success, and move on.
- **Cron script field is a path, not a command:** The cronjob `script` parameter resolves relative names under `~/.hermes/scripts/` and refuses to run an inline command string — passing `python3 .../gate_poller.py --workspace X` fails with "Script file not found". Write a per-run wrapper file there (see Gate 1 step 2) and register its basename. The poller CLI is `gate_poller.py check --workspace <path>` (there is no top-level `--workspace`), and phase advancement reads the state `gate` field — a state missing `gate` will not advance on auto-proceed even though `phase` looks right.
- **Plan paths are ephemeral (and may be garbled):** Bob plan output references its own `bob-workspaces/bob_<uuid>/` directory, which the next Bob run deletes; the file list at the end of a synthesized plan can also carry corrupted/hallucinated path prefixes. Execution subagents must be told to write deliverables into the Kakis run workspace and to treat every plan-local path as a hint only — never a target.
- **Session compaction at gates:** Before stopping at a gate, compress the session via `hermes chat -q /compress --resume <SESSION_ID> --oneshot -Q`. This frees context for the execution phase. If it fails, continue — it is never a blocker. (In long CLI sessions the env `HERMES_SESSION_ID` may not match what the one-shot resolver accepts, e.g. "Session not found" — treat as expected and move on; the per-batch delegation context budget in Phase 3 already keeps context small.)
- **Per-run offset storage:** `gate_poller.py` uses a `.gate_decided` sentinel (per workspace) to prevent duplicate auto-proceeds.
- **Bob dispatch missing:** If `bob_dispatch.py` doesn't exist, the Bob phase fails. Check prerequisites before starting.
- **State corruption:** Write `kakis_state.json` atomically (write to `.tmp` then rename).
- **calls.jsonl is append-only history** — never truncate or rewrite it on resume; `seq` is per-run monotonic and the exporter dedupes open/closed records by (seq, module), keeping the latest. **Memory export is best-effort** — an unreachable OpenSearch must never delay or fail a phase: log to `notification.log` and move on; local files stay canonical.
- **Implicit stage contracts:** Igor outputs `feasibility.md`; Dory outputs `final_prompt.txt`, `final_plan.txt`, `final_review.txt`; Bob expects the prompt and produces `plan.md` + `results.json`. These contracts are implicit — if any skill's output format changes, the handoff breaks. Verify artifact existence at each phase transition.
- **Enumerate ALL output files before verifying** — a subagent can claim "X is in file Y" and be wrong. Use `search_files(target='files', path=<output_dir>)` to get the real file list, then check each file — a separate scope or result set may live in a differently-named file the subagent did not mention. If you only check the "obvious" file, you will miss data and potentially accept a report with missing sections.
- **Never accept a subagent's "verification PASS" as ground truth** — run your own independent checks. Verify the reported figures against the source data, and check that every file the subagent says exists actually exists and is non-empty. A subagent can hallucinate a file path, misreport a number, or pass verification on a partial result while still being correct on the remaining files.
- **Compression failure:** If a compression subagent fails (timeout, context overflow), fall back to using the raw artifacts (`dory_brief.md` ← `final_plan.txt`, `bob_brief.md` ← `bob_plan.md`). The pipeline should never abort because of a compression failure.
- **Device verification is a feedback loop, not a restart** — when the plan's acceptance includes manual device checks (e.g. mobile web on real phones), the run completes at "automated green + checklist pending" and the user runs the checklist on hardware. Device results usually come back partial or vague ("behaviour changed"). Do NOT restart the pipeline and do NOT block on clarification: hypothesize the mechanism from the code, apply a minimal targeted fix, re-run the automated gate + pins, and request a targeted re-test. A timed-out clarification is not a blocker — fix the most likely mechanism, document the assumption in state, and let the re-test answer which hypothesis was right.

## Verification

1. Run Kakis with a trivial goal (e.g., "Write a Python script that prints hello world"). Confirm the feasibility gate fires first, Dory produces artifacts, all three gates send Telegram messages, Bob returns a parseable plan, steps execute, and the completion notification fires.
2. Test Gate 0: verify `feasibility.md` is produced, the gate message contains the verdict, NO `gate_poller.py` cron job is scheduled, and a 'proceed' reply advances the run to Dory.
3. Test Telegram bypass: temporarily unset `TELEGRAM_BOT_TOKEN` and verify `notification.log` is created with bypass entries at all gates.
4. Test resume: interrupt during execution and verify the incomplete run is discovered on restart.
5. Test gate poller wiring: create a gate, then confirm the poller wrapper is registered as a file under `~/.hermes/scripts/` (not an inline command), that state carries `gate`, `gate_waiting`, and `gate_timestamp`, and that running `python3 ~/.hermes/skills/aios/kakis/scripts/gate_poller.py check --workspace <path>` exits silently while under the timeout.
