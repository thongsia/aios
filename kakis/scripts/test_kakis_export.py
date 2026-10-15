"""Unit tests for kakis_export.py pure functions."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import kakis_export as ke  # noqa: E402


def test_doc_id_artifact_deterministic():
    a = ke.doc_id_artifact("run1", "dory/plan_1.txt")
    b = ke.doc_id_artifact("run1", "dory/plan_1.txt")
    c = ke.doc_id_artifact("run1", "dory/plan_2.txt")
    d = ke.doc_id_artifact("run2", "dory/plan_1.txt")
    assert a == b
    assert a != c
    assert a != d


def test_norm_ts():
    assert ke.norm_ts("2026-10-14T12:42:13+0800") == "2026-10-14T12:42:13+08:00"
    assert ke.norm_ts("2026-10-14T08:16:55.019505+00:00") == "2026-10-14T08:16:55.019505+00:00"
    assert ke.norm_ts("2026-10-06T01:40:31.568857") == "2026-10-06T01:40:31.568857+08:00"
    assert ke.norm_ts("") is None
    assert ke.norm_ts(None) is None
    assert ke.norm_ts("not-a-date") is None


def test_classify():
    cases = [
        ("kakis_state.json", "state", "execute"),
        ("feasibility.md", "feasibility", "research"),
        ("final_plan.txt", "plan", "dory"),
        ("dory_brief.md", "brief", "dory"),
        ("bob_plan.md", "bob_plan", "bob"),
        ("bob_results.json", "bob_results", "bob"),
        ("gate1_message.txt", "gate_message", "gate1"),
        ("batch_a_report.json", "execution_report", "execute"),
        ("dory/prompt_3.txt", "prompt", "dory"),
        ("dory/plan_3.txt", "plan", "dory"),
        ("dory/review_3.txt", "review", "dory"),
        ("bob/plan.md", "bob_plan", "bob"),
        ("bob/qwen/output.txt", "other", "bob"),
        ("device_results.md", "device", "execute"),
        ("results_2022plus_robustness.csv", "data", "execute"),
    ]
    for rel, want_kind, want_phase in cases:
        kind, phase, _module = ke.classify(rel, "execute")
        assert kind == want_kind, f"{rel}: kind {kind} != {want_kind}"
        assert phase == want_phase, f"{rel}: phase {phase} != {want_phase}"


def test_artifact_doc_content_policy(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    try:
        small = d / "small.txt"
        small.write_text("hello world" * 10)
        doc, ok = ke.artifact_doc("run1", "small.txt", small, "other", "execute", None)
        assert ok == "ok"
        assert doc["content"] == "hello world" * 10
        assert doc["sha256"] == __import__("hashlib").sha256(b"hello world" * 10).hexdigest()
        assert doc["head"].startswith("hello world")

        big = d / "big.md"
        big.write_text("x" * (ke.CONTENT_LIMIT + 10))
        doc2, ok2 = ke.artifact_doc("run1", "big.md", big, "other", "execute", None)
        assert ok2 == "ok"
        assert "content" not in doc2
        assert len(doc2["head"]) <= ke.HEAD_LIMIT
        assert doc2["sha256"]

        binary = d / "img.png"
        binary.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        doc3, ok3 = ke.artifact_doc("run1", "img.png", binary, "other", "execute", None)
        assert ok3 == "ok"
        assert "content" not in doc3
        assert doc3["sha256"]
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_calls_from_jsonl(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    try:
        p = d / "calls.jsonl"
        p.write_text(
            json.dumps({"seq": 1, "module": "dory_planner", "ts": "2026-10-14T13:00:00+08:00",
                        "goal_head": "g", "input_refs": ["dory/prompt_1.txt"],
                        "status": "ok", "ended_ts": "2026-10-14T13:09:00+08:00",
                        "result_summary_head": "r", "output_refs": ["dory/plan_1.txt"]}) + "\n"
            + "not json\n"
            + json.dumps({"module": "no-seq"}) + "\n"
        )
        calls = ke.calls_from_jsonl(p)
        assert len(calls) == 1
        c = calls[0]
        assert c["seq"] == 1 and c["module"] == "dory_planner"
        assert c["started_at"] == "2026-10-14T13:00:00+08:00"
        assert c["input_refs"] == ["dory/prompt_1.txt"]
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_calls_dedupe():
    primary = [{"seq": 1, "module": "dory_planner"}, {"seq": 2, "module": "dory_reviewer"}]
    additions = [{"seq": 1, "module": "dory_planner"},  # dup -> dropped
                 {"seq": 3, "module": "igor"}]          # new -> kept
    out = ke.dedupe_calls(primary, additions)
    pairs = {(c["seq"], c["module"]) for c in out}
    assert pairs == {(1, "dory_planner"), (2, "dory_reviewer"), (3, "igor")}
    assert out[0]["seq"] == 1 and out[-1]["seq"] == 3


def test_reconstruct_calls(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    try:
        run_ws = d / "run"
        run_ws.mkdir()
        dory = d / "dory"
        dory.mkdir()
        (run_ws / "feasibility.md").write_text("=== FEASIBILITY: GO ===")
        (run_ws / "bob_results.json").write_text(json.dumps({
            "normalized": [{"harness": "hermes", "status": "ok", "exit_code": 0, "duration_s": 100},
                           {"harness": "qwen", "status": "timeout", "exit_code": 124, "duration_s": 900}],
            "evaluation": {"best_plan_harness": "hermes"},
        }))
        (run_ws / "batch_a_report.json").write_text("{}")
        for n in (1, 2):
            (dory / f"prompt_{n}.txt").write_text(f"p{n}")
            (dory / f"plan_{n}.txt").write_text(f"plan{n}")
            (dory / f"review_{n}.txt").write_text(f"rev{n}")
        calls = ke.reconstruct_calls(run_ws, dory, None, "run1", {"goal": "g", "gate0_verdict": "GO"})
        modules = [(c["seq"], c["module"], c.get("iteration")) for c in calls]
        # dory: planner1, reviewer1, planner2, reviewer2
        assert ("dory_planner", 1) in [(m, i) for _, m, i in modules]
        assert ("dory_reviewer", 2) in [(m, i) for _, m, i in modules]
        bob = [c for c in calls if c["module"] == "bob_harness"]
        assert len(bob) == 2
        assert {c["variant"] for c in bob} == {"hermes", "qwen"}
        assert any(c["status"] == "timeout" for c in bob)
        assert any(c["module"] == "bob_synth" for c in calls)
        assert any(c["module"] == "execution_batch" for c in calls)
        assert any(c["module"] == "igor" and c["result_summary"] == "verdict=GO" for c in calls)
        seqs = [c["seq"] for c in calls]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_walk_workspace_pruning(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    try:
        import shutil
        root = d / "bob"
        (root / "home" / ".cache").mkdir(parents=True)
        (root / "home" / ".cache" / "x.bin").write_bytes(b"x")
        (root / "qwen" / "home").mkdir(parents=True)
        (root / "qwen" / "home" / "session.jsonl").write_text("{}")
        (root / "qwen" / "out.txt").write_text("o")
        (root / "plan.md").write_text("plan")
        got = {rel for rel, _ in ke.walk_workspace(root, "bob")}
        assert got == {"bob/plan.md", "bob/qwen/out.txt"}, got
        # run workspace: 'home' is NOT pruned, dotfiles/dirs are
        root2 = d / "run"
        (root2 / "home").mkdir(parents=True)
        (root2 / "home" / "notes.txt").write_text("n")
        (root2 / ".hidden").mkdir()
        (root2 / ".hidden" / "secret.txt").write_text("s")
        (root2 / "final_plan.txt").write_text("p")
        got2 = {rel for rel, _ in ke.walk_workspace(root2, "")}
        assert got2 == {"home/notes.txt", "final_plan.txt"}, got2
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
