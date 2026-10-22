---
name: Igor
description: "Use for feasibility research: go/risky/no-go verdict."
version: 1.0.4
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [research, feasibility, go-no-go, pre-planning, multi-agent]
    related_skills: [Dory, Bob, Kakis]
---

# Igor — Feasibility Researcher

Assess whether a goal is buildable in the current environment before committing to full planning. Produces a compact feasibility report — a go / risky / no-go verdict, one-paragraph rationale, key unknowns, dependencies, and top risks (plus, where the task depends on external data, whether good data sources are available) — and saves it to `feasibility.md`. Research only: no planning, no code, no execution.

## When to Use

- The user wants a feasibility verdict (go / risky / no-go) before committing to build.
- The user asks "is this feasible?", "can we build X?", "assess this before we start", "feasibility check", or "is this buildable?"
- The user wants a quick blocker / dependency / risk scan of a goal.
- An orchestrator (Kakis) needs the feasibility phase as a subtask.

Don't use for:
- A full plan — use Dory (iterative plan-review) instead.
- Multi-harness plan synthesis — use Bob.
- Executing a goal — use the plan skill or direct execution.

## Invocation

Like Dory, Igor is a procedural skill — no CLI. Two modes:

- **Standalone:** the user asks for a feasibility assessment. The agent loads Igor and runs the workflow end-to-end, delivering a Telegram notification on completion.
- **Orchestrated:** Kakis (or another orchestrator) loads Igor mid-pipeline, passing its run workspace path. Igor writes `feasibility.md` into that workspace and does NOT send a standalone notification — the orchestrator sends its own gate.

## Architecture

Two roles, one orchestrator:

| Role | Who | How |
|------|-----|-----|
| **Orchestrator** | This agent | Detects mode, sets up workspace, delegates research, verifies artifact, delivers |
| **Researcher** | Leaf subagent | Runs the research: verifies local prerequisites, web-searches unknowns, writes feasibility.md |

The researcher is a single, isolated subagent. Unlike Dory (which loops a subplanner and a subreviewer until saturation), Igor is one-shot: one research subagent, no iteration loop. The orchestrator does no research itself — it only wires up and delivers. This keeps the orchestrator boundary clean and makes the research an isolated, delegable subtask.

## Workflow

### Step 0 — Detect mode and set up workspace

- **Standalone:** derive a slug from the goal (lowercase, hyphens, max 40 chars) and `mkdir -p ~/workspace/igor_<slug>_<timestamp>/`.
- **Orchestrated:** use the run workspace path supplied by the orchestrator. Do NOT create a new workspace.
- `<workspace>` below refers to whichever path was chosen.

### Step 1 — Dispatch Researcher

Call `delegate_task` with the goal and context below. The researcher writes its report to `<workspace>/feasibility.md`. Wait for the subagent to complete before proceeding.

If the goal references a host or service by an internal name (e.g. "my-server"), resolve its access details (ssh user@host:port, relevant credentials) and include them in the researcher context — the subagent does not share your memory or config notes, and a bare name costs it a failed lookup.

**Researcher goal:**
```
Assess the feasibility of the goal below. Write the report to <workspace>/feasibility.md.
```

**Researcher context:**
```
You are a feasibility researcher. Assess the feasibility of the goal, quickly.

RESEARCH TASKS:
- Identify required tools, APIs, credentials, and environment prerequisites. Verify
  which exist locally (read-only terminal checks are fine) and which are missing.
- Research any unknown domains or technologies via web search as needed.
- Where the goal depends on external data (datasets, feeds, price/market/news
  data, scraped content, training data), determine whether good data sources
  are available: name concrete sources; note access (auth, quota, cost), format,
  coverage, and freshness. If no good source exists, say so explicitly — missing
  data can be a hard blocker (NO-GO) or a soft one (RISKY).
- Identify blockers, dependencies, and risks.

VERDICT — choose exactly one, with a one-paragraph rationale:
- GO: no hard blockers; required tools/creds/env exist or are trivially obtainable;
  every external dependency is satisfiable in the current environment — including
  a usable data source when the goal depends on external data.
- RISKY: soft blockers or unknowns exist (missing cred, uncertain API, unknown
  dependency) but each has a plausible workaround. Proceed with noted caveats.
- NO-GO: a hard blocker cannot be satisfied here (required service absent with no
  alternative, impossible constraint, legal/permission block, or a dependency that
  does not exist).

REPORT FORMAT (max 40 lines):
=== FEASIBILITY: <GO|RISKY|NO-GO> ===

## Rationale
[one paragraph]

## Key Unknowns
- [bullet list]

## Dependencies
- [each dependency: present / missing / uncertain]

## Data Sources
[only when the goal depends on external data: one line per source — what it
provides, access, quality/coverage; or "no good source found: <gap and impact>"]

## Top Risks
1. [top 3, most severe first]

STRICT RULES:
- RESEARCH ONLY. Do NOT plan, do NOT write code, do NOT execute the goal.
- Do NOT load or invoke the Kakis (pipeline), Dory, or Bob skills.
- Do NOT modify any files other than writing feasibility.md.

Goal: <original goal>
```

