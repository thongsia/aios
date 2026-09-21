#!/usr/bin/env python3
"""Telegram gate and notification helper for KAKIS workflow.

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

APPROVE = {"proceed", "yes", "go", "continue", "ok"}
REJECT = {"stop", "no", "abort", "cancel", "halt"}

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

def _get_telegram_updates(offset: int | None, limit: int = 1) -> list:
    """Poll Telegram getUpdates API directly."""
    token = _read_env("TELEGRAM_BOT_TOKEN")
    if not token:
        return []
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = f"limit={limit}"
    if offset is not None:
        params += f"&offset={offset}"
    try:
        result = subprocess.run(
            ["curl", "-s", f"{url}?{params}", "--max-time", "15"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        if data.get("ok"):
            return data.get("result", [])
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired, Exception):
        pass
    return []

def poll_telegram_reply(workspace: str, timeout: int = 3600, run_id: str = "") -> str:
    """Poll for reply via Telegram Bot API. Returns proceed/abort/timeout."""
    offset_file = os.path.expanduser(f"~/.hermes/kakis-offsets/{run_id}.offset") if run_id else None
    offset = None
    if offset_file:
        try:
            os.makedirs(os.path.dirname(offset_file), exist_ok=True)
            if os.path.exists(offset_file):
                offset = int(open(offset_file).read().strip())
        except Exception:
            offset = None

    start = time.time()
    reprompted = False

    while time.time() - start < timeout:
        updates = _get_telegram_updates(offset, limit=10)
        if updates:
            for u in updates:
                update_id = u.get("update_id", offset)
                msg = u.get("message", {})
                # Save offset
                if offset_file and update_id:
                    try:
                        with open(offset_file, "w") as f:
                            f.write(str(update_id + 1))
                    except Exception:
                        pass
                text = (msg.get("text") or "").strip().lower()
                if not text:
                    continue
                # Check for run_id token match (fallback)
                if run_id and run_id not in (msg.get("reply_to_message", {}).get("text", "") or ""):
                    # Check if message contains run_id as token
                    if run_id not in text:
                        continue
                if any(k in text for k in APPROVE):
                    return "proceed"
                if any(k in text for k in REJECT):
                    return "abort"
                # Unrecognized — re-prompt once
                if not reprompted:
                    send_telegram("Reply with 'proceed' or 'stop'.")
                    reprompted = True
                    return poll_telegram_reply(workspace, timeout, run_id)
            break
        time.sleep(30)

    log_notification(workspace, "[TIMEOUT] No reply within 1 hour — auto-proceeding.")
    return "timeout"

def gate(message: str, workspace: str, timeout: int = 3600, run_id: str = "") -> str:
    """Send gate message, poll for reply, return decision.
    On Telegram failure, auto-proceeds with bypass logged."""
    ok = send_telegram(message)
    if not ok:
        log_notification(workspace, f"[GATE BYPASS] {message} — Telegram unavailable, auto-proceeding.")
        return "proceed"
    return poll_telegram_reply(workspace, timeout, run_id)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KAKIS Telegram gate helper")
    sub = parser.add_subparsers(dest="cmd")

    g = sub.add_parser("gate")
    g.add_argument("--message", required=True)
    g.add_argument("--workspace", required=True)
    g.add_argument("--timeout", type=int, default=3600)
    g.add_argument("--run-id", default="")

    n = sub.add_parser("notify")
    n.add_argument("--message", required=True)
    n.add_argument("--workspace", required=True)

    args = parser.parse_args()
    if args.cmd == "gate":
        result = gate(args.message, args.workspace, args.timeout, args.run_id)
        print(result)
    elif args.cmd == "notify":
        send_notification(args.message, args.workspace)
    else:
        parser.print_help()
