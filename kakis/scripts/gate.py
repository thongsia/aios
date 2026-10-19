#!/usr/bin/env python3
"""Telegram gate and notification helper for Kakis workflow.

Usage:
    python3 gate.py gate --message "..." --workspace /path [--timeout 3600]
    python3 gate.py notify --message "..." --workspace /path

As a module:
    from gate import gate, send_notification
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

APPROVE = {"proceed", "yes", "go", "continue", "ok", "okay", "sure",
           "do it", "agree", "approve", "forward", "next", "yep", "yea", "yup"}
REJECT = {"stop", "no", "abort", "cancel", "halt", "skip", "nah",
           "decline", "reject", "dont", "don't", "later", "not now", "pass"}

def _env(path: str) -> str | None:
    """Read env var from ~/.hermes/.env."""
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            if k == path:
                return v
    return None

def _env_path() -> str:
    return os.path.expanduser("~/.hermes/.env")

def _read_env(name: str) -> str | None:
    path = _env_path()
    if not os.path.exists(path):
        return None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                if k == name:
                    return v
    return None

def log_notification(workspace: str, text: str) -> None:
    """Append timestamped entry to notification.log in workspace."""
    log_path = os.path.join(workspace, "notification.log")
    ts = datetime.now(timezone.utc).isoformat()
    os.makedirs(workspace, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"[{ts}] {text}\n")

def send_telegram(message: str) -> bool:
    """Send via 'hermes send --to telegram'. Returns True on success."""
    try:
        result = subprocess.run(
            ["hermes", "send", "--to", "telegram", message],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False

def send_notification(message: str, workspace: str, attachment_path: str = None) -> bool:
    """Send via Telegram; fall back to notification.log.
    If attachment_path is given, send it as a second message after the main one."""
    ok = send_telegram(message)
    if ok and attachment_path:
        try:
            with open(attachment_path) as f:
                attachment = f.read()
            # Truncate very long attachments
            if len(attachment) > 4000:
                attachment = attachment[:3500] + "\n\n... (truncated)"
            send_telegram(f"📋 ATTACHMENT:\n\n{attachment}")
        except Exception:
            pass
    if not ok:
        log_notification(workspace, f"[TELEGRAM BYPASS] {message}")
    return ok

def classify_reply(text: str) -> str:
    """Classify a reply as proceed/abort/unrecognized."""
    t = text.strip().lower()
    if any(k in t for k in APPROVE):
        return "proceed"
    if any(k in t for k in REJECT):
        return "abort"
    return "unrecognized"


def _load_state(workspace: str) -> dict:
    path = os.path.join(workspace, "kakis_state.json")
    with open(path) as f:
        return json.load(f)

def _save_state(workspace: str, state: dict) -> None:
    """Atomic write — write to .tmp then rename."""
    path = os.path.join(workspace, "kakis_state.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.rename(tmp, path)


def gate(message: str, workspace: str, send_only: bool = True) -> str:
    """Send gate message via Telegram. Returns 'sent' or 'bypass'.

    Records gate_timestamp in kakis_state.json so the gate_poller can
    auto-proceed after timeout.

    Gates do NOT poll the Telegram Bot API (the Hermes gateway consumes
    all updates). Instead, the agent sends the message, saves gate_waiting
    in kakis_state.json, and stops. When the user replies, the Hermes
    gateway delivers it to the agent, which classifies it via classify_reply().
    """
    # Record gate timestamp for auto-proceed
    state = _load_state(workspace)
    state["gate_timestamp"] = datetime.now(timezone.utc).isoformat()
    _save_state(workspace, state)

    ok = send_telegram(message)
    if not ok:
        log_notification(workspace, f"[GATE BYPASS] {message} — Telegram unavailable, auto-proceeding.")
        return "bypass"
    return "sent"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kakis Telegram gate helper")
    sub = parser.add_subparsers(dest="cmd")

    g = sub.add_parser("gate")
    g.add_argument("--message", required=True)
    g.add_argument("--workspace", required=True)

    n = sub.add_parser("notify")
    n.add_argument("--message", required=True)
    n.add_argument("--workspace", required=True)

    c = sub.add_parser("classify")
    c.add_argument("--text", required=True)

    args = parser.parse_args()
    if args.cmd == "gate":
        result = gate(args.message, args.workspace)
        print(result)
    elif args.cmd == "notify":
        send_notification(args.message, args.workspace)
    elif args.cmd == "classify":
        print(classify_reply(args.text))
    else:
        parser.print_help()
