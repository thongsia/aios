#!/usr/bin/env python3
"""Mirror a KAKIS run (workspace + Dory/Bob sub-workspaces) into OpenSearch.

Usage:
  kakis_export.py <run_workspace>            export one run
  kakis_export.py --all                      export every run under ~/.hermes/kakis-runs/
  [--opensearch http://host:9200]

Idempotent: deterministic doc ids, safe to re-run (upserts).
Exit codes: 0 ok, 2 opensearch unreachable, 3 bulk indexing errors.

Local files remain canonical; OpenSearch is a searchable copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OS = os.environ.get("AIOS_OPENSEARCH", "http://<your-opensearch>:9200")
KAKIS_RUNS_ROOT = Path(os.environ.get("KAKIS_RUNS_ROOT", str(Path.home() / ".hermes" / "kakis-runs")))
CONTENT_LIMIT = 512 * 1024  # full text only under this
HEAD_LIMIT = 2 * 1024
TEXT_EXT = {".md", ".txt", ".json", ".log", ".csv", ".py", ".yml", ".yaml", ".tsv"}
SKIP_FILES = {".gate_decided"}
LOCAL_TZ = "+08:00"  # legacy naive timestamps (pre-2026-10-14 states) are local wall clock
ASSUMED_TZ_NOTE = "legacy naive timestamps assumed " + LOCAL_TZ

# ---------------------------------------------------------------- http helpers

def req(base, method, path, body=None, timeout=60):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def bulk(base, actions):
    """actions: list of (op_type, index, doc_id, doc). Returns (ok, errors).

    Payloads are chunked so no single _bulk request exceeds MAX_BULK_BYTES
    (OpenSearch's default http.max_content_length is 100MB; stay well under it).
    """
    MAX_BULK_BYTES = 20 * 1024 * 1024
    chunks = []
    cur, cur_size = [], 0
    for op, index, doc_id, doc in actions:
        size = len(json.dumps(doc, ensure_ascii=False)) + 160
        if cur and cur_size + size > MAX_BULK_BYTES:
            chunks.append(cur)
            cur, cur_size = [], 0
        cur.append((op, index, doc_id, doc))
        cur_size += size
    if cur:
        chunks.append(cur)

    errors = []
    for chunk in chunks:
        lines = []
        for op, index, doc_id, doc in chunk:
            lines.append(json.dumps({op: {"_index": index, "_id": doc_id}}))
            lines.append(json.dumps(doc, ensure_ascii=False))
        payload = ("\n".join(lines) + "\n").encode()
        r = urllib.request.Request(base.rstrip("/") + "/_bulk", data=payload, method="POST")
        r.add_header("Content-Type", "application/x-ndjson")
        try:
            with urllib.request.urlopen(r, timeout=300) as resp:
                body = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode() or "{}")
            except Exception:
                body = {}
            errors.append({"index": "<bulk>", "id": None,
                           "error": f"HTTP {e.code}: {str(body)[:500]}"})
            continue
        except Exception as e:
            errors.append({"index": "<bulk>", "id": None, "error": str(e)})
            continue
        for item in body.get("items", []):
            for _op_res, res in item.items():
                if res.get("error"):
                    errors.append({"index": item.get("_index"), "id": item.get("_id"),
                                   "error": res["error"]})
    return (not errors), errors

# ---------------------------------------------------------------- ts / ids

def norm_ts(value):
    """Normalize a timestamp string to ISO8601 with offset. None/'' -> None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # +0800 -> +08:00 (no colon)
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    naive = not re.search(r"(Z|[+-]\d{2}:\d{2})$", s)
    if naive:
        s += LOCAL_TZ
    # drop microseconds beyond 6 / keep parseable
    try:
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except ValueError:
        return None


def mtime_iso(p: Path):
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).astimezone().isoformat()
    except OSError:
        return None


def doc_id_artifact(run_id, rel_path):
    return hashlib.sha256(f"{run_id}|{rel_path}".encode()).hexdigest()


def doc_id_call(run_id, seq, module):
    return f"{run_id}|call|{seq}|{module}"

# ---------------------------------------------------------------- classification

