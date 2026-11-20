---
name: Billy
description: "Use to upload the most recent Kakis study to a new private GitHub repo."
version: 1.3.1
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [publishing, github, private-repo, kakis, study, upload]
    related_skills: [Kakis, generated-research-repo, github-pr-workflow]
---

# Billy — Study Publisher

Upload the most recent study completed via the Kakis pipeline to a brand-new private GitHub repo, staging the run workspace into the established study-repo layout, then verify the push and record it in the run state. Billy publishes the study as delivered (after any user review is done) — it does not re-run the pipeline or rework the analysis.

## When to Use

- The user says "upload the study", "publish the study to a private repo", "follow the convention from the previous studies", or invokes Billy.
- A Kakis run has completed, the user has finished reviewing the deliverables, and the study needs to land in the user's GitHub account.

Don't use for:
- Pushing changes to an ALREADY-UPLOADED study repo — the run state carries a `repo` block with `local_clone`; just commit and push in that clone (never create a second repo for the same study).
- Publishing code-fix runs (a Kakis run that modified an existing project, e.g. a bug fix in hermes-webui) — those have no study to publish; the target repo already exists upstream.
- Public repos — the convention is private; if the user explicitly wants public, say so in the repo-creation step and in the report.

## Prerequisites

- `gh` CLI authenticated as the study-repo owner (`gh auth status` — owner is `thongsia`; every prior study repo is under it).
- `git` on PATH; the run workspace `~/.hermes/kakis-runs/<run_id>/` intact with its deliverables.
- The study's README exists and passed user review (Billy publishes, it doesn't polish — see Pitfall 7).

## Procedure

### Step 1 — Identify the study

