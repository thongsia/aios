# Qwen Code CLI Configuration

Qwen Code (`@qwen-code/qwen-code` on npm) supports any OpenAI-compatible endpoint via standard environment variables.

## Installation

```bash
npm install -g @qwen-code/qwen-code@latest
```

## Local Endpoint Configuration

Point Qwen Code at a local inference server (llama.cpp, vLLM, Ollama):

```bash
export OPENAI_API_KEY="dummy"          # Any non-empty value
export OPENAI_BASE_URL="http://llama.local:11435/v1"
export OPENAI_MODEL="Qwen3.8-27B"
```

## Headless Mode

```bash
# Simple prompt (non-interactive)
qwen -p "your prompt here" --output-format text

# NOTE: --approval-mode flag was removed in v0.22.0
# Do NOT use --approval-mode plan — it causes the process to hang waiting for approval
```

## Known Issues

- **`--approval-mode plan` removed in v0.22.0**: Older documentation references this flag. It was removed and causes the process to hang. Use plain `-p` with `--output-format text` instead.
- **Hangs without `strace`**: Qwen Code may hang on TTY detection in certain subprocess environments. Running under `strace` or with explicit `--output-format text` resolves this.
