---
name: Dory
description: "Use for iterative plan-review cycles until saturation."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [planning, multi-agent, delegation, iterative-refinement, planner-loop]
    related_skills: [plan, write-prompt]
---

# Forgetful Planner

Orchestrate an iterative planning workflow that refines a user's request through repeated planning and review cycles until theoretical saturation is reached.

## When to Use

- User asks for a plan and wants it refined through review iterations
- The task is complex enough that a single-pass plan would miss edge cases
- User says "plan this," "create a plan," or "plan and review"
- You need a specification that has been stress-tested by an independent reviewer

Don't use for:
- Simple tasks where a single-pass plan suffices
- When the user wants execution, not planning — use the `plan` skill plus your normal execution workflow instead

## Architecture

Three roles, one orchestrator:

| Role | Who | How |
|------|-----|-----|
| **Orchestrator** | This agent | Runs the loop, delegates tasks, checks saturation |
| **Subplanner** | Leaf subagent | Generates a plan from the current prompt (fresh run) |
| **Subreviewer** | Leaf subagent | Reviews the plan, produces an improved prompt |

The subplanner always starts from scratch — it never sees previous plans. This is intentional: if the prompt cannot produce a correct plan on its own, the prompt is not good enough. The subreviewer's job is to find what the subplanner missed and tighten the prompt.

## Workflow

### Initialization

1. Derive a task folder name from the user's prompt: slugify the core subject by taking the first meaningful noun phrase (e.g. "build a REST API for user auth" → `rest-api-user-auth`, "redesign the landing page" → `landing-page-redesign`). Keep it short, lowercase, hyphen-separated, max 40 characters.
2. Create a working directory: `mkdir -p ~/workspace/<TASK_FOLDER>`
3. Clear previous artifacts: remove all `plan_*.txt`, `prompt_*.txt`, `review_*.txt` from that directory
4. Set `current_prompt` to the user's request
5. Set iteration counter `N = 1`

### Iteration Loop

Repeat until saturation (max 10 iterations):

#### Step 1 — Dispatch Subplanner

Call `delegate_task` with `goal` and `context` described below. The subplanner writes its plan to `~/workspace/<TASK_FOLDER>/plan_N.txt`.

Wait for the subagent to complete before proceeding.

**Subplanner goal:**
```
Generate an implementation plan from the following prompt. Write the plan to ~/workspace/<TASK_FOLDER>/plan_N.txt.
```

**Subplanner context:**
```
Iteration: N

PROMPT:
[current_prompt]

PLAN FORMAT:
=== PROMPT ===
[Paste the original prompt verbatim]

=== PLAN ===
## Overview
[One-paragraph summary of what will be built]

## Steps
1. [Step title]
   [Detailed description — use pseudo-code and command outlines, not complete shell scripts]
2. [Next step]
   ...

## Assumptions
[List any assumptions made]

## Output Files
[List files that will be created or modified]

CORE RULES:
- Fresh run: treat this prompt as the first and only request. Do not assume prior context.
- Self-sufficient: if the prompt is ambiguous, choose the most reasonable option. Do not ask questions.
- Spec-level detail, not full implementation: provide enough detail for a developer to implement, but avoid writing complete shell scripts or production-ready code. Use pseudo-code, command outlines, and file structure descriptions.
```

**Note:** the subagent only needs `file` read/write. `delegate_task` has no per-call toolset parameter, so the child inherits the orchestrator's toolsets (which include `file`); no extra toolsets are required.

#### Step 2 — Dispatch Subreviewer

Call `delegate_task` with `goal` and `context` described below. The subreviewer writes two files: `~/workspace/<TASK_FOLDER>/prompt_N.txt` (improved prompt) and `~/workspace/<TASK_FOLDER>/review_N.txt` (review summary).

Wait for the subagent to complete before proceeding.

**Subreviewer goal:**
```
Review the plan at ~/workspace/<TASK_FOLDER>/plan_N.txt and produce an improved prompt at ~/workspace/<TASK_FOLDER>/prompt_N.txt and a review summary at ~/workspace/<TASK_FOLDER>/review_N.txt.
```