1. Scan `~/.hermes/kakis-runs/*/kakis_state.json`.
2. Keep runs with `phase: "completed"` (apply Kakis's substance check: `completed_steps` covers all planned steps and final notification is recorded — a `done` alias counts when the substance is there).
3. Keep STUDY runs only: goals producing a report + tables + charts from source data. Exclude code-fix runs (goal modifies an existing project) and non-study work. A study run's workspace contains `REPORT.md`, `tables/`, `charts/` at the top level.
4. Exclude runs whose state already has a `repo` block (already uploaded).
5. Most recent = newest run workspace (mtime / `created` timestamp). If the newest completed run is ambiguous (code-fix, or two studies in the same window), list the candidates with goal + date and ask the user to confirm which one to upload — one short question, then proceed autonomously.

### Step 2 — Name the repo

- Repo name = the run's slug (the `<slug>` part of `run_id`, kebab-case) — e.g. run `cve-cwe-reconciliation_20261023161605` → repo `cve-cwe-reconciliation`. Descriptive, lowercase, hyphens; matches the study's working name.
- Verify availability: `gh repo view thongsia/<name>` — 404/`HTTP 404` means free; an existing repo means the study was already published (check its `repo` block in other run states; if the user still wants a fresh name, confirm).

### Step 3 — Stage the repo tree

Local clone home is `~/workspace/<repo-name>/` (a fresh `git init`, not a clone). Copy from the run workspace (`WS`) with this mapping — the established layout, recorded as the standing convention on `thongsia/cve-cwe-reconciliation`:

| From `WS/` | To repo |
|---|---|
| `src/*.py` | `src/` (re-runnable pipeline modules; `__pycache__/` dropped) |
| `REPORT.md`, `STATS_SUMMARY.md`, `methodology_notes.md`, `provenance.md`, source documents (`docs/*.pdf`, OCR/extracted text) | `docs/` (report at `docs/REPORT.md`) |
| `tables/*.csv` | `tables/` |
| `charts/*.png` | `charts/` |
| `data/raw/**` (curated source extracts — small) | `data/raw/` |
| `data/processed/**` (derived datasets: report numbers JSON, maps, quantifications) | `data/processed/` |
| `verification/**` (file inventory, fetch logs, invariant/anchor checks, `live_probes/`) | `verification/` |
| `kakis_state.json`, `calls.jsonl`, `feasibility.md`, `dory_brief.md`, `bob_brief.md`, `bob_results.json`, `bob_plan.md`, `bob_dispatch.log`, `final_prompt.txt`, `final_plan.txt`, `final_review.txt`, `review_N.txt` | `pipeline/` (orchestrator meta — pipeline history lives with the study) |
| `gate0_message.txt`, `gate1_message.txt`, `gate2_message.txt`, `gate3_notification.txt` | `pipeline/gates/` |
| `batch_handoff_*.json` | repo root (only if the run kept them at root, as `thongsia/coe-category-study` did) |

Run workspaces rarely match this table literally (single entry script at the run root instead of `src/*.py`, tables/figures under `artifacts/`, lowercase `report.md`, audit logs under `artifacts/logs/`). Map by role onto the canonical target layout: pipeline entry script(s) → `src/`; the report (any case) → `docs/REPORT.md`; table CSVs → `tables/`; figure PNGs → `charts/`; audit/self-check/cleaning logs → `verification/`; orchestrator meta (state, calls, plans, dispatch logs, `final_*`) → `pipeline/`.

Curated `.gitignore` (exactly this, as in both prior uploads):

```
__pycache__/
*.pyc
.DS_Store
```

**Exclude record-level bulk artifacts — never commit them:** full source-repo clones (e.g. cvelistV5, 400k+ files), raw API-response pages, per-record CSVs, mirrored corpora, giant intermediate dirs. Instead pin them in `verification/file_inventory.txt` (tab-separated: `path`, `sha256`, `size_bytes`, `role`; a pinned git checkout records `HEAD verified at pinned SHA <sha>` instead of per-file hashes). Stage the run's own file inventory if it produced one (`file_inventory.txt` / `file_inventory.csv`) and extend it for anything Billy newly excludes.

**Size gate before commit:** `du -sh` + `find . -type f | wc -l` on the staged tree. GitHub rejects single files over 100 MB; hundreds of thousands of files is a no-go even under the limit. Anything in that territory moves to the exclusion list with its SHA-256 in the inventory. Enumerate ALL staged files (`find . -type f | sort`) before committing — a missing report section or a stray 2 GB intermediate is caught here, not at push.

### Step 4 — README + repo description

- A `README.md` at the repo root is a required artifact — the management-facing front door of the study. The README may be generated by the run or co-authored during review — in observed runs it often exists only in the local clone, not the run workspace. If the staged tree has none, build it from `docs/REPORT.md` before uploading, using the main-README conventions below (staging fallback). Content fixes to an already-reviewed README belong in the run only when a README generator owns the text (fix the generator, re-run); when it does not, see the "Unlabeled figures" pitfall.
- Main-README conventions — spot-check every one on an existing README, and follow every one when Billy builds the README:
  1. **Figures and tables back every statistical finding.** Each finding in the README sits next to an inlined figure or table: a bold "Figure N." / "Table N." label, the chart or table embedded at the point of discussion, and an in-text reference ("(Figure N)" / "(Table N)") in the body where the finding is discussed — no orphaned figure, no dangling reference. Run the mechanical check — `python3 ~/.hermes/skills/research/generated-research-repo/scripts/verify_readme_labels.py <README>`: label/embed parity, caption/table parity, in-body reference resolution, gapless 1..N numbering, every exhibit sitting under its label, sequential numbered sections, in-document TOC anchors, no tildes; exit 0 is the gate. Self-contained charts (in-image "Figure N: <caption>" band) per `generated-research-repo`.
  2. **Layman register — the audience is management.** The README carries the verdict and the key numbers in plain language and is self-sufficient for a decision-maker; technical detail (methodology, statistical machinery, equations, audit trails) stays in the supplementary report (`docs/REPORT.md`) and second-level docs, with explicit pointers to the sections that carry it. The final "Under the hood (for the curious)" section is the one place technical apparatus may surface in the README.
  3. **Numbered sections and sub-sections.** Top-level sections numbered 1., 2., 3., …; sub-sections numbered hierarchically under their parent (4.1, 4.2, …) so finding numbers never collide with section numbers; result headings state the outcome, not just the scenario.
  4. **Inlined tables must match their captions.** A caption like "cleaning rules (R1-R5)" promises five rows; if the generator's CSV expands a group ID into sub-rows (R5.1-R5.6), the table is misleading — collapse the sub-rows into ONE group row in the README renderer (compact row: what the sub-checks cover + the common verdict, e.g. "all passed, 0 rows, no-fix"). The per-sub-row detail with examples stays in the machine-readable CSV the table footer already links, and the formal `docs/REPORT.md` table keeps the full detail. Done criterion: caption's ID range == number of rows in the inlined table.
  5. **TL;DR section.** The first section (executive summary / short answer) is headed `## 1. TL;DR` — never academic variants like "The short answer" or "Bottom line" (standing user convention, applied retroactively to all study repos). If the README has a TOC, update the section's TOC label and anchor too (GitHub slug of "1. TL;DR" is `#1-tldr`).
- No `~` anywhere in the README (GitHub strikes out single-tilde pairs).
- When the README documents re-running the study, check how the entry script resolves its paths (its own directory vs CWD — e.g. `RUN_ROOT = Path(__file__).resolve().parent`) and write instructions that actually work from the repo root (typically: copy the `data/raw/` input next to the script, run it, outputs land next to the script).
- Repo description pattern (set at creation, `--description`): `<question the study answers?> — <short study title> (data, re-runnable pipeline, report)` — e.g. "Merging car COE categories A and B: who pays, and who is rebated? — Singapore COE categorisation scenario study (data, re-runnable pipeline, report)". (`thongsia/cve-cwe-reconciliation` was created without a description; the pattern above is the one to follow.)

### Step 5 — Commit (single, squashed)

```
cd ~/workspace/<name>
git init -b main
git add -A
git commit -m "<Title-case study name>: report, tables, charts, re-runnable pipeline, verification"
```

Commit body convention (from `thongsia/coe-category-study`): one paragraph on what the study is, then bullets — README audience + where the report/summary live (report numbers machine-checked against table cells); N ordered Python modules in `src/` and what end-to-end re-running does; N tables + N self-contained figures (in-image Figure N captions, layout-verified at save time); `verification/` audit trail (N checks: N pass, N documented exceptions, 0 fail) + sha256-audited source archives. Numbers come from the actual staged tree and the run's verification report — not from memory.

Both prior repos are a single commit on `main`. Get the tree right before `gh repo create` — fixing staging afterwards means follow-up commits.

### Step 6 — Create the private repo and push

```
gh repo create thongsia/<name> --private --source=. --push
```

Commit means commit AND push — the push is the point; never stop at a local commit.

### Step 7 — Verify the push (authenticated)

Private repos 404 on UNauthenticated web and raw endpoints (GitHub privacy protection — not a failure). Verify with authenticated calls:

```
gh api repos/thongsia/<name> --jq '{name, private, default_branch, pushed_at}'   # private must be true
gh api -H "Accept: application/vnd.github.raw+json" repos/thongsia/<name>/contents/README.md | head -5
```

Also confirm the file count the remote serves equals the staged count: `git ls-remote` + `git ls-files | wc -l` locally (record that number for the state block). On a README-touching commit, also grep the served README for the count of bold `Figure`/`Table` labels and confirm it matches the local `verify_readme_labels.py` output — a mismatch means the wrong or a stale file was pushed.

### Step 8 — Record in run state, log, and mirror

1. Add a `repo` block to `<run_workspace>/kakis_state.json`, preserving every existing key (write to a `.tmp` file, then `os.replace` — atomic):
   ```json
   "repo": {
     "url": "https://github.com/thongsia/<name>",
     "private": true,
     "default_branch": "main",
     "commit": "<full SHA>",
     "files": <staged file count>,
     "local_clone": "/home/hteo/workspace/<name>",
     "convention": "mirrors thongsia/coe-category-study: structured dirs (src/docs/tables/charts/data/verification/pipeline), curated .gitignore, self-contained README, caption-band charts",
     "excluded": "<what was excluded, e.g. record-level artifacts — SHA-256 in verification/file_inventory.txt>",
     "uploaded_at": "<ISO8601 UTC>"
   }
   ```
2. Append to `<run_workspace>/notification.log`:
   `[<ISO ts>] repo upload: github.com/thongsia/<name> (private, main, <short sha>, N files) verified via API+authed raw`
3. Re-run the memory export (best-effort, never blocks): `python3 ~/.hermes/skills/aios/kakis/scripts/kakis_export.py <run_workspace>` — non-zero exit → log to `notification.log`, continue. Heavy run workspaces can OOM-kill the exporter (SIGKILL -9; see Kakis Pitfalls for the targeted-sync remedy).
4. Report to the user: repo URL, commit SHA, file count, verification outcome, and the exclusion list (what stayed local and where its hashes live).

## Conventions extracted from prior uploads

Reference repos: `thongsia/coe-category-study` (2026-10-23, private, 125 files, commit 9b1626d) and `thongsia/cve-cwe-reconciliation` (2026-10-24, private, 96 files, commit d78b029); earlier public precedent `thongsia/coe-ev-rebate-analysis`. If a future repo diverges on purpose, update this list — the `convention` field in each run's `repo` block points here.

- Private repo, owner `thongsia`, kebab-case name = run slug; local clone in `~/workspace/<name>`; branch `main`; single squashed commit.
- Directory layout: `src/ docs/ tables/ charts/ data/{raw,processed}/ verification/ pipeline/{,gates}/`; `.gitignore` = `__pycache__/ *.pyc .DS_Store`.
- `README.md` at the repo root (required): every statistical finding backed by an inlined, body-referenced figure/table; layman register for management; numbered sections and sub-sections; technical detail deferred to `docs/REPORT.md`.
- Self-contained README per `generated-research-repo`; caption-band charts ("Figure N: …" rendered on the PNG).
- Record-level raw inputs excluded from the repo, pinned by SHA-256 in `verification/file_inventory.txt`.
- Description: `<question?> — <title> (data, re-runnable pipeline, report)`.
- Post-push: verify via authenticated API/raw only; record `repo` block in `kakis_state.json`; log line in `notification.log`; best-effort OpenSearch re-export.

## Pitfalls

- **Private-repo 404 trap** — after pushing, `https://github.com/thongsia/<name>` and `raw.githubusercontent.com` return 404 to unauthenticated requests. Do not "fix" a successful push by re-pushing; verify with `gh api` / authenticated raw.
- **Wrong run** — "most recent completed" is not "most recent study": exclude code-fix runs and runs that already carry a `repo` block. When two candidates are close in time, confirm with the user rather than guessing — uploading the wrong study to a new private repo is the worst failure mode.
- **Bulk data in the tree** — a run's workspace routinely holds multi-GB record-level inputs (full CVE corpora, NVD pages, cloned repos). The size gate (Step 3) is not optional; the prior cve run excluded ~200k files of cvelistV5 and pinned them by git SHA in the inventory instead.
- **Credentials in artifacts** — run logs occasionally echo environment; grep the staged tree for the tokens in `~/.hermes/.env` (Telegram, OpenSearch) before committing. Nothing from `.env` ever lands in a repo.
- **State clobber** — the `repo` block is an ADD to `kakis_state.json`, not a rewrite: read the whole state, set one key, write tmp + rename. A lost state file breaks Kakis resume for that run.
- **Billy doesn't polish** — if the README/report has a content problem, the fix belongs in the run workspace's generator, regenerated, and re-reviewed. Billy's edit surface is staging, layout, README existence, and metadata — hand-editing generated report text in the repo clone breaks the "every number originates in a generator" invariant (see `generated-research-repo`).
- **Tildes in generated deliverables** — the user's writeup convention bans `~` in markdown (GitHub strikes out single-tilde pairs), and generated report/table text routinely contains them ("~3%", "~2x"). Sweep the staged presentation markdown (README, `docs/`, `tables/`, `verification/*.md`) before committing. If a tilde is in generator output: patch the run's generator, re-run the pipeline, confirm the self-check passes and the numeric artifacts (CSV hashes) are unchanged — expect only text columns to shift — then re-stage the changed artifacts and re-verify inventory hashes. Never hand-edit generated text in the repo clone. Verbatim `pipeline/` records (harness transcripts, calls logs) are out of scope — never "fix" history.
- **Unlabeled figures / dangling references** — a run's README generator can emit image embeds with alt-text only (no "Figure N." label) while the prose cites figure numbers that no labeled figure carries, or leave tables without any in-text reference. The mechanical check in Step 4 catches it; renumbering cascades into compound references like "(Figure 4, Table 3)", so the script's exit 0 — not eyeballing — is the done criterion. If a README generator owns the text (grep the run's `src/`/`scripts/`), fix it there, regenerate, re-stage. If the run has no README generator — the README is a co-authored presentation document living only in the local clone — the no-hand-edit rule does not apply to it: edit the clone's README and push a follow-up commit to the same repo (the "Follow-up changes after upload" path), then verify the served label count.
- **Follow-up changes after upload** — later user corrections are pushed as new commits to the SAME repo from `local_clone` (rebase onto `origin/main` if the user committed themselves; never force-push). Never create a second repo for the same study. If a README staging/generation script owns the README prose (check the run workspace, e.g. `WS/stage_readme.py`, and `~/.hermes/cache/scratch/`), it is the single source of truth: apply every prose edit to the script and re-run it — direct patches to the clone's README are silently clobbered the next time the script regenerates (this actually happened: five reviewed edits regressed on one regeneration). Keep any such script in the run workspace, not just in scratch (scratch is pruned after 24h). After every follow-up commit: byte-compare the served files against local (`gh api repos/<o>/<r>/contents/<path> --jq .content | base64 -d | cmp - <local>`), bump `repo.commit` in kakis_state.json, and best-effort re-run the kakis_export.py mirror — the review loop runs many small rounds, and each round needs the same verification, not just the first upload. The mirrored run doc does NOT carry the `repo` block (exporter run-doc fields are run metadata + artifact/call counts only), so a commit-only bump needs no re-export — local state is canonical; skip the (possibly heavy/OOM-kill) export there. If the same edit request arrives twice (messaging platforms redeliver), do not re-apply blindly — verify state first (grep the clone for the target sentence, check `git log -1` and the remote tip): if the edit is already pushed, report "already done" with the commit instead of making a duplicate change.
- **Convention backport across study repos** — when the user wants a presentation change applied to "my other recent kakis studies": enumerate with `gh repo list thongsia`, fetch each README via `gh api -H "Accept: application/vnd.github.raw+json" repos/thongsia/<r>/contents/README.md` and grep for the old text (404 = run not published, skip). For each hit, decide the edit surface first: a README generator owns the prose (run workspace top-level `*.py`, e.g. `stage_readme.py`, or the repo's `src/`) → patch the generator and rebuild; no generator → the no-hand-edit rule does not apply (see "Unlabeled figures" pitfall) — patch the clone and push. Renaming a section heading must also update its TOC label and anchor in the same commit. A repo with no run workspace (pre-kakis study, e.g. the public `coe-ev-rebate-analysis`) is outside the stated scope — list it as a candidate and let the user decide; if included, treat it as a plain clone edit (no state/mirror sync has a workspace to point at).
- **GitHub remotes are HTTPS on this host** — every study clone's `origin` is `https://github.com/thongsia/<name>.git`; `git clone git@github.com:…` fails with host-key verification. When no local clone exists, clone over HTTPS before editing.
- **Description drift** — `gh repo create --description` takes a single-line string; compose it in a file and pass via command substitution if it carries quotes.

## Verification

1. `gh api repos/thongsia/<name> --jq '{private, default_branch, pushed_at}'` shows `private: true`, `main`, a fresh `pushed_at`.
2. Authenticated README fetch returns the actual README head (not a 404 page).
3. Remote file count == `git ls-files | wc -l` locally == the `files` value recorded in the `repo` block.
4. `kakis_state.json` parses, contains the `repo` block, and every pre-existing key is intact.
5. `notification.log` carries the `repo upload:` line; `kakis_export.py` re-run logged (or its failure logged, run unaffected).
6. Exclusion list in the report to the user matches what `verification/file_inventory.txt` pins.
