---
name: aios-repo-maintenance
description: "Maintain the aios skillset repo: fixes, sync, republish."
version: 0.2.5
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [aios, maintenance, documentation, opensearch, sync]
    related_skills: [repo-writeup-review]
---

# aios Repo Maintenance

Apply fixes to the aios skillset repo (docs, skill files, scripts) and keep all three copies consistent: the git repo, the live skill install, and the published `kakis_meta` docs.

## Layout (fixed)

- **Repo** (edit here, then push): `~/workspace/refs/aios`, branch `master`.
- **Install**: `~/.hermes/skills/aios` — a git clone of the repo; the live skills this machine loads.
- **Published docs**: OpenSearch alias `kakis_meta` (docs `schema/v1`, `query-cookbook/v1`, `index-map/v1`), whose bodies are `kakis/references/schema-v1.json`, `kakis/references/query-cookbook.md`, and the index map. Writer: `kakis/scripts/kakis_publish_meta.py`. Endpoint: env var `AIOS_OPENSEARCH` (or `~/.hermes/.env`), else `--opensearch http://192.168.18.101:9200`.

## Sync before editing

The repo copy lags origin/master — the user pushes from other machines/sessions, so the remote advances between sessions. Before the first edit: `git status --short` must be clean (inspect and capture uncommitted work before any sync), then `git fetch -q origin && git merge --ff-only origin/master`. If the fast-forward fails, stop and report the divergence — never force-reset or rebase the edit copy.

## Setup audit (env, endpoints, harnesses)

When asked whether the skillset is set up to run (env, IPs, harnesses), verify in this order — a file existing is not the same as a setting being live:

