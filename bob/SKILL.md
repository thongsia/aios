---
name: bob
description: "Fan-out/fan-in planning: dispatch a prompt to multiple AI coding agents, collect and synthesize a best-of-breed implementation plan."
version: 1.0.1
author: Hermes Agent
---

## Overview

Bob is a fan-out/fan-in planning orchestrator. Given a user prompt, it dispatches the prompt in parallel to multiple independent AI coding-agent harnesses, collects each harness's plan, normalizes them to a common schema, scores them, and synthesizes a single best-of-breed merged plan.

## Trigger

- `/bob "your prompt here"` — dispatches to all available harnesses and synthesizes
- `/bob cleanup` — removes the previous workspace directory

## Supported Harnesses

| Harness | Binary | Status |
|---------|--------|--------|
| Opencode | `opencode` | Primary |
| Hermes | `hermes` | Primary (uses bob-worker profile) |
| Qwen Code | `qwen` | Optional (skipped if not installed) |
| DeepSeek Harness | `dsh` | Optional (skipped if not installed) |

Missing harnesses are gracefully skipped. A minimum of 2 available harnesses is required for synthesis.

## Programmatic Invocation

```bash
# Run all available harnesses
python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --prompt "Build a REST API with FastAPI"

# Run specific harnesses only
python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --prompt "..." --harnesses opencode,hermes

# Custom timeout (default 1800s)
python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --prompt "..." --timeout 300

# Clean up previous workspace
python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --cleanup
```

This environment installs the skill under the `aios/` category (`~/.hermes/skills/aios/bob/`); if a path below looks wrong, resolve scripts relative to the skill's actual install directory.

## Configuration

`bob_dispatch.py` takes CLI flags only — there is no config-file loading:

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` / `-p` | — | User prompt to dispatch (required for a run) |
| `--timeout` | `1800` | Per-harness timeout in seconds |
| `--harnesses` | all available | Comma-separated list of harnesses to use (e.g. `opencode,hermes`) |
| `--min-success` | `1` | Minimum harnesses that must succeed |
| `--cleanup` | — | Remove the previous workspace and exit |

## Architecture

```
User prompt
    │
    ▼
┌─────────────┐
│ bob_dispatch │── Preflight: check harness availability, ensure bob-worker profile
└──────┬──────┘
       │ Fan-out (ThreadPoolExecutor)
       ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│Opencode  │ │  Hermes  │ │  Qwen    │ │   DSH    │
│ adapter  │ │ adapter  │ │ adapter  │ │ adapter  │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
     │             │             │             │
     ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────┐
│              normalizer.py (3-pass pipeline)         │
│  Pass 1: JSON parse → Pass 2: Headings → Pass 3: Raw│
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              scorer.py (non-LLM metrics)             │
│  Completeness (0.4) + Specificity (0.35) +           │
│  Feasibility (0.25) on 1-5 scale                    │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│        synthesizer.py (2-phase pipeline)        │
│                                                  │
│  Phase 1: Per-plan evaluation (N subprocesses)   │
│    → each subprocess sees ONE compact plan       │
│    → strengths/weaknesses per plan (JSON)        │
│    → best plan by auto-score (highest wins)      │
│    → ANSI/control-char repair for JSON output    │
│                                                  │
│  Phase 2: Augmentation (single subprocess)       │
│    → basis plan compact summary + strength       │
│      bullets from non-basis plans                │
│    → augmented final plan (JSON: overview,steps) │
│    → 2 retries on JSON extraction failure        │
│    → prompt truncated at 8K chars if needed      │
│                                                  │
│  Compact plans: overview truncated to 200 chars, │
│  steps/assumptions as structured text             │
│                                                  │
│  Fallback: basis plan + evaluation rationale     │
│  Single-plan: return as-is (zero LLM calls)      │
│  Returns: SynthesisResult(plan_text, metadata)   │
└─────────────────────────────────────────────────┘
                      │
                      ▼
              Synthesized plan output
```

## Recursion Guard

All Hermes invocations (adapter dispatch + synthesis) use:
- `HERMES_PROFILE=bob-worker` — dedicated profile with isolated session store
- `--ignore-rules` — prevents loading skills, AGENTS.md, memory
- `--max-turns 1` — prevents tool-calling loops

This ensures the bob skill does NOT load in any child Hermes process.

## Bob-worker Profile

The `bob-worker` profile is auto-created on first run (cloned from the default profile). It inherits the parent's model/provider config and `.env` credentials, so child Hermes calls work without additional setup.

## Workspace Isolation

Each invocation creates a temporary workspace under `~/.hermes/bob-workspaces/bob_<uuid>/`. Per-harness subdirectories get isolated HOME directories with copied config files. The previous invocation's workspace is cleaned up on the next run.

Output files per run:
- `plan.md` — synthesized best-of-breed plan with optional `## Augmentation Log` section showing what was incorporated from each non-basis harness
- `results.json` — raw normalized + scored results plus `evaluation` key with the full phase-1 evaluation JSON (strengths/weaknesses, selection rationale)
- `<harness>/` — per-harness raw output directories

## Partial Failure Tolerance

- If 2+ harnesses produce usable output (status `ok` or `partial`), synthesis proceeds with what's available
- If fewer than 2 are usable, the workflow aborts with per-harness error reasons
- Failed synthesis falls back to the highest-scoring individual plan

## Completion Notification

Upon successful synthesis, Bob sends a Telegram notification with:
- Summary message (harnesses used, success count, workspace path)
- The synthesized plan attached as `plan.md` (via `MEDIA:` directive)

The notification uses `hermes send --to telegram` and is silently skipped on failure (e.g. Telegram not configured).

## File Structure

```
~/.hermes/skills/aios/bob/
├── SKILL.md
├── scripts/
│   ├── bob_dispatch.py         # Main orchestrator
│   ├── adapters/
│   │   ├── __init__.py          # Registry
│   │   ├── base.py              # Abstract base class
│   │   ├── opencode_adapter.py  # Opencode CLI wrapper
│   │   ├── hermes_adapter.py    # Hermes CLI wrapper
│   │   ├── qwen_code_adapter.py # Qwen Code CLI wrapper
│   │   └── dsh_adapter.py       # DeepSeek Harness wrapper
│   ├── normalizer.py            # Three-pass output normalizer
│   ├── scorer.py                # Automated scoring metrics
│   ├── synthesizer.py           # Two-phase synthesis engine (evaluate → augment)
│   └── prompt_template.py       # Standardized plan prompt
└── references/
    └── harness_specs.md         # Per-harness CLI documentation
```
