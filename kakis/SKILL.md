---
name: kakis
description: "Research→Dory→Bob→execute orchestration with Telegram gates."
version: 0.3.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [planning, multi-agent, delegation, orchestration, workflow]
    related_skills: [Igor, Dory, bob]
---

# KAKIS Workflow Skill

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
- Bob skill installed at `~/.hermes/skills/aios/bob/` with at least one working harness (`skill_view(name='bob')`).
- Telegram configured in `~/.hermes/.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`).
- `hermes send --to telegram` delivers messages (exit code 0).

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
   - If `proceed`: set `gate_waiting: false`, advance to the next phase (gate0 → dory, gate1 → bob, gate2 → execute).
   - If `abort`: set phase `aborted`, notify the user, and stop.
   - If `unrecognized`: send "I did not understand '...'. Reply with '/kakis proceed' to continue or '/kakis stop' to abort." and stop again (leaving `gate_waiting: true`).

   APPROVE keywords: proceed, yes, go, continue, ok, okay, sure, do it, agree, approve, forward, next, yep, yea, yup
   REJECT keywords: stop, no, abort, cancel, halt, skip, nah, decline, reject, dont, don't, later, not now, pass

**Completion:** User has chosen a run path (fresh or resume) and `kakis_state.json` is loaded.

### Phase 0.5 — Feasibility Research (Gate 0)

Before invoking Dory, quickly assess whether the goal is feasible. Research ONLY: no planning, no code, no execution. This phase delegates to the **Igor** skill (orchestrated mode). Unlike Gates 1 and 2, this gate has NO timeout and NO auto-proceed — it waits indefinitely for the user's explicit proceed/abort.

1. Derive a task slug from the goal (lowercase, hyphens, max 40 chars). Create the run workspace `~/.hermes/kakis-runs/<slug>_<timestamp>/` and initialize `kakis_state.json` with `phase: "research"`, empty `completed_steps`, and the original goal.
2. **Invoke Igor in orchestrated mode**: load the Igor skill (`skill_view(name='Igor')`) and run its workflow, passing the run workspace path as Igor's `<workspace>`. Igor delegates the research subagent and writes `feasibility.md` into the run workspace, returning a GO / RISKY / NO-GO verdict and the report path. Igor does NOT send a Telegram message in orchestrated mode — KAKIS owns the gate below. (The research prompt template, strict rules, and the researcher's recursion guard all live in the Igor skill, not here.)
3. Confirm `feasibility.md` exists in the run workspace with a valid `=== FEASIBILITY: <GO|RISKY|NO-GO> ===` verdict line (Igor verifies this; re-check before the gate).
4. Write the gate message (verdict, key unknowns, top risks) to `<run_workspace>/gate0_message.txt`, appending the reply line below — never build a multi-line gate message as an inline shell string. Send it via `gate.py gate` (same as Gate 1) with `--message "$(cat <run_workspace>/gate0_message.txt)"` and confirm the command prints `sent` (a `bypass` means the send failed — fix and resend before waiting):
   ```
   Reply with '/kakis proceed' to continue or '/kakis stop' to abort.
   ```
5. Update `kakis_state.json`: set `phase: "gate0"`, `gate: "gate0"`, `gate_waiting: true`.
6. **No cron poller, no timeout**: do NOT schedule a `gate_poller.py` job for Gate 0. The gate waits indefinitely.
7. The agent STOPS. On reply (handled by Phase 0):
   - `proceed`: set `gate_waiting: false`, `phase: "dory"`, continue to Phase 1.
   - `abort`: set phase `aborted`, notify the user, and stop.
8. If the research subagent fails: record `research_failure_cause` in state, notify the user that feasibility research failed, and ask whether to proceed without the report or abort — same gate, no timeout. If proceeding, continue to Phase 1 without `feasibility.md`.

**Completion:** Gate 0 decision recorded; pipeline proceeds to Dory or aborts.

### Phase 1 — Dory Planning

