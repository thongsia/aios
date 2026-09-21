# DeepSeek Harness (dsh) CLI Configuration

DeepSeek Harness (`@deepseek-ai/dsh` on npm) uses a YAML-based provider config in `~/.dsh/settings.yaml`.

## Installation

```bash
npm install -g @deepseek-ai/dsh@latest
```

## Local Endpoint Configuration

Create `~/.dsh/settings.yaml`:

```yaml
llm-pi-ai:
  providers:
    local-llama:
      displayName: Local LLaMA
      api: openai-completions
      baseURL: http://llama.local:11435/v1
      apiKeyEnv: DUMMY_API_KEY    # env var name (not the key itself)
      compat:
        supportsDeveloperRole: false
        maxTokensField: max_tokens
      models:
        - id: deepseek-v4-flash   # maps to the default model below
          name: Qwen3.8-27B       # actual model ID on the endpoint
          contextWindow: 131072
          maxTokens: 8192

agent-default-model:
  provider: local-llama
  model: deepseek-v4-flash
```

Then set the env var and run:

```bash
export DUMMY_API_KEY="dummy"   # dsh reads this from settings.yaml's apiKeyEnv
dsh --profile headless "your prompt"
```

## Key Points

- `apiKeyEnv` references an environment variable name, NOT the actual key
- The `models[].id` is the identifier used by `agent-default-model.provider`
- The `models[].name` is the model ID sent to the `/v1` endpoint
- `--profile headless` is the non-interactive mode; other profiles include `web` and `tui`
- `~/.dsh` is the default `$DSH_HOME`; override with `DSH_HOME` env var

## Patch Overlay

The `--patch` flag expects a YAML **array** of loader patch entries, NOT a flat key-value YAML. For simple config, use `settings.yaml` directly instead of `--patch`.
