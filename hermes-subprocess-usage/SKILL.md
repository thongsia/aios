---
name: hermes-subprocess-usage
description: Use when spawning Hermes as a subprocess.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, subprocess, cli, spawning, automation, multi-agent, events-stream]
    related_skills: [hermes-agent, autonomous-ai-agents]
---

# Hermes as a Subprocess

Use this skill whenever you need to spawn `hermes` as a subprocess from Python, shell scripts, or orchestration code — for one-shot queries, multi-agent fan-out, CI/automation, or any programmatic usage.

## CLI Flag Differences (CRITICAL)

The `-z` (oneshot) and `chat -q` (query mode) have DIFFERENT flag support:

| Flag | `-z` (oneshot) | `chat -q` (query mode) |
|---|---|---|
| `--quiet` | NO | YES |
| `--ignore-rules` | YES | YES |
| `--max-turns` | NO | YES |
| `--ignore-user-config` | YES | YES |
| `--safe-mode` | YES | YES |

**Use `hermes chat -q "PROMPT"` instead of `hermes -z "PROMPT"` when you need `--quiet`, `--max-turns`, or `--reasoning`.**

```python
# WRONG — fails with exit code 2 (argument error)
subprocess.run(["hermes", "-z", prompt, "--quiet", "--ignore-rules", "--max-turns", "1"], ...)

# CORRECT
subprocess.run(["hermes", "chat", "-q", prompt, "--quiet", "--ignore-rules", "--max-turns", "1"], ...)
```

## Profile Isolation

When spawning child Hermes processes, prevent recursion (child spawning another child) by using a dedicated profile:

```python
env = os.environ.copy()
env["HERMES_PROFILE"] = "bob-worker"  # or any isolated profile name
```

Create the profile once:
```bash
hermes profile create bob-worker --clone --no-alias
```

## HOME Override and HERMES_HOME

If you override `HOME` for subprocess isolation (e.g., each agent gets its own temp home), Hermes can't find `~/.hermes/` profiles. Fix by setting `HERMES_HOME` explicitly:

```python
from pathlib import Path

env["HOME"] = "/tmp/isolated-home"        # Your isolated directory
env["HERMES_HOME"] = str(Path.home() / ".hermes")  # Real Hermes home
env["HERMES_PROFILE"] = "bob-worker"
```

**Use `Path.home()` (which uses pwd/realuid), NOT `os.environ.get("HOME")`** — the latter has already been overridden to the isolated directory at the point you build the env dict.

## Parsing Events-Stream Output

`hermes chat -q` (and `opencode`) output JSON events per line, not raw text:

```json
{"type":"step_start","timestamp":...,"part":{"type":"step-start"}}
{"type":"text","timestamp":...,"part":{"type":"text","text":"{\"overview\":...}"}}
{"type":"step_finish","timestamp":...,"part":{"type":"step-finish"}}
```

To extract the actual text response:

```python
import json

def extract_text_from_events(raw_text: str) -> str | None:
    text_parts = []
    for line in raw_text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):  # Skip non-object JSON
            continue
        if event.get("type") == "text":
            # Direct text field
            if "text" in event and isinstance(event["text"], str):
                text_parts.append(event["text"])
            # Nested in part
            elif "part" in event and isinstance(event["part"], dict):
                part_text = event["part"].get("text", "")
                if part_text and isinstance(part_text, str):
                    text_parts.append(part_text)
    return ''.join(text_parts) if text_parts else None
```

## Recommended Command for Automation

The most robust subprocess invocation:

```python
result = subprocess.run(
    ["hermes", "chat", "-q", prompt,
     "--quiet",           # suppress banners/spinners
     "--ignore-rules",    # skip AGENTS.md, skills, etc.
     "--max-turns", "1",  # single-turn only (no tool loops)
    ],
    capture_output=True,
    text=True,
    timeout=300,
    env=env,  # with HERMES_PROFILE and HERMES_HOME set
)
```

## Parsing LLM JSON Output (Structural Repair)

LLMs often produce structurally malformed JSON even when the content is correct. The most common error is a premature object-close on array termination:

```
BEFORE (invalid):  ..."]},  "assumptions": ...
AFTER (valid):     ..."],  "assumptions": ...
```

The `]` closes the array, but the LLM inserts a `}` before the comma, which `json.loads()` rejects as "Extra data".

**Fix**: Apply a regex repair before `json.loads()`:

```python
import re

def repair_llm_json(text: str) -> str:
    # Replace ]}, (with optional whitespace) with ],
    text = re.sub(r'\]\}\s*,', r'],', text)
    return text
```

Apply this repair after stripping markdown fences but before `json.loads()`. It is safe on valid JSON (the pattern `]},` only appears in the malformed case). See `references/llm-json-repair.md` for more patterns.

## Pitfalls

- **`hermes -z` with `--max-turns`** → exit code 2. Use `chat -q` instead.
- **`HOME` override breaks profile lookup** → always set `HERMES_HOME` alongside.
- **`os.environ["HOME"]` after override** → returns the isolated HOME, not the real one. Use `Path.home()` instead.
- **Events-stream output is not the final answer** → you must parse the text events. The raw stdout contains JSON metadata events that are not the model response.
- **LLM JSON is structurally malformed** → `json.loads()` fails even on valid-looking output. Run `_repair_llm_json()` (above) before parsing.
- **Synthesis recursion** → if the child Hermes process has access to the same tools/skills, it may try to re-run the orchestrator. Use `--ignore-rules` and a dedicated profile with minimal config.
- **Qwen Code hangs without `--bare`** → Qwen Code loads hooks/extensions/skills/MCP servers in non-interactive mode, which hang waiting for a TTY. Always use `--bare` to skip customizations. See `references/qwen-code-cli.md`.
- **DeepSeek Harness (`dsh`) uses `settings.yaml` for provider config** → Create `~/.dsh/settings.yaml` with the `llm-pi-ai.providers` block pointing to your local endpoint. Use `apiKeyEnv` (not `apiKey`) to reference an env var. See `references/deepseek-harness-cli.md`.