1. **Env keys** in `~/.hermes/.env`: `AIOS_OPENSEARCH` (kakis mirror), `AIOS_QWEN_BASE_URL` + `AIOS_QWEN_MODEL` (Bob's qwen endpoint), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_HOME_CHANNEL` (gates, notifications). Per-machine values belong in this file, never in a session export: a missing var fails as a silent no-op (the export skips mirroring, qwen drops its OPENAI_* injection) instead of an error, so absence is only found by grepping for the key.
2. **Endpoints**: `curl` the OpenSearch root and `_cat/aliases/kakis_*` (expect runs/artifacts/calls/meta), and the LLM endpoint's `/v1/models`. A harness 404ing on a model name means the config's model id drifted from the served id — fix the id; display names are cosmetic, ids go on the wire.
3. **Harness binaries**: `command -v` each of `opencode hermes qwen dsh` in a NON-interactive shell. rc-file PATH exports (`~/.bashrc`) do not apply there, and Bob's preflight uses `shutil.which` on the dispatcher's PATH — a binary visible under interactive `bash -ic` but missing from `command -v` is silently skipped. Fix: symlink into an always-on-PATH dir (e.g. `~/.local/bin`).
4. **Harnesses actually work**: per-harness one-word live test plus one single-harness `bob_dispatch.py` end-to-end — full copy-paste recipe in `references/harness-verification.md`.
5. **Three-way sync**: repo + install `git status` clean, `HEAD == origin/master`, README version table matches every frontmatter `version`.

## Procedure

1. Re-verify every item in the fix list against the CURRENT files and code before editing. A fix list is a set of hypotheses: items go stale between review and application (a file's claimed state may have moved), and a "remove it or implement it" item may already be implemented — the harness auto-registers a `/<name>` slash command from each skill's frontmatter `name` (lowercased) and preloads the skill on invocation, so documented `/name` triggers are real. Where the evidence indicates, generalize the fix to its full scope (a frontmatter-consistency gap applies to every skill in the set, not just the ones named).
2. Ground every doc claim in code before writing the fix: read the parser `default=` values and the actual branch logic. A code comment that contradicts the code is stale — the code wins; never copy a comment's claim into a doc.
3. Edit with targeted `patch` old/new pairs, not whole-file rewrites; a failed patch returns the exact current text it nearly matched, which is the fastest way to re-read a section.
4. Mechanical word normalizations (e.g. spelling variants) across the repo: replace all case variants, then grep for zero remaining, then check whether the word also occurs in published artifacts (it triggers step 9).
5. ASCII diagrams with column annotations: never align by eye. Compute the anchor column index in Python, place the annotation segments, assert no two segments overlap in a row, then splice the block in.
6. Bump the frontmatter `version` of every skill whose content changed, and reconcile the README version table against every skill's frontmatter — check ALL rows, not just the ones you touched; the table drifts.
7. Commit in logical groups (one skill per commit with its version bump; README per commit; cross-skill contracts together; mechanical normalization last). Commit means commit AND push — push every commit.
8. Re-sync the install: first `git status --short` in `~/.hermes/skills/aios` — uncommitted drift there may be self-improvement edits that belong in the repo; capture it as a patch, apply to the repo, commit, push. `M` and `??` entries are both drift — sessions routinely create files in the install (reference docs, scripts) that never get committed. Apply the captured patch with `git apply --check` first: a failed check means the remote landed an edit on the same file between the install's base and origin/master — re-apply the intended change by hand on top of the synced version rather than forcing the stale patch, then verify each applied file is byte-identical to the install's working file. Then `git fetch -q && git reset --hard origin/master && git status --short` must be empty.
9. If `schema-v1.json` or `query-cookbook.md` changed: run `kakis_publish_meta.py` (with `--opensearch` if the env var is unset), then verify the live bodies by reading them back — `_search` against the `kakis_meta` alias (a direct `_doc/<id>` GET 400s because the doc ids contain slashes), and grep each body for the old wording → expect zero.
10. Report per item: fixed / no-change-needed with the reason, version bumps, commit SHAs, install clean, live docs verified.

## Pitfalls

- `reset --hard` on the install without `git status` first: silently destroys uncommitted self-improvement edits (in-repo skills can patch themselves in place on a git-clone install). If the reset already ran, recover from the session store, not from memory or a compaction summary — replay the recorded edit ops and snapshot-diff the last full `skill_view` (hermes-agent skill, `references/session-db-recovery.md`); summaries undercount what was lost.
- Fixing the repo files and stopping: the published `kakis_meta` docs are a second copy of the same artifacts, and other agents read the alias — a repo-only fix leaves the live docs stale.
- Renaming a skill's frontmatter `name`: the `/<name>` command surface changes with it (harness lowercases), but machine tokens must stay lowercase: phase values, module names, file paths, profile names (e.g. `bob-worker`).
- A fix-list item that verifies as already-correct or already-implemented: report it as no-change-needed with the evidence, do not force an edit to "complete" the list.
- skill_manage takes canonical names — lowercase, as on disk (`billy`). The aios category displays capitalised names (Billy) and skill_view resolves them case-insensitively, so a view-then-manage flow fails at manage with "Invalid skill name" and the WHOLE batch rolls back atomically, including ops on other skills. Use the directory name for every skill_manage op; display names are safe only for skill_view/skills_list.
- **Limited-scope commit on a dirty install** — when the user asks for a scoped commit ('just commit the latest patch') while the install also carries older out-of-scope drift: commit the WHOLE file when the requested hunks and other sessions' hunks are intermixed in one file (a partial-hunk commit orphans the other lessons, and they are destroyed from the live install on any re-sync); bump version + README row only for the skill actually committed; leave out-of-scope files untouched; and do NOT run the install `reset --hard` — it destroys the remaining drift. Report the leftover drift as still pending.
- **Drift moves between inspection and capture** — other sessions write to the install concurrently (skill patches, new reference files, version bumps), so a file can change between the diff you first inspected and the moment you capture/apply it. Derive the version bump, commit message, and README line from the POST-APPLY bytes (grep the frontmatter after applying), never from the earlier diff view — a stale number produces a version-table mismatch that costs a second reconciliation commit. Expect untracked files to appear mid-session too: the install re-sync's `git status --short` must be empty, not merely free of tracked modifications.
- **A quiet commit in an && chain can silently skip the push** — if an edit meant for the commit never landed in the worktree (e.g. the version-bump patch was left out of the command chain), `git commit -q` exits 1 with 'nothing to commit' and aborts the chain before `git push` runs, leaving an earlier commit unpushed whose message may not match its content. Verify each commit staged what its message claims (`git show --stat HEAD` after each commit) before treating the chain as done.
- **Never chain `git status --short` and `git reset --hard` in one command** — the status listing is only visible AFTER the reset has already destroyed the drift, so you can never act on it. Inspect the status in a separate earlier call; if anything is `M`/`??`, capture the drift (diff to scratch, decide commit-or-discard) before resetting. (Incident 2026-11-20: a chained status+reset destroyed two sessions' uncommitted lessons; both were recovered byte-exact from session-store `skill_view` snapshots — see hermes-agent, `references/session-db-recovery.md` — but recovery is slower and can undercount what a diff cannot see.)
