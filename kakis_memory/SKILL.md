---
name: kakis_memory
description: "Use when any agent needs past KAKIS pipeline runs or plans."
version: 1.0.1
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [memory, opensearch, kakis, retrieval, long-term-memory]
    related_skills: [KAKIS, Dory, Bob, Igor]
---

# KAKIS Memory (OpenSearch)

## When to Use

- You need a past KAKIS run: its goal, feasibility verdict, final plan, execution results, or gate decisions.
- You are asked "what did we plan/decide/do about X" and X may have gone through the KAKIS pipeline.
- You need the sub-module call trace of a run (Dory iterations, Bob harness outcomes, execution batches, failures).
- You are the KAKIS orchestrator verifying that a run was mirrored correctly.

Don't use for in-flight runs (local `~/.hermes/kakis-runs/` is fresher), or for topics KAKIS never touched.

KAKIS pipeline runs are mirrored into a private-network OpenSearch cluster so any agent can search and retrieve pipeline history as long-term memory: goals, feasibility verdicts, Dory plans/iterations, Bob synthesis (per-harness outcomes), execution batch results, and gate decisions.

## Endpoint

- Base URL: a private-network address (no auth — trusted network). Resolve it from `AIOS_OPENSEARCH` (process env, or set in `~/.hermes/.env` — the kakis scripts read the same setting and exit with a clear not-configured message when it is unset, so mirroring is skipped rather than erroring the run). In the examples below: `OS="${AIOS_OPENSEARCH:-http://<your-opensearch>:9200}"`.
- Read via ALIASES only: `kakis_runs`, `kakis_artifacts`, `kakis_calls`, `kakis_meta`. Never versioned index names (`*_v1`) — they change with schema versions.
- **Write policy: READ-ONLY for all agents.** The only writer is `kakis_export.py` (the KAKIS pipeline). There is no auth, so this convention is the only guardrail — do not index, delete, or update docs in these indices.

## Schema discovery protocol (the contract)

Before running ad-hoc queries, discover the live schema — it is self-described inside OpenSearch:

```bash
OS="${AIOS_OPENSEARCH:-http://<your-opensearch>:9200}"   # or set AIOS_OPENSEARCH in ~/.hermes/.env

# 1. Fetch the authoritative schema (embedded JSON schemas for all doc shapes, enums, doc-id conventions, content policy)
curl -s "$OS/kakis_meta/_search" -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"name":"schema"}},"_source":["schema_version","body"]}'

# 2. Fetch the query cookbook (copy-pasteable recipes)
curl -s "$OS/kakis_meta/_search" -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"name":"query-cookbook"}},"_source":["body"]}'
```

**Authority rule:** the `kakis_meta` schema doc is the AUTHORITATIVE schema. If this skill's text disagrees with the live schema doc, the meta doc wins — act on the meta doc and patch this skill to match.

## Document model (summary — live schema wins)

- `kakis_runs` — one doc per run; id = `run_id`. Fields: goal, phase, status, feasibility_verdict, gates (decision/scope note per gate), dory_iterations, bob_best_harness/score, completed_steps, workspace paths, artifact/call counts.
- `kakis_artifacts` — one doc per file artefact; id = sha256(run_id|path). Paths: bare = run workspace, `dory/...` = Dory sub-workspace, `bob/...` = Bob sub-workspace. Text files ≤ 512KiB carry full `content`; larger/binary carry `head` (2KiB) + `sha256` + `original_path` (canonical local copy).
- `kakis_calls` — one doc per sub-module invocation; id = run_id|call|seq|module. Modules: igor, dory_planner, dory_reviewer, bob_harness (variant = harness name), bob_synth, execution_batch, compress. Sorted by `seq` = the run's full call trace.

## Retrieval patterns

1. **Find a run** — full-text over goal: `kakis_runs/_search` with `match` on `goal`; or list recent: sort `updated_at` desc.
2. **List its artefacts** — `kakis_artifacts/_search` with `term run_id`, sort by path; request `_source: [path, kind, size_bytes, mtime, head]` for cheap previews.
3. **Fetch content** — add `content` to `_source` for the specific path (final plans live at `final_plan.txt`; feasibility at `feasibility.md` — see the schema doc for the full kind enum).
4. **Call trace** — `kakis_calls/_search` with `term run_id`, sort `seq` asc. This shows every subplanner/reviewer iteration, every Bob harness outcome, and every execution batch — including failures (`status: failed|timeout`).
5. **Cross-run memory** ("what do we know about topic X") — search `kakis_runs.goal`, then pull artefacts for the matching run(s); for deep text search use `multi_match` over `kakis_artifacts.content`/`head`.

Full copy-pasteable recipes: `kakis_meta` doc `query-cookbook` (or `~/.hermes/skills/aios/kakis/references/query-cookbook.md` locally).

## Pitfalls

- **No auth, no write.** If a query errors with a missing index, you are hitting a versioned index name — re-discover via aliases.
- **content can be absent** by design (files > 512KiB or binary). Fall back to `head` + `original_path` (local canonical copy; reachable if you run on this host).
- **Reconstructed calls** (legacy runs) carry `reconstructed` in `notes`; they are filename-inferred, less precise than live `calls.jsonl` records.
- **Legacy timestamps**: pre-2026-10-14 naive timestamps are assumed +08:00 local.
- **This mirror lags the pipeline by one export** (exports run at each KAKIS phase transition + after the final notification). For an in-flight run, the local run workspace under `~/.hermes/kakis-runs/` is fresher.
