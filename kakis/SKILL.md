---
name: kakis
description: "Orchestrate Dory→Bob→execute with Telegram decision gates."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [planning, multi-agent, delegation, orchestration, workflow]
    related_skills: [Dory, bob]
---

# KAKIS Workflow Skill

Chains three phases — iterative planning, best-of-breed synthesis, and step-by-step execution — separated by two Telegram decision gates where the user approves or aborts. Resumes on interruption; auto-proceeds gates after 1 hour of silence.

## When to Use

- The user provides a goal that benefits from multi-stage refinement: first plan iteratively (Dory), then synthesize across AI agents (Bob), then execute step by step.
- The user wants human-in-the-loop approval gates via Telegram before each major phase transition.
- The task is complex enough that a single-pass plan would be insufficient.

Don't use for:
- Simple tasks where one planning pass suffices — use `delegate_task` directly.
- When the user wants immediate execution without gates — follow the plan skill instead.

## Prerequisites

- Dory skill installed and functional (`skill_view(name='Dory')`).
- Bob skill installed at `~/.hermes/skills/loops/bob/` with at least one working harness (`skill_view(name='bob')`).
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

**Completion:** User has chosen a run path (fresh or resume) and `kakis_state.json` is loaded.

### Phase 1 — Dory Planning

1. Derive a task slug from the goal (lowercase, hyphens, max 40 chars). Create a run workspace: `~/.hermes/kakis-runs/<slug>_<timestamp>/`.
2. Initialize `kakis_state.json` with `phase: "dory"`, empty `completed_steps`, and the original goal.
3. Create a Dory sub-workspace: `~/workspace/kakis_<timestamp>/`.
4. Run the full Dory iterative planning loop on the user's goal statement. Follow the Dory skill exactly — delegate subplanner and subreviewer, check saturation, iterate until convergence.
5. **Specification-level output**: Dory's subplanner must stay at SPECIFICATION level — architecture, requirements, and edge cases only. Do NOT let it write implementation code, CLI invocations, JSON schemas, or API signatures. Add this to the subplanner context:
   ```
   CRITICAL: Stay at SPECIFICATION level. Do NOT write implementation code,
   CLI invocations, JSON schemas, API signatures, or file layout diagrams.
   Describe WHAT is needed, not HOW to build it.
   ```
6. After Dory saturates, discover its output artifacts by scanning the Dory workspace for the latest `plan_*.txt`, `prompt_*.txt`, and `review_*.txt` (sort filenames to find the highest N). Copy them to the KAKIS run workspace as `final_prompt.txt`, `final_plan.txt`, `final_review.txt`.
7. **Preemptive compression**: Read all Dory artifacts (`final_plan.txt`, `final_prompt.txt`, `final_review.txt`, and any prior `review_*.txt` that are still in the workspace). Delegate a subagent to compress them into `dory_brief.md` — a single, compact summary (max 60 lines) containing only: the goal statement, the final refined prompt, the key architectural decisions, and unresolved edge cases from the last review. The subagent should discard iteration history, repeated findings, and operational details.
8. Update `kakis_state.json`: set `phase: "gate1"`, record Dory artifact paths and iteration count.
9. If Dory fails: set `dory_failure_cause` in state, send failure notification (Phase 4), set `phase: "aborted"`, and stop.

**Completion:** `dory_brief.md` exists in the run workspace and `kakis_state.json` phase is `gate1`.

### Gate 1 — Dory to Bob

1. Compose a Telegram message summarizing Dory's output from `dory_brief.md`: iteration count, key findings from the final review, and the refined prompt.
2. Invoke `scripts/gate.py`:
   ```
   python3 ~/.hermes/skills/kakis/scripts/gate.py gate --message "<message>" --workspace <run_workspace> --run-id <run_id>
   ```
3. If the gate returns `proceed`, continue to Phase 2.
4. If `abort`, set `phase: "aborted"`, notify the user, and stop.
5. If `timeout`, auto-proceed to Phase 2 and log it.

**Completion:** Gate decision recorded; pipeline proceeds or aborts.

### Phase 2 — Bob Synthesis

1. Invoke Bob's dispatch CLI with Dory's refined prompt:
   ```
   python3 ~/.hermes/skills/loops/bob/scripts/bob_dispatch.py --prompt "$(cat final_prompt.txt)"
   ```
2. Parse stdout for the workspace path (a line starting with `[bob] Workspace:`).
3. Copy Bob's `plan.md` and `results.json` from its workspace into the KAKIS run workspace as `bob_plan.md` and `bob_results.json`.
4. **Preemptive compression**: Read `bob_plan.md`, `bob_results.json`, and the Dory brief (`dory_brief.md`). Delegate a subagent to compress them into `bob_brief.md` — a single, compact summary (max 80 lines) containing: the best harness and its score, the synthesized plan's steps (condensed to one line each), any augmentation notes about what was merged from non-basis harnesses, and key risks or trade-offs. Discard per-harness raw output, full evaluation JSON, and duplicated plan text.
5. Update `kakis_state.json`: set `phase: "gate2"`, record Bob's harness count and best harness (from `results.json`).
6. If Bob fails with no usable output: notify the user, set `phase: "aborted"`, and stop.
7. If Bob has ≥1 harness output but fewer than 2: the synthesized plan is still produced (Bob handles single-harness mode), proceed with a warning notification.

