# Harness & endpoint verification recipe

Copy-paste verification for the aios skillset's runtime dependencies. Use when asked "is it set up to run", or after any config/env change. All commands are read-only except the export re-run (idempotent).

## 1. Env keys (per-machine settings live in ~/.hermes/.env)

```bash
grep -E '^(AIOS_OPENSEARCH|AIOS_QWEN_BASE_URL|AIOS_QWEN_MODEL|AIOS_QWEN_API_KEY|TELEGRAM_BOT_TOKEN|TELEGRAM_HOME_CHANNEL)=' ~/.hermes/.env
```

- `AIOS_OPENSEARCH` — kakis_export.py mirror target; missing → mirroring silently skipped (exit 4), runs still work locally.
- `AIOS_QWEN_BASE_URL` / `AIOS_QWEN_MODEL` — Bob's qwen endpoint (resolved process env → `~/.hermes/.env`; optional `AIOS_QWEN_API_KEY`, default `dummy`); missing → no OPENAI_* injected, qwen uses its own config.
- `TELEGRAM_*` — gate + notification delivery. Verify presence only; never probe with a test message to the user's channel — the gate send printing `sent` is itself the connectivity check.

## 2. Endpoints

```bash
OS="${AIOS_OPENSEARCH:-<from ~/.hermes/.env>}"   # no built-in default

curl -s -m 5 "$OS/" | head -3                    # cluster info
curl -s -m 5 "$OS/_cat/aliases/kakis_*?v"        # expect 4 aliases → _v1 indices
# end-to-end (idempotent re-export of an existing run):
python3 ~/.hermes/skills/aios/kakis/scripts/kakis_export.py ~/.hermes/kakis-runs/<slug>_<ts>   # exit 0 = mirror wired

curl -s -m 5 http://llama.local:11435/v1/models  # served model ids — compare to harness configs
```

## 3. Harness binaries (NON-interactive shell)

```bash
for b in opencode hermes qwen dsh; do printf '%-10s ' "$b"; command -v "$b" || echo MISSING; done
```

Binaries whose PATH export lives in `~/.bashrc` are invisible here (Bob's preflight `shutil.which` shares the dispatcher's PATH). Fix: `ln -s <real path> ~/.local/bin/` — `~/.local/bin` is always on PATH; `~/.bashrc`-only dirs (e.g. `~/.opencode/bin`) are not.

## 4. Per-harness live test (exactly as the adapters build the commands)

Trivial one-word prompt keeps cost near zero. Run from a scratch dir, each wrapped in `timeout 240`:

```bash
# opencode
timeout 240 opencode run --format json "Reply with exactly one word: OK"
# hermes (bob-worker profile + recursion guard)
timeout 240 env HERMES_PROFILE=bob-worker HERMES_HOME=$HOME/.hermes hermes chat -q "Reply with exactly one word: OK" --quiet --ignore-rules
# qwen (endpoint from AIOS_QWEN_* — env or ~/.hermes/.env)
timeout 240 env OPENAI_API_KEY=dummy OPENAI_BASE_URL=<base> OPENAI_MODEL=<model> qwen --bare -p "Reply with exactly one word: OK" --output-format text
# dsh (read-only sandbox; endpoint + model id come from ~/.dsh/settings.yaml)
timeout 240 env DSH_PERMISSION_MODE=read-only DSH_HOME=$HOME/.dsh DUMMY_API_KEY=dummy dsh --profile headless "Reply with exactly one word: OK"
```

Pass = exit 0 with the expected word in the output.

## 5. End-to-end through the real dispatcher

```bash
timeout 300 python3 ~/.hermes/skills/aios/bob/scripts/bob_dispatch.py --prompt "Reply with exactly one word: OK" --harnesses qwen --timeout 240
```

Single-harness runs skip the synthesizer's LLM calls (single plan returned as-is), so this is cheap. Expect per-harness status, `Plan saved to:`, `Workspace:`, exit 0. A status of `partial` is USABLE — Bob treats `ok` and `partial` alike (it comes from the normalizer's fallback passes); judge by plan content, not the status string. The completion Telegram notification is standard dispatch behavior, not a probe — don't suppress it or be surprised by it.

## 6. Where machine-specific values actually live

- **qwen**: `AIOS_QWEN_*` in `~/.hermes/.env` (no default in the repo) or qwen's own `~/.config/qwen`
- **dsh**: `~/.dsh/settings.yaml` — provider baseURL + model id; the id must match the endpoint's served id (`/v1/models`); display names are cosmetic
- **opencode**: `~/.config/opencode/opencode.jsonc` (legacy `~/.opencode/`)
- **hermes**: bob-worker profile (`~/.hermes/profiles/bob-worker`), inherits the default profile's model/provider