### Step 2 — Verify the artifact

Confirm `<workspace>/feasibility.md` exists and contains a `=== FEASIBILITY:` line with a valid verdict (GO / RISKY / NO-GO). If the verdict line is missing or malformed, read the report and extract the closest valid verdict. If none is determinable, mark the verdict `RISKY` and note the uncertainty in Rationale. Never fabricate a verdict.

### Step 3 — Deliver

- **Standalone:** present the report to the user inline, then send a Telegram notification with the verdict, top risks, and the workspace path (by design — always send on standalone completion). Use `hermes send --to telegram -f <msgfile>` (reuses the gateway's TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL from ~/.hermes/.env). Write the body to a scratch file first to avoid shell-quoting issues, and put the attachment in the body as its own line `MEDIA: <workspace>/feasibility.md` — the attachment rides in the message text, not a CLI flag. Check the exit code: 0 = delivered; nonzero = surface the error, do not claim success.
- **Orchestrated:** return the verdict and report path to the orchestrator. Do NOT send a Telegram message — the orchestrator (Kakis) sends its own gate.

## Common Pitfalls

1. **Fabricated verdict.** If the researcher times out or returns no valid verdict, fall back to `RISKY` with the uncertainty noted — never invent a GO/NO-GO.
2. **Researcher drifts into planning or overflows the line cap.** The STRICT RULES forbid planning/code/execution and the report must be ≤ 40 lines, but the researcher often appends an extra reference section (e.g. a "deployment shape" command block) that pushes it over. The orchestrator owns the cap: trim the report to the verdict + Rationale/Unknowns/Dependencies/Risks sections before delivery, or re-dispatch with a stronger "research only" instruction.
3. **Recursion / re-entering the pipeline.** The researcher must not load Kakis, Dory, or Bob. Without the guard, a delegated subagent can re-enter the full pipeline.
4. **Double Telegram in orchestrated mode.** When Kakis invokes Igor, Igor must NOT send its own notification — Kakis sends the gate. A double message confuses the user. Gate the delivery on the mode (Step 3).
5. **Workspace collision.** Standalone uses `~/workspace/igor_<slug>_<timestamp>/`; orchestrated uses the orchestrator's run workspace. Never create a new workspace when an orchestrator already supplied one.
6. **Local checks go beyond read-only.** The researcher may run read-only terminal checks to verify prerequisites (e.g., `which opencode`, `test -f ~/.hermes/.env`) but must not install, modify, or create anything except feasibility.md.

## Verification

- [ ] Mode detected (standalone vs orchestrated) and the correct workspace used
- [ ] Researcher delegated via `delegate_task` with the goal and context above
- [ ] `feasibility.md` exists and has a valid `=== FEASIBILITY: <GO|RISKY|NO-GO> ===` line
- [ ] Verdict is GO, RISKY, or NO-GO (never fabricated; fallback is RISKY)
- [ ] Report has Rationale, Key Unknowns, Dependencies, Top Risks sections — plus a Data Sources section when the goal depends on external data
- [ ] Report is ≤ 40 lines
- [ ] Standalone: Telegram notification sent and exit code 0; Orchestrated: no notification
- [ ] Researcher did not load Kakis/Dory/Bob and did not write code or modify files