**Completion:** `bob_brief.md` exists in the run workspace and `kakis_state.json` phase is `gate2`.

### Gate 2 — Bob to Execute

1. Compose a Telegram message summarizing Bob's output from `bob_brief.md`: harnesses used, best harness, score, and plan step count.
2. Invoke `scripts/gate.py` with the same parameters as Gate 1.
3. If `proceed`, continue to Phase 3. If `abort`, set `phase: "aborted"`, notify, and stop. If `timeout`, auto-proceed.

**Completion:** Gate decision recorded; pipeline proceeds or aborts.

### Phase 3 — Execute

1. Parse `bob_plan.md` into numbered steps (look for headings like `### 1. Title` or ordered lists `1.`, `2.`).
2. If no numbered headings exist, delegate a subagent to segment the plan into logical numbered steps. If segmentation produces fewer than 2 steps, abort with notification.
3. For each step (tracking in `completed_steps`):
   - Skip if the step index is already in `completed_steps` (resume).
   - Delegate via `delegate_task` with the step description as the goal and full context (original KAKIS goal, `dory_brief.md`, `bob_brief.md`, `bob_plan.md`, and previous step results). Use the briefs (`dory_brief.md`, `bob_brief.md`) as the primary context to keep subagent context small; include `bob_plan.md` only for step-level detail.
   - **Recursion guard:** Explicitly instruct the subagent: "DO NOT load or invoke the kakis skill."
   - On success: add the step index to `completed_steps`, update `kakis_state.json`.
   - On failure: retry once. If the retry fails, skip the step, log the error, and continue.
4. When all steps are processed, set `phase: "completed"`.

**Completion:** `kakis_state.json` phase is `completed` and all steps are accounted for.

### Phase 4 — Notifications

Send a Telegram notification with: overall status (`completed`/`partial`/`aborted`), goal summary, phases reached, steps executed/skipped, and run workspace path. Attach `bob_plan.md` via the `MEDIA:` directive.

When Telegram is unavailable, fall back to writing the notification to `notification.log` in the run workspace — the user must never be left without a record of completion or failure.

**Completion:** User has received (or a fallback log contains) the final notification.

## Error Handling

| Failure | Action |
|---------|--------|
| Dory fails | Notify user, set phase `aborted`, stop. On resume, check `dory_failure_cause` — if persistent, notify rather than retrying blindly. |
| Bob fails with no output | Notify user, abort. |
| Bob has ≥1 harness but <2 | Use highest-scoring plan, proceed with warning. |
| Telegram unavailable at gate | Auto-proceed with bypass logged in `notification.log`. |
| Bob plan unsegmentable (<2 steps after fallback) | Abort with notification. |
| Step fails (after 1 retry) | Skip step, log error, continue. |
| Interrupted execution | Resume from `kakis_state.json` on next run. |

## Pitfalls

- **Subplanner writes implementation, not spec** — the #1 failure mode. Fix the subplanner prompt (see step 5 of Phase 1), don't patch the plan output.
- **Recursion:** Execution subagents must be told not to load the kakis skill. Without this, they re-enter the pipeline.
- **Concurrent runs:** Always use timestamped workspaces (`<slug>_<timestamp>`) to avoid artifact collision.
- **Dory artifact discovery:** Scan the workspace for the latest `plan_*.txt`/`prompt_*.txt`/`review_*.txt` — never assume a specific N.
- **Dual reply matching in gates:** `gate.py` uses two strategies — `reply_to_message_id` (Telegram reply chain) and run-token matching (e.g., `kakis-{run_id}` embedded in the gate message). This survives concurrent Telegram activity. If building custom gates, follow this same pattern.
- **Per-run offset storage:** `gate.py` stores `getUpdates` offsets per run in `~/.hermes/kakis-offsets/{run_id}.offset` to prevent race conditions between concurrent runs.
- **Telegram polling in subagent context:** The gate sends the message then polls the Bot API for replies. If polling is unavailable, the gate times out and auto-proceeds after 1 hour.
- **Bob dispatch missing:** If `bob_dispatch.py` doesn't exist, the Bob phase fails. Check prerequisites before starting.
- **State corruption:** Write `kakis_state.json` atomically (write to `.tmp` then rename).
- **Implicit stage contracts:** Dory outputs `final_prompt.txt`, `final_plan.txt`, `final_review.txt`; Bob expects the prompt and produces `plan.md` + `results.json`. These contracts are implicit — if either skill's output format changes, the handoff breaks. Verify artifact existence at each phase transition.
- **Compression failure:** If a compression subagent fails (timeout, context overflow), fall back to using the raw artifacts (`dory_brief.md` ← `final_plan.txt`, `bob_brief.md` ← `bob_plan.md`). The pipeline should never abort because of a compression failure.

## Verification

1. Run KAKIS with a trivial goal (e.g., "Write a Python script that prints hello world"). Confirm Dory produces artifacts, both gates send Telegram messages, Bob returns a parseable plan, steps execute, and the completion notification fires.
2. Test Telegram bypass: temporarily unset `TELEGRAM_BOT_TOKEN` and verify `notification.log` is created with bypass entries at both gates.
3. Test resume: interrupt during execution and verify the incomplete run is discovered on restart.