1. Verify the run workspace exists (created in Phase 0.5). If it is missing (should only happen on a manual resume), derive the slug and create it.
2. Set `kakis_state.json` phase to `"dory"` (workspace and state were initialized in Phase 0.5).
3. Create a Dory sub-workspace: `~/workspace/kakis_<timestamp>/`.
4. Run the full Dory iterative planning loop on the user's goal statement. Follow the Dory skill exactly — delegate subplanner and subreviewer, check saturation, iterate until convergence.
5. **Specification-level output**: Dory's subplanner must stay at SPECIFICATION level — architecture, requirements, and edge cases only. Do NOT let it write implementation code, CLI invocations, JSON schemas, or API signatures. Add this to the subplanner context:
   ```
   CRITICAL: Stay at SPECIFICATION level. Do NOT write implementation code,
   CLI invocations, JSON schemas, API signatures, or file layout diagrams.
   Describe WHAT is needed, not HOW to build it.
   ```
   For data-analysis goals, also pass VERIFIED source-data facts into the subplanner context (resource ids, actual date windows, when each series/label/value first appears, what each category truly means) and instruct it to confirm them against the data rather than assume the prompt's stated values — see the "Dory data-analysis loops must verify the data" pitfall.
6. After Dory saturate, discover its output artifacts by scanning the Dory workspace for the latest `plan_*.txt`, `prompt_*.txt`, and `review_*.txt` (sort filenames to find the highest N). Copy them to the KAKIS run workspace as `final_prompt.txt`, `final_plan.txt`, `final_review.txt`.
7. **Preemptive compression**: Read all Dory artifacts (`final_plan.txt`, `final_prompt.txt`, `final_review.txt`, and any prior `review_*.txt` that are still in the workspace). Delegate a subagent to compress them into `dory_brief.md` — a single, compact summary (max 60 lines) containing only: the goal statement, the final refined prompt, the key architectural decisions, and unresolved edge cases from the last review. The subagent should discard iteration history, repeated findings, and operational details.
8. Update `kakis_state.json`: set `phase: "gate1"`, record Dory artifact paths and iteration count.
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
   - If `proceed`: set `gate_waiting: false`, remove the cron poller (`cronjob(action='remove', name='kakis-gate1-<run_id>')`), proceed to Phase 2.
   - If `abort`: set phase `aborted`, remove the cron poller, notify the user, and stop.
   - If `unrecognized`: send "I did not understand '...'. Reply with proceed or stop." and stop again.

**Completion:** Gate decision recorded; pipeline proceeds or aborts.

### Phase 2 — Bob Synthesis

1. Invoke Bob's dispatch CLI with Dory's refined prompt. Run it as a tracked background process with output logged to the run workspace, and raise the per-harness timeout above the 600s default for long or complex prompts (e.g. `--timeout 1200`) — at the default limit every harness can time out on a complex prompt, leaving Bob with no usable output:
   ```
   terminal(command='cd <run_workspace> && python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --prompt "$(cat final_prompt.txt)" --timeout 1200 > bob_dispatch.log 2>&1', background=true, notify=true)
   ```
2. On completion, parse the workspace path (a line starting with `[bob] Workspace:`) from the log.
3. Copy Bob's `plan.md` and `results.json` from its workspace into the KAKIS run workspace as `bob_plan.md` and `bob_results.json`.
4. **Preemptive compression**: Read `bob_plan.md`, `bob_results.json`, and the Dory brief (`dory_brief.md`). Delegate a subagent to compress them into `bob_brief.md` — a single, compact summary (max 80 lines) containing: the best harness and its score, the synthesized plan's steps (condensed to one line each), any augmentation notes about what was merged from non-basis harnesses, and key risks or trade-offs. Discard per-harness raw output, full evaluation JSON, and duplicated plan text.
5. Update `kakis_state.json`: set `phase: "gate2"`, record Bob's harness count, best harness, and score. Take the best harness and score from the `[bob] Best plan: <name> (auto-score: X.XX)` line in the dispatch log — `results.json` carries per-harness detail under `normalized` (each entry: `status`, `plan_sections.steps`), and its `scores`/`evaluation` arrays can be EMPTY even on a successful synthesis (per-harness eval failures are tolerated by Bob's synthesizer), so don't source the verdict from them.
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
   - If `proceed`: set `gate_waiting: false`, remove cron poller (`cronjob(action='remove', name='kakis-gate2-<run_id>')`), advance to Phase 3.
   - If `abort`: set phase `aborted`, remove cron poller, notify, and stop.

**Completion:** Gate decision recorded; pipeline proceeds or aborts.