def classify(rel_path, state_phase="unknown"):
    """Return (kind, phase, module) for an artefact path (relative, may be dory/... or bob/...)."""
    name = Path(rel_path).name
    dory_n = re.match(r"^(prompt|plan|review)_(\d+)\.txt$", name)
    if rel_path.startswith("dory/"):
        if dory_n and dory_n.group(1) in ("prompt", "plan"):
            return "prompt" if dory_n.group(1) == "prompt" else "plan", "dory", "dory_planner"
        if dory_n and dory_n.group(1) == "review":
            return "review", "dory", "dory_reviewer"
        if name == "dory_brief.md":
            return "brief", "dory", "compress"
        return "other", "dory", "other"
    if rel_path.startswith("bob/"):
        if name == "plan.md":
            return "bob_plan", "bob", "bob_synth"
        if name == "results.json":
            return "bob_results", "bob", "bob_synth"
        # bob/<harness>/... per-harness raw output
        return "other", "bob", "bob_harness"
    # run workspace
    if name == "kakis_state.json":
        return "state", state_phase, None
    if name == "feasibility.md":
        return "feasibility", "research", "igor"
    if name == "calls.jsonl":
        return "call_log", state_phase, None
    if name == "final_prompt.txt":
        return "prompt", "dory", "dory_planner"
    if name == "final_plan.txt":
        return "plan", "dory", "dory_planner"
    if name == "final_review.txt":
        return "review", "dory", "dory_reviewer"
    if name == "dory_brief.md":
        return "brief", "dory", "compress"
    if name == "bob_brief.md":
        return "brief", "bob", "compress"
    if name == "bob_plan.md":
        return "bob_plan", "bob", "bob_synth"
    if name == "bob_results.json":
        return "bob_results", "bob", "bob_synth"
    if name == "bob_dispatch.log":
        return "bob_log", "bob", None
    m = re.match(r"^gate([012])_message\.txt$", name)
    if m:
        return "gate_message", f"gate{m.group(1)}", None
    if name == "final_notification.txt":
        return "notification", state_phase, None
    if name == "notification.log":
        return "log", state_phase, None
    if re.match(r"^batch_[a-z0-9_]*_?report\.json$", name):
        return "execution_report", "execute", "execution_batch"
    if name.startswith("device_"):
        return "device", "execute", "execution_batch"
    ext = Path(name).suffix.lower()
    if ext == ".csv" or ext == ".tsv":
        return "data", state_phase, None
    return "other", state_phase, None

# ---------------------------------------------------------------- artifact docs

def read_text_head(p: Path, limit):
    try:
        with open(p, "rb") as f:
            raw = f.read(limit)
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


def artifact_doc(run_id, rel_path, abspath: Path, kind, phase, module):
    doc = {
        "run_id": run_id,
        "path": rel_path,
        "original_path": str(abspath),
        "kind": kind,
        "phase": phase,
        "module": module,
    }
    try:
        st = abspath.stat()
    except OSError:
        return doc, "missing"
    doc["size_bytes"] = st.st_size
    doc["mtime"] = mtime_iso(abspath)
    sha = hashlib.sha256()
    is_text = abspath.suffix.lower() in TEXT_EXT
    content = None
    if is_text:
        try:
            with open(abspath, "rb") as f:
                data = f.read()
            sha.update(data)
            content = data.decode("utf-8", errors="replace")
        except OSError:
            content = None
    else:
        try:
            with open(abspath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
        except OSError:
            pass
    doc["sha256"] = sha.hexdigest()
    head = read_text_head(abspath, HEAD_LIMIT)
    if head is not None:
        doc["head"] = head
    if content is not None and len(content.encode("utf-8")) <= CONTENT_LIMIT:
        doc["content"] = content
    return doc, "ok"

# ---------------------------------------------------------------- walk / skip

SKIP_DIRS = {".git", "node_modules", ".cache", "__pycache__", "venv", ".venv",
             "target", "dist", "build", ".local", ".npm", ".cargo"}


def walk_workspace(root: Path, prefix):
    """Yield (rel_path_with_prefix, abspath) for every indexable file under root.

    Prunes heavy/sandbox directories. In Bob workspaces the per-harness `home/`
    directory is a simulated HOME sandbox (caches, checkouts) — never mirrored.
    """
    if not root.is_dir():
        return
    base = prefix.split("/") if prefix else []
    for dirpath, dirnames, filenames in os.walk(root):
        kept = []
        for d in dirnames:
            if d.startswith(".") or d in SKIP_DIRS:
                continue
            if prefix == "bob" and d == "home":
                continue
            kept.append(d)
        dirnames[:] = sorted(kept)
        for fn in sorted(filenames):
            if (fn.startswith(".") or fn in SKIP_FILES or fn.endswith("~")
                    or fn.endswith(".tmp") or fn.endswith(".pyc")):
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root)
            parts = base + list(rel.parts)
            yield ("/".join(parts), p)

# ---------------------------------------------------------------- calls

