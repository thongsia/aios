# AIOS — AI Orchestration Skillset for human-in-the-loop agentic workflows

_Disclaimer: This is very much a work-in-progress. It captures my research interest in an eco-sysñtem of skillful agents, where skills can be learned, honed, and recalled. The orchestration skillset is the beginning. The eventual goal is an AI Operating System -- the real AIOS._

AIOS is a skillset developed on Hermes Agent harness that chains AI agents into a semi-autonomous, human-in-the-loop planning-and-execution pipeline. Its aim is to turn a human curiosity or goal into results, in a high quality way. Every run is mirrored into OpenSearch as searchable long-term memory. 

Each skill is a `SKILL.md` (procedural memory loaded on demand by the agent)
plus optional scripts. No build step — clone into your skills directory and
the agent picks them up.

## Skills

| Skill | Version | What it does |
|---|---|---|
| [`kakis`](kakis/) | 0.5.0 | The orchestrator: Igor → Dory → Bob → Execute, with three Telegram decision gates. User supplies a goal, kakis does the rest. |
| [`igor`](igor/) | 1.0.0 | Feasibility research assistant: a single research subagent produces a GO / RISKY / NO-GO verdict. TODO: Recall |
| [`dory`](dory/) | 1.1.2 | Iterative plan-review loop (subplanner ↔ subreviewer) until theoretical saturation as a stop loop signal. Outputs specs as a prompt |
| [`bob`](bob/) | 1.0.1 | Fan-out/fan-in: dispatch a prompt to multiple AI coding agents to produce individual plans, synthesize a best-of-breed plan. Not merge, but pick the best and augment with the rest. |
| [`kakis_memory`](kakis_memory/) | 1.0.0 | Access protocol for the OpenSearch mirror — how any other agent discovers and queries pipeline history |
| [`prompt-writing`](prompt-writing/) | 1.0.0 | Production-grade prompt patterns (Anthropic canonical style) |

## The KAKIS pipeline

```
goal ──▶ Igor (feasibility) ──▶ GATE 0 ──▶ Dory (plan iterate) ──▶ GATE 1 ──▶ Bob (synthesize) ──▶ GATE 2 ──▶ Execute (batches) ──▶ notify
                (no timeout)        (user proceeds/aborts via Telegram)        (auto-proceed after 1h)      (auto-proceed after 1h)
```

- **Gates** are real decision points: the agent sends a Telegram message and
  stops; the user's reply (`/kakis proceed` / `/kakis stop`, optionally with a
  scope note) is classified on resume. Gates 1 and 2 auto-proceed after an
  hour of silence via a cron poller; Gate 0 waits indefinitely.
- **Resume**: all state lives in `<run_workspace>/kakis_state.json`; an
  interrupted run is discovered and resumed, skipping completed steps.
- **Execution** runs the synthesized plan as tightly-coupled subagent batches
  with machine-readable handoffs, each batch resuming from the previous
  batch's artifacts.

Run workspaces land in `~/.hermes/kakis-runs/<slug>_<timestamp>/` (override
the root with `KAKIS_RUNS_ROOT`).

## OpenSearch memory mirror

Every run — artifacts **and sub-module call traces** — is mirrored into
OpenSearch so other agents (any profile, any machine) can use pipeline
history as long-term memory.

### Indices (read via aliases; versioned indices evolve under them)

| Alias | Contents |
|---|---|
| `kakis_runs` | one doc per run: goal, phase, gate decisions, verdicts, workspace paths, counts |
| `kakis_artifacts` | one doc per file (run + `dory/` + `bob/` sub-workspaces); full text ≤ 512 KiB, else head + sha256 + canonical local path |
| `kakis_calls` | one doc per sub-module invocation: Igor, Dory planner/reviewer iterations, Bob per-harness outcomes, execution batches — the run's full call trace |
| `kakis_meta` | the self-describing layer: authoritative schema (`name=schema`), copy-pasteable query cookbook (`name=query-cookbook`), index map |

### How agents discover the schema

The memory is self-describing: `GET kakis_meta/_search` with
`term name=schema` returns the full JSON schemas, enums, and doc-id
conventions; `name=query-cookbook` returns ready-to-run queries. The
`kakis_meta` doc is **authoritative** — if the `kakis_memory` skill text
disagrees, the meta doc wins.

### Scripts (`kakis/scripts/`)

| Script | Purpose |
|---|---|
| `kakis_indices.py` | Create the four indices + aliases (idempotent) |
| `kakis_export.py` | Mirror one run (`<run_workspace>`) or all runs (`--all`) into OpenSearch. Deterministic doc ids → re-runs are idempotent upserts. Best-effort: the KAKIS pipeline never aborts on export failure |
| `kakis_publish_meta.py` | (Re)publish schema + query cookbook into `kakis_meta` |
| `test_kakis_export.py` | Unit tests for the exporter's pure functions (`python3 -m pytest test_kakis_export.py`) |
| `gate.py` / `gate_poller.py` | Gate messaging (records `gate_timestamp`) and the 1-hour auto-proceed poller |

### Configuration

| Setting | Default |
|---|---|
| `AIOS_OPENSEARCH` (process env, or `AIOS_OPENSEARCH=...` in `~/.hermes/.env`) or `--opensearch` (flag) | No default. Set `AIOS_OPENSEARCH=http://<your-opensearch>:9200` in `~/.hermes/.env` (see `.env.example` at the repo root). If unset, the scripts exit with a clear not-configured message and mirroring is skipped — runs continue normally |
| `KAKIS_RUNS_ROOT` (env) | `~/.hermes/kakis-runs` |

A run on a machine that cannot reach the cluster — or has not configured it
(`AIOS_OPENSEARCH` unset) — simply skips mirroring (reason logged to the run's
`notification.log`) — the pipeline is unaffected.

### Sub-module call trace: `calls.jsonl`

KAKIS appends one JSON record per delegation (Dory dispatch, Bob harness,
execution batch) to `<run_workspace>/calls.jsonl` — open record on dispatch,
closed record (status, timing, summary, outputs) on return. Legacy runs
without `calls.jsonl` get their calls reconstructed from the on-disk
artefacts (flagged `reconstructed` in `notes`).

### Write policy

Only `kakis_export.py` writes the data indices. All other agents are
read-only (there is no auth on the cluster; the convention is the guardrail).

## Repository layout

```
aios/
├── bob/                  fan-out/fan-in synthesis (scripts/bob_dispatch.py)
├── dory/                 iterative plan-review loop
├── igor/                 feasibility research
├── kakis/                orchestrator
│   ├── SKILL.md
│   ├── references/       schema-v1.json, query-cookbook.md (published into kakis_meta), data-analysis-runs.md
│   └── scripts/          gate, poller, index setup, exporter, meta publisher, tests
├── kakis_memory/         OpenSearch access protocol for other agents
└── prompt-writing/       prompt engineering patterns
```

## Installation

Clone into the Hermes skills directory (this repo *is* the `aios` category
folder):

```bash
git clone https://github.com/thongsia/aios ~/.hermes/skills/aios
```

The install is a live git working tree, not a snapshot: Dory's
Self-Improvement Loop commits skill improvements back into this repo (see
`dory/SKILL.md`, step S2), so the tree should never carry uncommitted skill
edits, and updates arrive via `git pull` (after a history rewrite:
`git fetch && git reset --hard origin/master`).

Prerequisites for a full KAKIS run: Telegram configured in `~/.hermes/.env`
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`) and at least one working Bob
harness. The OpenSearch mirror is optional — KAKIS runs fine without it.
A `.env.example` at the repo root lists every setting the scripts read.
