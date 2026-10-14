#!/usr/bin/env python3
"""
Bob Dispatch — Main orchestrator for the fan-out/fan-in planning workflow.

Usage:
    python3 bob_dispatch.py --prompt "Build a REST API with FastAPI"
    python3 bob_dispatch.py --prompt "..." --harnesses opencode,hermes
    python3 bob_dispatch.py --cleanup

Dispatches a user prompt to multiple AI coding-agent harnesses in parallel,
collects their individual plans, normalizes them, scores them, and synthesizes
a best-of-breed merged plan.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add scripts dir to path for imports
SCRIPTS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPTS_DIR))

from adapters import get_adapter
from prompt_template import build_plan_prompt
from normalizer import normalize
from scorer import score_plan
from synthesizer import synthesize


# API key env vars to pass through to all harnesses
API_KEY_VARS = [
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
    "DSH_API_KEY", "NVIDIA_API_KEY",
]

WORKSPACE_ROOT = Path.home() / ".hermes" / "bob-workspaces"
LAST_RUN_FILE = WORKSPACE_ROOT / ".last_run"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bob: fan-out/fan-in planning orchestrator")
    parser.add_argument("--prompt", "-p", type=str, help="User prompt to dispatch")
    parser.add_argument("--cleanup", action="store_true", help="Clean up previous workspace")
    parser.add_argument("--timeout", type=int, default=1800, help="Per-harness timeout (seconds)")
    parser.add_argument("--harnesses", type=str, default="",
                        help="Comma-separated list of harnesses (default: all available)")
    parser.add_argument("--min-success", type=int, default=1,
                        help="Minimum harnesses that must succeed (default: 1)")
    return parser.parse_args()


def cleanup_old_workspace() -> None:
    """Remove the previous session's workspace."""
    if LAST_RUN_FILE.exists():
        path = LAST_RUN_FILE.read_text().strip()
        ws = Path(path)
        if ws.is_dir():
            shutil.rmtree(ws)
            print(f"[bob] Cleaned up workspace: {ws}")
        LAST_RUN_FILE.unlink()
    else:
        print("[bob] No previous workspace to clean up.")