def calls_from_jsonl(p: Path):
    """Parse calls.jsonl -> list of call docs.

    Malformed lines are skipped. Open/closed records sharing (seq, module)
    are deduplicated, keeping the latest (closed) record in file order.
    """
    if not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records = {}
    order = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or "seq" not in rec or "module" not in rec:
            continue
        try:
            seq = int(rec["seq"])
        except (TypeError, ValueError):
            continue
        key = (seq, str(rec["module"]))
        if key not in records:
            order.append(key)
        records[key] = {
            "seq": seq,
            "module": str(rec["module"]),
            "variant": rec.get("variant"),
            "iteration": rec.get("iteration"),
            "input_refs": rec.get("input_refs") or [],
            "output_refs": rec.get("output_refs") or [],
            "status": rec.get("status", "ok"),
            "goal": rec.get("goal_head") or rec.get("goal"),
            "result_summary": rec.get("result_summary_head") or rec.get("result_summary"),
            "notes": rec.get("notes"),
            "started_at": norm_ts(rec.get("ts")),
            "ended_at": norm_ts(rec.get("ended_ts")),
        }
    return [records[k] for k in order]


def reconstruct_calls(run_ws: Path, dory_ws, bob_ws, run_id, state):
    """Reconstruct sub-module calls for legacy runs (no calls.jsonl)."""
    calls = []
    seq = 0
    dory_files = {}
    if dory_ws and dory_ws.is_dir():
        for p in dory_ws.iterdir():
            m = re.match(r"^(prompt|plan|review)_(\d+)\.txt$", p.name)
            if m and p.is_file():
                dory_files.setdefault(int(m.group(2)), {})[m.group(1)] = p
    if dory_files:
        for n in sorted(dory_files):
            f = dory_files[n]
            if "plan" in f:
                seq += 1
                calls.append({
                    "seq": seq, "module": "dory_planner", "variant": None, "iteration": n,
                    "input_refs": [f"dory/prompt_{n}.txt"] if "prompt" in f else
                                  [f"dory/prompt_{n - 1}.txt"],
                    "output_refs": [f"dory/plan_{n}.txt"],
                    "status": "ok", "goal": None, "result_summary": None,
                    "notes": "reconstructed", "started_at": mtime_iso(f.get("prompt", f["plan"])),
                    "ended_at": mtime_iso(f["plan"]), "source": "reconstructed",
                })
            if "review" in f:
                seq += 1
                calls.append({
                    "seq": seq, "module": "dory_reviewer", "variant": None, "iteration": n,
                    "input_refs": [f"dory/plan_{n}.txt"],
                    "output_refs": [f"dory/review_{n}.txt"],
                    "status": "ok", "goal": None, "result_summary": None,
                    "notes": "reconstructed", "started_at": mtime_iso(f.get("plan", f["review"])),
                    "ended_at": mtime_iso(f["review"]), "source": "reconstructed",
                })
    # igor
    if (run_ws / "feasibility.md").is_file():
        seq += 1
        calls.append({
            "seq": seq, "module": "igor", "variant": None, "iteration": None,
            "input_refs": [], "output_refs": ["feasibility.md"],
            "status": "ok", "goal": (state or {}).get("goal"),
            "result_summary": f"verdict={state.get('gate0_verdict')}" if (state or {}).get("gate0_verdict") else None,
            "notes": "reconstructed", "started_at": None,
            "ended_at": mtime_iso(run_ws / "feasibility.md"), "source": "reconstructed",
        })
    # bob harnesses from bob_results.json
    results_p = run_ws / "bob_results.json"
    if results_p.is_file():
        try:
            results = json.loads(results_p.read_text())
            for entry in results.get("normalized", []):
                if not isinstance(entry, dict):
                    continue
                seq += 1
                calls.append({
                    "seq": seq, "module": "bob_harness", "variant": entry.get("harness"),
                    "iteration": None,
                    "input_refs": ["final_prompt.txt"],
                    "output_refs": [f"bob/{entry.get('harness')}/"] if entry.get("harness") else [],
                    "status": str(entry.get("status", "ok")),
                    "goal": None, "result_summary": None,
                    "notes": f"exit_code={entry.get('exit_code')} duration_s={entry.get('duration_s')} (reconstructed)",
                    "started_at": None, "ended_at": None, "source": "reconstructed",
                })
            seq += 1
            calls.append({
                "seq": seq, "module": "bob_synth", "variant": None, "iteration": None,
                "input_refs": ["bob_results.json"], "output_refs": ["bob/plan.md"],
                "status": "ok", "goal": None,
                "result_summary": f"best={(results.get('evaluation') or {}).get('best_plan_harness')}",
                "notes": "reconstructed", "started_at": None,
                "ended_at": mtime_iso(results_p), "source": "reconstructed",
            })
        except (json.JSONDecodeError, OSError):
            pass
    # execution batches
    for p in sorted(run_ws.glob("batch_*_report.json")):
        seq += 1
        stem = p.stem  # e.g. batch_a_report
        calls.append({
            "seq": seq, "module": "execution_batch", "variant": stem.replace("batch_", "").replace("_report", ""),
            "iteration": None,
            "input_refs": [], "output_refs": [p.name],
            "status": "ok", "goal": None, "result_summary": None,
            "notes": "reconstructed", "started_at": None,
            "ended_at": mtime_iso(p), "source": "reconstructed",
        })
    return calls


