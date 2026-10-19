# Harness Specifications

Per-harness CLI flags, binary names, verified commands, and quirks.

## Opencode

| Field | Value |
|-------|-------|
| **Binary** | `opencode` |
| **Installed at** | `~/.opencode/bin/opencode` |
| **Version** | 1.17.15 |
| **One-shot command** | `opencode run 'PROMPT'` |
| **Key flags** | `--model provider/model`, `--format json` (raw JSON events), `--thinking`, `-f file`, `--auto` (auto-approve), `--pure` (no plugins) |
| **Approval mode** | None — always can execute. Restrict via prompt instructions. |
| **Auth** | Provider env vars (e.g., `OPENROUTER_API_KEY`, `OPENAI_API_KEY`); also `opencode auth login` |
| **Config dir** | `~/.opencode/` |
| **PTY needed** | No for `run` mode |
| **Verified** | `opencode --version` → 1.17.15; `opencode run --help` confirms all flags |

## Hermes

| Field | Value |
|-------|-------|
| **Binary** | `hermes` |
| **Installed at** | `~/.local/bin/hermes` |
| **One-shot command** | `hermes -z 'PROMPT'` (top-level oneshot) |
| **Alternative** | `hermes chat -q 'PROMPT' -Q` (chat query, quiet) |
| **Key flags** | `-m MODEL`, `--provider PROVIDER`, `--reasoning LEVEL`, `-s SKILLS`, `-Q/--quiet`, `--max-turns N`, `--ignore-rules`, `--ignore-user-config`, `--yolo` |
| **Profile selection** | `HERMES_PROFILE=name` env var (no `--profile` CLI flag on `chat`) |
| **Recursion guard** | `HERMES_PROFILE=bob-worker` + `--ignore-rules` prevents the Bob skill from loading |
| **Auth** | `~/.hermes/.env` and `~/.hermes/config.yaml`; profiles inherit via `--clone` |
| **Config dir** | `~/.hermes/` (or per-profile `~/.hermes/profiles/NAME/`) |
| **Verified** | `hermes --version`; `hermes chat --help` confirms all flags |

## Qwen Code

| Field | Value |
|-------|-------|
| **Binary** | `qwen` |
| **Installed at** | `~/.local/bin/qwen` |
| **Version** | 0.22.0 |
| **One-shot command** | `qwen --bare -p "PROMPT" --output-format text` |
| **Key flags** | `--bare` (skip hooks/extensions), `--output-format text` (machine-parseable), `--approval-mode plan` (analysis-only) |
| **Auth** | `OPENAI_API_KEY` + `OPENAI_BASE_URL` env vars (points to local llama.cpp: `http://llama.local:11435/v1`) |
| **Config dir** | `~/.config/qwen/` |
| **PTY needed** | No for headless `-p` mode |
| **Status** | INSTALLED — available |

## DeepSeek Harness (dsh)

| Field | Value |
|-------|-------|
| **Binary** | `dsh` |
| **Installed at** | `~/.local/bin/dsh` |
| **Version** | 0.1.1-rc.2 |
| **Headless command** | `dsh --profile headless "PROMPT"` |
| **Permissions** | `DSH_PERMISSION_MODE=read-only` sandbox |
| **Auth** | `DUMMY_API_KEY` env var; settings in `~/.dsh/settings.yaml` pointing to local llama.cpp |
| **Config dir** | `~/.dsh/` (via `DSH_HOME`) |
| **PTY needed** | No for `--profile headless` |
| **Status** | INSTALLED — available |

## Verification Summary

| Harness | `which` check | Version/help check | Available |
|---------|--------------|-------------------|-----------|
| opencode | `/home/hteo/.opencode/bin/opencode` | `1.17.15` | YES |
| hermes | `/home/hteo/.local/bin/hermes` | confirmed | YES |
| qwen | `/home/hteo/.local/bin/qwen` | `0.22.0` | YES |
| dsh | `/home/hteo/.local/bin/dsh` | `0.1.1-rc.2` | YES |

## Notes

- Missing harnesses are gracefully skipped at runtime if 2+ remain.
- All harnesses that ARE available must have their API keys configured.
- The orchestrator (`bob_dispatch.py`) checks `which <binary>` at startup and only dispatches to available harnesses.