def create_workspace() -> Path:
    """Create a fresh workspace directory for this invocation."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    ws = tempfile.mkdtemp(prefix="bob_", dir=str(WORKSPACE_ROOT))
    return Path(ws)


def check_harness_availability(harness_names: list[str]) -> list[str]:
    """Check which harnesses are actually installed on PATH."""
    available = []
    for name in harness_names:
        adapter_cls = get_adapter(name)
        if adapter_cls and adapter_cls("").is_available():
            available.append(name)
        else:
            print(f"[bob] Harness '{name}' not available — skipping.")
    return available


def ensure_bob_worker_profile() -> bool:
    """Ensure the bob-worker Hermes profile exists (auto-create if missing)."""
    result = subprocess.run(
        ["hermes", "profile", "list"],
        capture_output=True, text=True,
    )
    if "bob-worker" in result.stdout:
        return True

    print("[bob] Creating bob-worker profile for isolated child processes...")
    subprocess.run(
        ["hermes", "profile", "create", "bob-worker", "--clone", "--no-alias"],
        capture_output=True, text=True,
    )
    # Verify creation succeeded
    result2 = subprocess.run(
        ["hermes", "profile", "list"],
        capture_output=True, text=True,
    )
    if "bob-worker" in result2.stdout:
        print("[bob] bob-worker profile created successfully.")
        return True
    else:
        print("[bob] ERROR: Failed to create bob-worker profile.", file=sys.stderr)
        return False


def prepare_isolated_home(workspace: Path, harness_name: str,
                          original_env: dict) -> Path:
    """
    Create an isolated HOME for a harness and copy its config into it.

    Returns the isolated HOME path.
    """
    isolated_home = workspace / harness_name / "home"
    isolated_home.mkdir(parents=True, exist_ok=True)

    original_home = Path(original_env.get("HOME", "~")).expanduser()

    # Copy harness-specific config dirs
    # NOTE: Do NOT copy .hermes/ for the hermes harness — it uses HERMES_PROFILE
    # env var to locate its profile, and copying .hermes/ causes infinite path
    # nesting (bob-workspaces lives inside .hermes/).
    #
    # Config locations (legacy → modern):
    #   opencode: ~/.opencode/  →  ~/.config/opencode/
    #   qwen:     ~/.qwen-code/
    #   dsh:      ~/.dsh/
    config_dirs = {
        "opencode": [".opencode", ".config/opencode"],
        "qwen": [".qwen-code"],
        "dsh": [".dsh"],
    }

    for dir_rel in config_dirs.get(harness_name, []):
        src = original_home / dir_rel
        if src.is_dir():
            dst = isolated_home / dir_rel
            # Skip heavy files for opencode
            if dir_rel == ".opencode":
                for item in src.iterdir():
                    if item.name not in ("node_modules", "bin", "package-lock.json"):
                        if item.is_file():
                            dst.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, dst / item.name)
            else:
                shutil.copytree(src, dst, dirs_exist_ok=True)

    return isolated_home


def build_harness_env(original_env: dict) -> dict:
    """Build environment dict with API keys preserved."""
    env = original_env.copy()
    for key in API_KEY_VARS:
        if key in original_env:
            env[key] = original_env[key]
    return env


def run_harness(name: str, prompt: str, workspace: Path,
                timeout: int, original_env: dict) -> dict:
    """Run a single harness and return its raw result."""
    adapter_cls = get_adapter(name)
    if not adapter_cls:
        return {"harness": name, "error": f"Unknown harness: {name}"}

    # Create isolated workspace for this harness
    harness_dir = workspace / name
    harness_dir.mkdir(parents=True, exist_ok=True)

    # Prepare isolated HOME
    isolated_home = prepare_isolated_home(workspace, name, original_env)

    adapter = adapter_cls(str(harness_dir), timeout=timeout)

    # For Hermes, ensure bob-worker profile exists
    if name == "hermes" and hasattr(adapter, "ensure_bob_worker_profile"):
        adapter.ensure_bob_worker_profile()

    # Override HOME to the isolated directory
    env = build_harness_env(original_env)
    env["HOME"] = str(isolated_home)
    env["PATH"] = original_env["PATH"]  # Preserve PATH

    start = time.time()
    try:
        result = adapter.run(prompt, env)
        duration = time.time() - start
        return {
            "harness": name,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "duration_s": duration,
        }
    except Exception as e:
        duration = time.time() - start
        return {
            "harness": name,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "duration_s": duration,
        }


def main():
    args = parse_args()

    # Cleanup mode
    if args.cleanup:
        cleanup_old_workspace()
        return

    if not args.prompt:
        print("[bob] ERROR: --prompt is required.", file=sys.stderr)
        print("Usage: bob_dispatch.py --prompt 'Your implementation request'")
        sys.exit(1)

    print(f"[bob] Dispatching prompt to harnesses...")
    print(f"[bob] Prompt: {args.prompt[:100]}{'...' if len(args.prompt) > 100 else ''}\n")

    # Preflight checks
    original_env = os.environ.copy()
    workspace = create_workspace()

    # Record workspace for next-invocation cleanup
    LAST_RUN_FILE.write_text(str(workspace))

    # Determine which harnesses to use
    if args.harnesses:
        requested = [h.strip() for h in args.harnesses.split(",")]
    else:
        requested = ["opencode", "hermes", "qwen", "dsh"]

    available = check_harness_availability(requested)
    if not available:
        print("[bob] ERROR: No harnesses available. Install at least one.", file=sys.stderr)
        sys.exit(1)

    # Ensure bob-worker profile (needed by hermes adapter and synthesis)
    ensure_bob_worker_profile()

    # Build standardized prompt
    plan_prompt = build_plan_prompt(args.prompt)

    # Fan-out: spawn all harnesses in parallel
    print(f"[bob] Running {len(available)} harnesses: {', '.join(available)}\n")
    results = []

    with ThreadPoolExecutor(max_workers=len(available)) as executor:
        futures = {
            executor.submit(
                run_harness, name, plan_prompt, workspace,
                args.timeout, original_env
            ): name
            for name in available
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                results.append(result)
                status = "OK" if result.get("exit_code", 1) == 0 else f"FAILED (code {result.get('exit_code')})"
                print(f"[bob] {name}: {status} ({result['duration_s']:.1f}s)")
            except Exception as e:
                results.append({
                    "harness": name,
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": -1,
                    "duration_s": 0,
                })
                print(f"[bob] {name}: ERROR ({e})")

    # Normalize all outputs
    print("\n[bob] Normalizing outputs...")
    normalized = []
    for r in results:
        n = normalize(
            harness_name=r["harness"],
            raw_text=r.get("stdout", ""),
            exit_code=r.get("exit_code", -1),
            duration=r.get("duration_s", 0),
        )
        normalized.append(n)
        print(f"  {n['harness']}: status={n['status']}, "
              f"steps={len(n['plan_sections'].get('steps', []))}, "
              f"exit={n['exit_code']}")

    # Partial-failure tolerance: need 2+ usable (ok or partial)
    usable = [n for n in normalized if n["status"] in ("ok", "partial")]
    failed = [n for n in normalized if n["status"] == "failed"]

    if failed:
        print(f"\n[bob] {len(failed)} harness(es) failed:")
        for f in failed:
            print(f"  - {f['harness']}: exit_code={f['exit_code']}")

    if len(usable) < args.min_success:
        if len(usable) == 0:
            print("\n[bob] ABORT: No harnesses produced usable output.", file=sys.stderr)
            for n in normalized:
                print(f"  {n['harness']}: {n['status']}", file=sys.stderr)
            sys.exit(1)
        # Continue with what we have
        print(f"\n[bob] Only {len(usable)}/{len(available)} harness(es) produced "
              f"usable output (min_success={args.min_success}). "
              f"Continuing anyway.", file=sys.stderr)
        for n in normalized:
            print(f"  {n['harness']}: {n['status']}", file=sys.stderr)

    # Score plans
    print("\n[bob] Scoring plans...")
    scored = []
    for plan in usable:
        s = score_plan(plan)
        scored.append((plan, s))
        print(f"  {plan['harness']}: weighted={s['weighted_score']} "
              f"(complete={s['completeness']}, specific={s['specificity']}, "
              f"feasible={s['feasibility']})")

    # Synthesize
    print("\n[bob] Synthesizing best-of-breed plan...\n")
    result = synthesize(
        plans=[s[0] for s in scored],
        scores=[s[1] for s in scored],
        user_prompt=args.prompt,
        timeout=args.timeout,
    )

    # Unpack SynthesisResult
    plan_text = result.plan_text
    metadata = result.metadata or {}

    # Append augmentation log if present
    aug_log = metadata.get("augmentation_log")
    if aug_log:
        plan_text += "\n## Augmentation Log\n"
        for entry in aug_log:
            plan_text += f"- {entry}\n"

    print(plan_text)

    # Save synthesized plan as markdown
    plan_md = workspace / "plan.md"
    with open(plan_md, "w") as f:
        f.write(plan_text)
    print(f"\n[bob] Plan saved to: {plan_md}")

    # Save raw results to workspace for debugging
    results_file = workspace / "results.json"
    with open(results_file, "w") as f:
        json.dump({
            "normalized": [
                {**n, "raw_stdout": r.get("stdout", "")[:50000]}
                for n, r in zip(normalized, results)
            ],
            "scores": {plan["harness"]: score for plan, score in scored},
            "evaluation": metadata.get("evaluation"),
        }, f, indent=2, default=str)

    print(f"\n[bob] Results saved to: {results_file}")
    print(f"[bob] Workspace: {workspace}")

    # Telegram notification with plan attachment
    try:
        msg_lines = [
            "Bob planning complete.",
            "Harnesses: " + ", ".join(available),
            "Usable: %d/%d" % (len(usable), len(available)),
            "Workspace: " + str(workspace),
            "",
            "See attached synthesized plan.",
            "MEDIA:" + str(plan_md),
        ]
        msg = "\n".join(msg_lines)
        send_cmd = 'hermes send --to telegram --quiet "%s"' % msg.replace('"', '\\"')
        send_result = subprocess.run(send_cmd, shell=True, capture_output=True, text=True)
        if send_result.returncode == 0:
            print("[bob] Telegram notification sent with plan attachment.")
        else:
            print(f"[bob] Telegram notification failed: {send_result.stderr.strip()}", file=sys.stderr)
    except Exception as e:
        print(f"[bob] Telegram notification error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