**Subreviewer context:**
```
Iteration: N

PLAN TO REVIEW: ~/workspace/<TASK_FOLDER>/plan_N.txt

PREVIOUS REVIEW: [contents of ~/workspace/<TASK_FOLDER>/review_(N-1).txt if N > 1, otherwise "None — this is the first review."]

ORIGINAL PROMPT:
[current_prompt — for reference to extract the goal statement]

CORE RULES:

1. Review specs, not code. You are reviewing a PLAN, not implemented code. Focus on missing requirements, incorrect technical assumptions, incomplete or contradictory specifications, and architecture or design gaps. DO NOT audit implementation syntax (sed patterns, grep flags, shell variable scoping, exit codes, file permissions in scripts). DO NOT find bugs in code snippets unless they indicate a missing specification. If a code snippet has a bug, flag the missing requirement that would prevent it, not the bug itself.

2. Severity-aware findings. Categorize each finding as Critical, High, or Low. After iteration 3, report only Critical and High findings. Low findings belong in code review during implementation.

3. Verify previous fixes. If a previous review exists, explicitly verify that ALL findings from it are addressed in the current plan. Any unfixed issue must be re-reported.

4. Extract the goal statement. The goal statement is the paragraph beginning with "Goal" (typically the first paragraph of the original prompt). If the original prompt has no such "Goal" paragraph, synthesize a concise one-sentence goal from the request and place it first. Preserve the goal statement (original or synthesized) verbatim in the improved prompt. Everything after it is specifications and is fully modifiable.

5. Rewrite specs from scratch with a line budget. Retain ONLY the goal statement from the original. Rewrite all specifications from scratch based on your review findings. Keep the total improved prompt under 100 lines. Do NOT accumulate a "CRITICAL BUGS TO AVOID" or similar negative-constraint section. Encode lessons learned as positive requirements. Consolidate related specs. Drop specs that are redundant, vague, or implied by other specs.

6. Write concise, high-level specs. Describe what is needed, not how to implement it. Avoid naming specific files, functions, or data structures. Use short phrases or bullet points.

7. Final review mode. If N >= 5, only report issues that would cause the solution to fail at runtime or violate core policy/requirements. Minor implementation issues, style concerns, and low-probability edge cases should NOT be reported. If the plan covers all requirements, report: "No new issues — spec is complete."

8. Maximum 5 new specifications per iteration. If you find more than 5 gaps, prioritize the most critical ones and drop the rest.

9. Apply prompt-writing patterns from the write-prompt skill. When writing the improved prompt, follow these principles: describe the outcome, not the steps; give the agent a way to verify its own work (tests, build, comparison); point at references when possible (existing patterns, examples); state measurable targets for performance/coverage goals; say how the answer should be delivered (format, audience). The improved prompt should follow the anatomy: Goal + Reference + Constraint + Verification + Output format.

OUTPUT FORMAT for prompt file:
=== IMPROVED PROMPT (Iteration N) ===
[Goal paragraph preserved verbatim]

[Concise, high-level specifications rewritten from scratch]

OUTPUT FORMAT for review file:
=== REVIEW SUMMARY (Iteration N) ===

## Findings
[List of issues, gaps, or improvements identified with severity]

## Previous Findings Verified
[For each finding from the previous review: FIXED or UNFIXED]

## New Specifications Added
[List of new specifications added this iteration (max 5)]

## Rationale
[Brief explanation of key decisions]
```

**Note:** the subagent only needs `file` read/write. `delegate_task` has no per-call toolset parameter, so the child inherits the orchestrator's toolsets (which include `file`); no extra toolsets are required.

#### Step 3 — Check Theoretical Saturation

Read `~/workspace/<TASK_FOLDER>/prompt_N.txt`.

- If `N == 1`: always continue
- If `N > 1`:
  1. Compare the new prompt against `current_prompt`
  2. Extract only the NEW specification lines (not rewording, rationale, or bug callouts)
  3. Categorize each new spec: structural design (architecture, requirements, edge cases) vs operational detail (file permissions, error codes, grep flags, shell syntax, portability)
  4. **Declare saturation if:**
     a) New spec count is 2 or fewer AND all are operational details, OR
     b) 2+ consecutive iterations have added only operational details, OR
     c) The subreviewer reports "No new issues — spec is complete"
- If `N >= 10`: trigger the Self-Improvement Loop (see below)

#### Step 4 — Decide

- **Not saturated**: set `current_prompt` to the new prompt, increment N, repeat from Step 1
- **Saturated**: go to Final Output
- **N >= 10 (limit reached)**: go to Self-Improvement Loop

### Self-Improvement Loop

When N >= 10 without reaching theoretical saturation, the loop itself has a design flaw. Do not stop — improve the skill and restart from scratch.

#### Step S1 — Post-Mortem Analysis

Read ALL artifacts:
- Every `review_N.txt` (iterations 1-10): what findings persisted? what kept getting missed or re-missed?
- Every `prompt_N.txt` (iterations 1-10): did the prompt inflate, drift, or fail to consolidate?
- Every `plan_N.txt` (iterations 1-10): did the subplanner consistently miss the same areas?