### Phase 3 — Execute

1. Parse `bob_plan.md` into numbered steps (look for headings like `### 1. Title` or ordered lists `1.`, `2.`).
2. If no numbered headings exist, delegate a subagent to segment the plan into logical numbered steps. If segmentation produces fewer than 2 steps, abort with notification.
3. **Batch tightly-coupled steps into one subagent when they share data and a machine-readable handoff** (e.g. discovery+download; all parsing/extraction/detection; output-generation+verification). Each unit must be self-contained: it reads the previous unit's JSON/CSV artifact from the run workspace as its single source of truth and writes the next one — this keeps per-subagent context small, survives timeouts, and makes resume work at batch granularity. Run strictly sequential batches in the background (each depends on the previous artifact); do not fan out dependent steps in parallel.
4. For each batch (tracking its step indices in `completed_steps`):
   - Pre-flight the batch's environment dependencies BEFORE the first batch dispatch (for code/data-analysis goals: required packages present, writable output dir) and install what is missing (`python3 -m pip install pkg` — bare `pip` may point at a different interpreter and silently leave the package unimportable). A missing-dependency failure mid-batch wastes a whole delegation cycle.
   - Skip if all its step indices are already in `completed_steps` (resume).
   - Delegate via `delegate_task` with the batch description as the goal and context: original KAKIS goal, the briefs (`dory_brief.md`, `bob_brief.md`) for background, the previous unit's output file path (primary input), and the `bob_plan.md` step-level detail for this batch only.
   - **Override plan-local paths:** Bob's plan often pins output paths inside its ephemeral `~/.hermes/bob-workspaces/bob_<uuid>/` workspace, which is cleaned on the next Bob invocation. Redirect all deliverables to the KAKIS run workspace; treat the plan's own paths as hints only.
   - **Recursion guard:** Explicitly instruct the subagent: "DO NOT load or invoke the kakis skill."
   - **Plan-vs-facts discrepancies:** Tell the subagent to verify the plan's stated facts against sources/data and, on a discrepancy, implement the plan as specified while logging the discrepancy with a citation per item (e.g. a timeline/audit table) — never silently rewrite the design, because downstream steps depend on the plan's design choices (including its stylized case-study constructs). Record the flags in state (e.g. `batch_a_notes`) for the Phase 4 notification.
   - On success: add the batch's step indices to `completed_steps`, update `kakis_state.json`.
   - On failure: retry once. If the retry fails, skip the batch, log the error, and continue.
5. When all steps are processed, set `phase: "completed"`.

**Completion:** `kakis_state.json` phase is `completed` and all steps are accounted for.

### Phase 4 — Notifications

