#!/usr/bin/env python3
"""Gate poller for Kakis workflow — checks for pending gates and auto-proceeds after timeout.

Runs as a cron job (no_agent=True) every 10 minutes.
Auto-proceeds a gate if it has been waiting for GATE_TIMEOUT_SECONDS (default 3600).
On decision, writes a .decided sentinel so subsequent runs exit silently.

Usage as cron script:
    python3 gate_poller.py --workspace /path/to/run

Usage standalone:
    python3 gate_poller.py scan  (scan all kakis-runs)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

GATE_TIMEOUT_SECONDS = 3600  # 1 hour
KAKIS_RUNS_DIR = os.path.expanduser("~/.hermes/kakis-runs")
KAKIS_OFFSETS_DIR = os.path.expanduser("~/.hermes/kakis-offsets")


def load_state(workspace: str) -> dict:
    path = os.path.join(workspace, "kakis_state.json")
    with open(path) as f:
        return json.load(f)


def save_state(workspace: str, state: dict) -> None:
    """Atomic write — write to .tmp then rename."""
    path = os.path.join(workspace, "kakis_state.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.rename(tmp, path)


def log_notification(workspace: str, text: str) -> None:
    log_path = os.path.join(workspace, "notification.log")
    ts = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(f"[{ts}] {text}\n")


def decided_path(workspace: str, gate: str) -> str:
    """Per-gate sentinel. A run has MULTIPLE auto-advancing gates (gate1, gate2):
    a single shared .gate_decided sentinel made the gate2 poller exit silently
    because gate1's sentinel was still present (incident 2026-10-24:
    gate2 never auto-proceeded, gate waited 4h until manual reply)."""
    return os.path.join(workspace, f".gate_decided_{gate}")


def auto_proceed(workspace: str, state: dict) -> None:
    """Auto-proceed the current gate: update state, write sentinel, log."""
    gate_label = state.get("gate", "unknown")
    ts = datetime.now(timezone.utc).isoformat()

    log_notification(workspace,
        f"[AUTO-PROCEED] Gate '{gate_label}' auto-proceeded after {GATE_TIMEOUT_SECONDS}s timeout at {ts} UTC. "
        f"Gate was set at {state.get('gate_timestamp', 'unknown')}.")

    # Update state: clear gate_waiting, advance phase
    state["gate_waiting"] = False
    state["gate_auto_proceeded"] = True

    # Advance phase based on current gate
    if state.get("gate") == "gate1":
        state["phase"] = "bob"
    elif state.get("gate") == "gate2":
        state["phase"] = "execute"

    save_state(workspace, state)

    # Write per-gate sentinel so cron stops polling this gate
    with open(decided_path(workspace, gate_label), "w") as f:
        f.write(f"auto_proceed at {ts}\n")

    print(f"AUTO-PROCEED: {workspace} gate={gate_label} -> phase={state['phase']}")


def check_gate(workspace: str) -> bool:
    """Check a single run workspace. Returns True if action was taken."""
    state = load_state(workspace)

    # Only act if gate is waiting
    if not state.get("gate_waiting"):
        return False

    # If THIS gate is already decided, skip (per-gate sentinel)
    if os.path.exists(decided_path(workspace, state.get("gate", "unknown"))):
        return False

    gate_ts = state.get("gate_timestamp")
    if not gate_ts:
        return False

    # Parse timestamp
    try:
        if isinstance(gate_ts, (int, float)):
            elapsed = time.time() - gate_ts
        else:
            # ISO string
            if gate_ts.endswith("Z"):
                gate_ts = gate_ts[:-1] + "+00:00"
            ts = datetime.fromisoformat(gate_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
    except (ValueError, TypeError):
        return False

    if elapsed >= GATE_TIMEOUT_SECONDS:
        auto_proceed(workspace, state)
        return True

    return False


def scan_all() -> int:
    """Scan all kakis run workspaces. Returns count of auto-proceeds."""
    if not os.path.isdir(KAKIS_RUNS_DIR):
        return 0

    count = 0
    for entry in sorted(os.listdir(KAKIS_RUNS_DIR)):
        ws = os.path.join(KAKIS_RUNS_DIR, entry)
        if os.path.isdir(ws) and os.path.exists(os.path.join(ws, "kakis_state.json")):
            if check_gate(ws):
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Kakis gate poller")
    sub = parser.add_subparsers(dest="cmd")

    scan_p = sub.add_parser("scan", help="Scan all kakis runs for expiring gates")
    single_p = sub.add_parser("check", help="Check a single workspace")
    single_p.add_argument("--workspace", required=True)

    args = parser.parse_args()

    if args.cmd == "scan" or args.cmd is None:
        count = scan_all()
        sys.exit(0)  # Always exit 0 — silence on no-op

    elif args.cmd == "check":
        if check_gate(args.workspace):
            sys.exit(0)
        sys.exit(0)  # Silent on no-op


if __name__ == "__main__":
    main()
