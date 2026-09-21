# LLM JSON Structural Repair Patterns

LLMs frequently produce structurally malformed JSON even when the semantic content is correct. These patterns are common enough that a normalizer should repair them before `json.loads()`.

## Pattern 1: Premature object-close on array termination

**Most common.** The LLM closes an array with `]` but inserts a stray `}` before the comma:

```
MALFORMED:  ..."]},  "assumptions": [...]
FIXED:      ..."],  "assumptions": [...]
```

**Regex fix:**
```python
text = re.sub(r'\]\}\s*,', r'],', text)
```

**Why it happens:** The LLM treats the array termination and the enclosing object termination as a single token boundary, merging `]` (close array) + `,` (comma) into `]},` (close object + comma).

**Seen in:** Hermes output via `chat -q`, Qwen Code output, any LLM asked to produce structured JSON with multiple top-level keys.

## When to Apply

1. Strip markdown code fences first (`_strip_markdown_code_fences`)
2. Apply repair (`_repair_llm_json`)
3. Attempt `json.loads()`
4. If it still fails, fall back to heading-based extraction

## Safety

The `]\}\s*,` → `],` repair is safe on valid JSON: the pattern `]},` followed by more content never appears in well-formed JSON (a `]` already terminates the value, so `}` would be a syntax error at that position anyway). It only matches the malformed case.