def dedupe_calls(primary, additions):
    """Keep primary calls; add reconstructed calls whose (seq, module) is not in primary."""
    seen = {(c["seq"], c["module"]) for c in primary}
    for c in additions:
        if (c["seq"], c["module"]) not in seen:
            seen.add((c["seq"], c["module"]))
            primary.append(c)
    primary.sort(key=lambda c: (c["seq"], c["module"]))
    return primary

# ---------------------------------------------------------------- run doc

def parse_gate_decision(value):
    """('proceed'|'abort'|'auto_proceed'|None, scope_note_or_None)."""
    if not value:
        return None, None
    s = str(value).strip()
    low = s.lower()
    if "auto" in low:
        return "auto_proceed", None
    m = re.match(r"^(proceed|abort|yes|no|stop|go)\b", low)
    if not m:
        return None, s
    decision = "proceed" if m.group(1) in ("proceed", "yes", "go") else "abort"
    rest = s[m.end():].strip()
    note = None
    m2 = re.match(r"^\((.*)\)$", rest)
    if m2:
        note = m2.group(1).strip() or None
    elif rest:
        note = rest
    return decision, note


def run_doc(run_ws: Path, state, artifact_count, call_count):
    run_id = (state or {}).get("run_id") or run_ws.name
    phase = (state or {}).get("phase", "unknown")
    status = phase if phase in ("completed", "aborted") else "in_progress"
    slug = run_id.rsplit("_", 1)[0] if "_" in run_id else run_id
    dory_art = (state or {}).get("dory_artifacts") or {}
    bob_art = (state or {}).get("bob_artifacts") or {}

    gates = {}
    for gn, note_key in (("gate0", "gate0_user_note"), ("gate1", "gate1_scope"), ("gate2", "gate2_scope")):
        decision_raw = (state or {}).get(f"{gn}_decision")
        if decision_raw is None and gn == "gate0":
            # gate0 has no _decision field; infer from phase progression
            if phase in ("gate0",) or (state or {}).get("gate_waiting") and (state or {}).get("gate") == "gate0":
                decision_raw = None
            elif phase not in ("research",):
                decision_raw = "proceed"
        decision, note = parse_gate_decision(decision_raw)
        if decision is None and (state or {}).get(gn + "_user_note"):
            note = (state or {}).get(gn + "_user_note")
        if (state or {}).get(note_key) and not note:
            note = (state or {}).get(note_key)
        if decision or note:
            gates[gn] = {
                "decision": decision,
                "decided_at": None,  # per-gate timestamps not stored in state v1
                "scope_note": note,
                "auto_proceeded": decision == "auto_proceed",
            }
    if (state or {}).get("gate_waiting"):
        pending = (state or {}).get("gate")
        if pending in gates:
            gates[pending] = {"decision": "pending", "decided_at": None,
                              "scope_note": None, "auto_proceeded": False}
        elif pending:
            gates[pending] = {"decision": "pending", "decided_at": None,
                              "scope_note": None, "auto_proceeded": False}

    state_p = run_ws / "kakis_state.json"
    errors = []
    for key in ("research_failure_cause", "dory_failure_cause"):
        if (state or {}).get(key):
            errors.append(f"{key}: {(state or {}).get(key)}")

    return {
        "run_id": run_id,
        "slug": slug,
        "goal": (state or {}).get("goal"),
        "phase": phase,
        "status": status,
        "feasibility_verdict": (state or {}).get("gate0_verdict"),
        "gates": gates or None,
        "created_at": norm_ts((state or {}).get("created")),
        "updated_at": mtime_iso(state_p) if state_p.is_file() else None,
        "dory_iterations": (state or {}).get("dory_iterations"),
        "bob_harness_count": (state or {}).get("bob_harnesses"),
        "bob_best_harness": (state or {}).get("bob_best_harness"),
        "bob_best_score": (state or {}).get("bob_best_score"),
        "completed_steps": len((state or {}).get("completed_steps") or []),
        "total_steps": (state or {}).get("total_steps"),
        "run_workspace": (state or {}).get("run_workspace", str(run_ws)),
        "dory_workspace": (state or {}).get("dory_workspace") or dory_art.get("dory_workspace"),
        "bob_workspace": (state or {}).get("bob_workspace") or bob_art.get("bob_workspace"),
        "artifact_count": artifact_count,
        "call_count": call_count,
        "error_summary": " | ".join(errors) or None,
    }