Send a Telegram notification with: overall status (`completed`/`partial`/`aborted`), goal summary, phases reached, steps executed/skipped, and run workspace path. Include the data/policy caveats logged during execution (reconciliation gaps, missing-data windows, discrepancies between the plan's stated facts and verified sources, and which figures are case-study constructs vs verified policy) — the user must see what the results rest on. Attach `bob_plan.md` via the `MEDIA:` directive.

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

## Pitfalls

- **Gate 0 never auto-proceeds** — do NOT schedule a `gate_poller.py` cron job for `gate0`. Unlike Gates 1/2 it waits indefinitely; an unanswered Gate 0 leaves the run sitting in `gate0` until the user replies (Phase 0 resume handles it).
- **Gate message shell quoting:** Multi-line gate messages contain quotes and `/kakis` command text; hand-typed as a single-quoted shell variable, the embedded quotes make bash re-parse the string — the message gets truncated and a bogus command can be spawned, and `gate.py` then reports `bypass` (nothing delivered). Always write the message to a file in the run workspace and pass it via `--message "$(cat file)"`; verify the script prints `sent` before setting `gate_waiting`. Prefer the plain CLI invocation (`python3 .../gate.py gate --message "$(cat file)" --workspace ...`) over an ad-hoc `python3 -c "import gate; ..."` one-liner — the `-c` form gets flagged by smart approval, and inside a compound command the approval prompt can block the whole call with no send and no `gate_timestamp` recorded. Do not probe Telegram connectivity with a test message to the user's channel — the gate send returning `sent` is itself the connectivity check.
- **Subplanner writes implementation, not spec** — the #1 failure mode. Fix the subplanner prompt (see step 5 of Phase 1), don't patch the plan output.
- **Dory data-analysis loops must verify the data** — For data-analysis goals, probe the source data read-only BEFORE the loop (row counts, actual date ranges, when each series/label/value first appears, what each category actually means) and inject the verified facts into the subplanner's Reference section with instructions to confirm rather than assume. Also require the plan to verify that the coefficient of interest VARIES within its estimation window: a treatment variable that is flat over a sub-window makes estimation on that sub-window rank-deficient — estimation window ≠ interpretation window (estimate where the variable varies; interpret on the relevant sub-period). WHY: unverified data assumptions burn iterations re-deriving window ends, label onsets, and category meanings, and an unexamined identification scope silently produces undefined coefficients that fail at execution time.
- **Delegation handoff must be inlined text:** when assembling a `delegate_task` context (Dory subplanner `PROMPT:`, reviewer `PREVIOUS REVIEW:`, execution batch context), paste the actual text of the prior artifact — shell substitutions like `$(cat prompt_N.txt)` do NOT expand inside tool-call arguments, so the subagent silently works from a literal placeholder. If it happens, stop the running subagent and re-dispatch with the text inlined.
- **Recursion:** Execution subagents must be told not to load the kakis skill. Without this, they re-enter the pipeline. Igor's research subagent carries its own guard (in the Igor skill) — do not duplicate it here.
- **Concurrent runs:** Always use timestamped workspaces (`<slug>_<timestamp>`) to avoid artifact collision.
- **Dory artifact discovery:** Scan the workspace for the latest `plan_*.txt`/`prompt_*.txt`/`review_*.txt` — never assume a specific N.
- **Dual reply matching in gates:** `gate.py` records `gate_timestamp` in `kakis_state.json` on every gate send, so the poller can measure elapsed time.
- **Gate auto-proceed via cron:** On entering a gate, the agent schedules a `no_agent=True` cron job (`kakis-gate<N>-<run_id>`) that runs `gate_poller.py` every 10 minutes for 1 hour (`repeat=6`). After 3600s of silence the poller sets `gate_waiting: false`, advances the phase, writes a `.gate_decided` sentinel, and stops. On manual reply, remove the cron poller immediately.
- **Cron script field is a path, not a command:** The cronjob `script` parameter resolves relative names under `~/.hermes/scripts/` and refuses to run an inline command string — passing `python3 .../gate_poller.py --workspace X` fails with "Script file not found". Write a per-run wrapper file there (see Gate 1 step 2) and register its basename. The poller CLI is `gate_poller.py check --workspace <path>` (there is no top-level `--workspace`), and phase advancement reads the state `gate` field — a state missing `gate` will not advance on auto-proceed even though `phase` looks right.
- **Plan paths are ephemeral (and may be garbled):** Bob plan output references its own `bob-workspaces/bob_<uuid>/` directory, which the next Bob run deletes; the file list at the end of a synthesized plan can also carry corrupted/hallucinated path prefixes. Execution subagents must be told to write deliverables into the KAKIS run workspace and to treat every plan-local path as a hint only — never a target.
- **Session compaction at gates:** Before stopping at a gate, compress the session via `hermes chat -q /compress --resume <SESSION_ID> --oneshot -Q`. This frees context for the execution phase. If it fails, continue — it is never a blocker. (In long CLI sessions the env `HERMES_SESSION_ID` may not match what the one-shot resolver accepts, e.g. "Session not found" — treat as expected and move on; the per-batch delegation context budget in Phase 3 already keeps context small.)
- **Per-run offset storage:** `gate_poller.py` uses a `.gate_decided` sentinel (per workspace) to prevent duplicate auto-proceeds.
- **Bob dispatch missing:** If `bob_dispatch.py` doesn't exist, the Bob phase fails. Check prerequisites before starting.
- **State corruption:** Write `kakis_state.json` atomically (write to `.tmp` then rename).
- **Implicit stage contracts:** Igor outputs `feasibility.md`; Dory outputs `final_prompt.txt`, `final_plan.txt`, `final_review.txt`; Bob expects the prompt and produces `plan.md` + `results.json`. These contracts are implicit — if any skill's output format changes, the handoff breaks. Verify artifact existence at each phase transition.
- **Enumerate ALL output files before verifying** — a subagent can claim "X is in file Y" and be wrong. Use `search_files(target='files', path=<output_dir>)` to get the real file list, then check each file. A separate scope (e.g. EV-era results) may live in a differently-named CSV (e.g. `*_2022plus_robustness.csv`) that the subagent did not mention. If you only check the "obvious" file, you will miss data and potentially accept a report with missing sections.
- **Never accept a subagent's "verification PASS" as ground truth** — run your own independent checks. Read the source tables (CSVs) and verify the report figures against them, check that every file the subagent says exists actually exists and is non-empty, and cross-check the negative-control verdicts against the raw coefficient signs. A subagent can hallucinate a file path, misreport a number, or pass verification on a partial result while still being correct on the remaining files.
- **String matching on numbers must handle Unicode** — reports and tables may use Unicode minus (U+2212, −) or ASCII hyphen-minus (-). When grep-ing for a coefficient like "-0.016", also check "−0.016" (with the Unicode minus) to avoid false negatives. Normalize with `tr -d '\u2212'` or `sed` before comparison if you want a single-match check.
- **Price/demand equations can split across files by scope** — downstream modules may write full-window results to `price_equation.csv` and EV-era results to `price_equation_2022plus_robustness.csv` (or similar). Always check for files with scope indicators in the name when verifying scope-specific results.
- **Dual scope naming convention** — when the pipeline supports dual-scope (full-window + interpretation/era window), expect: (1) main tables contain full-window specs; (2) separate `*_2022plus*` or `*_era_*` files contain the secondary scope; (3) the report must cite numbers from both scopes. Do not assume one file has everything.
- **Negative-control verdicts must be cross-checked against coefficient signs** — the subagent may report a NC "PASS" or "FAIL" based on its own logic. Verify independently: read the negative-control CSV, compute the sign/direction yourself, and compare against the verdict. A sign flip in the control category invalidates the causal claim regardless of what the subagent says.
- **Report figure tracing must verify every cited number** — the subagent claims to copy numbers "from tables at runtime." Verify this: pick 3-5 key coefficients (price equation dose, mediation indirect, negative-control %), read the raw table value, and confirm the report matches (allowing for rounding). If even one number is wrong, the rest are suspect.
- **Unicode minus sign (U+2212) vs ASCII hyphen-minus (U+002D)** — when doing string-based verification of report numbers, always check both characters. Python `in` operator will miss Unicode minus if you only search for ASCII minus. Use `text.replace('\u2212', '\u002D')` before checking.
- **Session compaction at gates** — Before stopping at a gate, compress the session via `hermes chat -q /compress --resume <SESSION_ID> --oneshot -Q`. This frees context for the execution phase. If it fails, continue — it is never a blocker. (In long CLI sessions the env `HERMES_SESSION_ID` may not match what the one-shot resolver accepts, e.g. "Session not found" — treat as expected and move on; the per-batch delegation context budget in Phase 3 already keeps context small.)
- **Compression failure:** If a compression subagent fails (timeout, context overflow), fall back to using the raw artifacts (`dory_brief.md` ← `final_plan.txt`, `bob_brief.md` ← `bob_plan.md`). The pipeline should never abort because of a compression failure.

## Verification

1. Run KAKIS with a trivial goal (e.g., "Write a Python script that prints hello world"). Confirm the feasibility gate fires first, Dory produces artifacts, all three gates send Telegram messages, Bob returns a parseable plan, steps execute, and the completion notification fires.
2. Test Gate 0: verify `feasibility.md` is produced, the gate message contains the verdict, NO `gate_poller.py` cron job is scheduled, and a 'proceed' reply advances the run to Dory.
3. Test Telegram bypass: temporarily unset `TELEGRAM_BOT_TOKEN` and verify `notification.log` is created with bypass entries at all gates.
4. Test resume: interrupt during execution and verify the incomplete run is discovered on restart.
5. Test gate poller wiring: create a gate, then confirm the poller wrapper is registered as a file under `~/.hermes/scripts/` (not an inline command), that state carries `gate`, `gate_waiting`, and `gate_timestamp`, and that running `python3 ~/.hermes/skills/aios/kakis/scripts/gate_poller.py check --workspace <path>` exits silently while under the timeout.