Then dispatch a **Sub-Analyst** subagent to diagnose the root cause:

**Sub-Analyst goal:**
```
Analyze the design iteration loop artifacts and diagnose why saturation was not reached in 10 iterations. Write the diagnosis to ~/workspace/<TASK_FOLDER>/postmortem.txt.
```

**Sub-Analyst context:**
```
The design loop ran 10 iterations without reaching theoretical saturation. Analyze the artifacts to find out WHY.

ARTIFACTS:
- Plans: ~/workspace/<TASK_FOLDER>/plan_1.txt through plan_10.txt
- Reviews: ~/workspace/<TASK_FOLDER>/review_1.txt through review_10.txt
- Prompts: ~/workspace/<TASK_FOLDER>/prompt_1.txt through prompt_10.txt

DIAGNOSIS QUESTIONS — answer each one:

1. SUBREVIEWER FAILURE: Did the subreviewer keep finding the same class of issues without ever resolving them? Were findings stuck in a cycle (e.g., always flagging the same missing edge case that the prompt tried to address but the subplanner kept misinterpreting)?

2. SUBPLANNER BLIND SPOT: Did the subplanner consistently miss the same areas regardless of prompt improvements? If so, what capability gap does this suggest?

3. PROMPT DEGRADATION: Did the prompt grow beyond its 100-line budget? Did it accumulate contradictory specs? Did the subreviewer fail to consolidate and rewrite from scratch?

4. SEVERITY GATE FAILURE: After iteration 3, should the subreviewer have only reported Critical/High findings? If it kept reporting Low-severity issues, that is the reviewer's fault — the skill should enforce the gate more strictly.

5. SATURATION CHECK FAILURE: Was the saturation check too aggressive (stopping early on operational details that were actually structural) or too lenient (continuing when the prompt had genuinely converged)?

6. TASK COMPLEXITY: Is this genuinely a task that requires more than 10 iterations, or does the prompt architecture need a fundamental change (e.g., the task needs to be decomposed into sub-tasks)?

CONCLUSION:
Write a concise diagnosis (max 30 lines) with:
- ROOT CAUSE: [the primary reason saturation was not reached]
- CONTRIBUTING FACTORS: [secondary issues]
- SKILL IMPROVEMENTS: [specific changes to the Dory skill that would prevent this next time]
```

**Note:** the subagent only needs `file` read/write. `delegate_task` has no per-call toolset parameter, so the child inherits the orchestrator's toolsets (which include `file`); no extra toolsets are required.

Wait for the Sub-Analyst to complete.

#### Step S2 — Apply Skill Improvements

Read `~/workspace/<TASK_FOLDER>/postmortem.txt`. Extract the `SKILL IMPROVEMENTS` section. Apply targeted patches to the `Dory` skill itself via `skill_manage(action='patch', name='Dory')`. Typical fixes include:

- **Stricter severity gates**: If the reviewer kept reporting Low findings, add explicit instructions to stop at Critical/High earlier.
- **Tighter prompt consolidation**: If the prompt inflated, reinforce the 100-line budget and ban on negative constraints.
- **Subplanner guidance**: If the subplanner had a consistent blind spot, add a specific instruction in the subplanner context to address it.
- **Saturation check tuning**: If the saturation check was too lenient or too aggressive, adjust the thresholds.
- **Task decomposition hint**: If the task is inherently too complex for a single loop, add instructions to decompose it into sub-tasks.

**Persist the improvement — never leave it as an uncommitted local edit.** The patch above modifies the installed skill file in place. If the install is a git working tree (`git -C <skill_dir> rev-parse --is-inside-work-tree`; true for the documented clone install), commit the change on the spot: `git -C <skill_dir> commit -am "dory: self-improvement after <TASK_FOLDER> — <one-line summary> (postmortem: <path>)"`, and push if a remote exists. An uncommitted patch is invisible to future clones, lost on the next reset, and can block or be silently discarded by the next pull; the commit plus the postmortem reference is the reviewable record of what the loop learned (revert it with `git revert` if the change proves harmful). For a non-git (copy) install, append the applied patch and a one-line postmortem summary to `<TASK_FOLDER>/skill_improvements_pending.md` so the owner can port it into the canonical repo.

#### Step S3 — Restart From Scratch

1. Clear all artifacts in `~/workspace/<TASK_FOLDER>/` (remove `plan_*.txt`, `prompt_*.txt`, `review_*.txt`, `postmortem.txt`)
2. Reload the updated `Dory` skill via `skill_view(name='Dory')` to confirm changes
3. Inform the user:

```
=== SELF-IMPROVEMENT COMPLETE ===

The design loop hit the 10-iteration limit. A post-mortem was performed and the skill was patched.

Key diagnosis: [ROOT CAUSE from postmortem]

Skill improvements applied:
[List of patches made]

Restarting the task from scratch with the improved skill...
```

4. Reset `N = 1`, set `current_prompt` to the original user request, and begin the Iteration Loop again from Step 1.

### Final Output

When saturation is reached:

1. Load the `write-prompt` skill to review the final prompt quality
2. Read the final plan from `~/workspace/<TASK_FOLDER>/plan_N.txt`
3. Read the final prompt from the last `prompt_N.txt`
4. Apply write-prompt principles: verify the prompt describes outcomes not steps, includes verification criteria, references existing patterns, states measurable targets, and specifies output format
5. Present to the user:

```
=== PLANNING COMPLETE ===

Iterations: N

=== FINAL PROMPT ===
[Content]

=== FINAL PLAN ===
[Content]

ARTIFACTS: ~/workspace/<TASK_FOLDER>/
```

6. Send a Telegram notification with the summary (by design — always send this on completion):

Copy the final prompt and plan to `.md` attachments, then deliver with `hermes send` via the terminal tool. This reuses the gateway's Telegram credentials (TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL in ~/.hermes/.env) and works in any session type (CLI, gateway, cron) without a running gateway. If the in-session `send_message` tool is available it may be used instead, but `hermes send` is the portable path that always works. Check the exit code: 0 = delivered; nonzero = surface the error, do not claim success.

Steps:
  a) Copy artifacts to `.md` for attachment:
     ```
     cp ~/workspace/<TASK_FOLDER>/plan_N.txt ~/workspace/<TASK_FOLDER>/final_plan.md
     cp ~/workspace/<TASK_FOLDER>/prompt_N.txt ~/workspace/<TASK_FOLDER>/final_prompt.md
     ```
  b) Send with `hermes send`, attaching both `.md` files via `MEDIA:` syntax:

     ```
     hermes send --to telegram "Planning complete for <TASK_FOLDER>.

Iterations: N
Artifacts: ~/workspace/<TASK_FOLDER>/
  - plan_N.txt (final plan)
  - prompt_N.txt (final prompt)
  - review_N.txt (final review)

See attached files for the final plan and prompt.
MEDIA:~/workspace/<TASK_FOLDER>/final_plan.md
MEDIA:~/workspace/<TASK_FOLDER>/final_prompt.md"
     ```

     The `MEDIA:<path>` directive sends the file as a document attachment in the Telegram message. Include it on its own line within the message body.

## Common Pitfalls

1. **Subreviewer drifts into code review.** The subreviewer is explicitly instructed to review specs, not code. If it starts finding `grep -P` portability issues, the prompt is not enforcing the constraint strongly enough. This is covered by rule 1 in the subreviewer context.

2. **Prompt inflates monotonically.** The 100-line budget and ban on negative-constraint sections prevent this. If the prompt grows past 100 lines, the subreviewer is not consolidating — re-read rule 5.

3. **Loop runs to 10 iterations without converging.** Triggers the Self-Improvement Loop: a Sub-Analyst diagnoses why, the skill is patched, and the task restarts from scratch with the improved skill. This should only happen on genuinely complex tasks. If it happens twice, the task likely needs to be decomposed into smaller sub-tasks.

4. **Subplanner misses previous fixes.** This is expected — the subplanner is a fresh run. The subreviewer catches regressions (rule 3: verify previous fixes) and re-reports them. The prompt tightens until it's precise enough to prevent the regression.

5. **Token cost.** Each iteration spawns two subagents carrying the full prompt. For simple tasks, 3-4 iterations is enough. For complex tasks, the severity gates (iter 3) and final review mode (iter 5) naturally drive convergence.

## Verification Checklist

- [ ] Task folder name derived from prompt (slugified, lowercase, hyphenated, max 40 chars)
- [ ] Working directory created and cleaned under ~/workspace/<TASK_FOLDER>/
- [ ] Subplanner receives only current prompt (no previous plan)
- [ ] Subreviewer receives previous review summary for regression checking
- [ ] Saturation check uses delta significance, not full-text comparison
- [ ] Operational-only iterations trigger early saturation
- [ ] Final output presents both final prompt and final plan
- [ ] Maximum 10 iterations enforced
- [ ] Self-Improvement Loop triggers at N >= 10 (Sub-Analyst dispatched, skill patched, task restarted)
- [ ] Postmortem identifies root cause and contributes concrete skill improvements
- [ ] Telegram notification sent with summary when planning complete