# ---------------------------------------------------------------- export one run

def resolve_workspace(value):
    if not value:
        return None
    p = Path(str(value).strip().rstrip("/"))
    return p if p.is_dir() else None


def export_run(base, run_ws: Path, os_base_errors):
    state_p = run_ws / "kakis_state.json"
    state = None
    if state_p.is_file():
        try:
            state = json.loads(state_p.read_text())
        except (json.JSONDecodeError, OSError) as e:
            os_base_errors.append(f"{run_ws.name}: unreadable state: {e}")
            state = {}
    if state is None:
        state = {}
    phase = state.get("phase", "unknown")
    run_id = state.get("run_id") or run_ws.name

    dory_ws = resolve_workspace(state.get("dory_workspace")) or resolve_workspace(
        (state.get("dory_artifacts") or {}).get("dory_workspace"))
    bob_ws = resolve_workspace(state.get("bob_workspace")) or resolve_workspace(
        (state.get("bob_artifacts") or {}).get("bob_workspace"))
    if bob_ws is None:
        # fallback: [bob] Workspace: line in bob_dispatch.log
        log_p = run_ws / "bob_dispatch.log"
        if log_p.is_file():
            try:
                for line in log_p.read_text(errors="replace").splitlines():
                    m = re.match(r"^\[bob\] Workspace:\s*(\S+)", line.strip())
                    if m:
                        bob_ws = resolve_workspace(m.group(1))
                        break
            except OSError:
                pass

    # artifacts
    actions = []
    artifact_count = 0
    for root, prefix in ((run_ws, ""), (dory_ws, "dory"), (bob_ws, "bob")):
        if root is None:
            continue
        for rel, abspath in walk_workspace(root, prefix):
            kind, a_phase, module = classify(rel, phase)
            doc, ok = artifact_doc(run_id, rel, abspath, kind, a_phase, module)
            if ok != "ok":
                continue
            actions.append(("index", "kakis_artifacts", doc_id_artifact(run_id, rel), doc))
            artifact_count += 1

    # calls
    calls = calls_from_jsonl(run_ws / "calls.jsonl")
    reconstructed = reconstruct_calls(run_ws, dory_ws, bob_ws, run_id, state)
    dedupe_calls(calls, reconstructed)
    for c in calls:
        c = {k: v for k, v in c.items() if k != "source"}
        c["run_id"] = run_id
        actions.append(("index", "kakis_calls", doc_id_call(run_id, c["seq"], c["module"]), c))

    # run doc
    doc = run_doc(run_ws, state, artifact_count, len(calls))
    actions.append(("index", "kakis_runs", run_id, doc))

    ok, errors = bulk(base, actions)
    if errors:
        os_base_errors.extend(f"{run_id}: {e.get('error')}" for e in errors[:5])
    return run_id, artifact_count, len(calls), ok

# ---------------------------------------------------------------- main

def main(argv):
    base = DEFAULT_OS
    if "--opensearch" in argv:
        base = argv[argv.index("--opensearch") + 1]
    status, body = req(base, "GET", "/")
    if status != 200:
        print(f"ERROR: OpenSearch unreachable at {base} (HTTP {status})", file=sys.stderr)
        return 2

    targets = []
    if "--all" in argv:
        for d in sorted(KAKIS_RUNS_ROOT.iterdir()):
            if d.is_dir() and (d / "kakis_state.json").is_file():
                targets.append(d)
    else:
        for a in argv:
            if a.startswith("--"):
                continue
            d = Path(a).expanduser()
            if d.is_dir() and (d / "kakis_state.json").is_file():
                targets.append(d)
    if not targets:
        print("ERROR: no run workspaces found", file=sys.stderr)
        return 2

    errors = []
    total_a = total_c = 0
    for ws in targets:
        try:
            run_id, a, c, ok = export_run(base, ws, errors)
        except Exception as e:
            errors.append(f"{ws.name}: {e}")
            continue
        total_a += a
        total_c += c
        print(f"{run_id}: {a} artifacts, {c} calls, ok={ok}")

    req(base, "POST", "/kakis_runs,kakis_artifacts,kakis_calls/refresh")
    print(f"total: {len(targets)} runs, {total_a} artifacts, {total_c} calls")
    if errors:
        print("ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
