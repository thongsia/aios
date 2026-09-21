"""
Multi-pass output normalizer.

Converts raw harness output to the canonical JSON schema:
{
  "harness": str,
  "status": "ok" | "partial" | "failed",
  "plan_sections": {
    "overview": str,
    "steps": list[str],
    "assumptions": list[str],
    "output_files": list[str]
  },
  "exit_code": int,
  "duration_s": float
}

Pipeline:
  Pre-pass: Events-stream extraction (handles opencode/hermes event JSON)
  Pass 1: Direct JSON parse (strip markdown fences)
  Pass 2: Heading-based parse (## Overview, ## Steps, ...)
  Pass 3: Raw fallback (entire output as overview, status=partial)
"""

import json
import re


def normalize(harness_name: str, raw_text: str, exit_code: int, duration: float) -> dict:
    """Normalize harness output through the multi-pass pipeline."""

    # Empty or error output -> failed
    if not raw_text or (exit_code < 0):
        return _build_canonical(harness_name, {
            "overview": f"Harness returned no output (exit_code={exit_code})",
            "steps": [],
            "assumptions": [],
            "output_files": [],
        }, "failed", exit_code, duration)

    # Diff-stripping pass (Hermes renders tool-use as unified diffs).
    # Must run BEFORE events-stream extraction so the JSON inside a diff
    # is recoverable by later passes.
    raw_text = _strip_diff_syntax(raw_text)

    # Pre-pass: Extract embedded JSON from events-stream format.
    # Both opencode and hermes chat -q can output lines like:
    #   {"type":"text","text":"{\"overview\":...}"}
    # or individual event JSON lines. We look for a text event containing
    # the plan JSON and extract it.
    extracted = _extract_from_events_stream(raw_text)
    if extracted:
        try:
            data = json.loads(extracted)
            if _validate_sections(data):
                return _build_canonical(harness_name, data, "ok", exit_code, duration)
        except (json.JSONDecodeError, ValueError):
            pass

    # Pass 1: Direct JSON parse (with repair for common LLM errors)
    json_text = _strip_markdown_code_fences(raw_text)
    json_text = _repair_llm_json(json_text)
    try:
        data = json.loads(json_text)
        if _validate_sections(data):
            return _build_canonical(harness_name, data, "ok", exit_code, duration)
    except (json.JSONDecodeError, ValueError):
        pass

    # Pass 2: Heading-based parse
    data = _extract_from_headings(raw_text)
    if _validate_sections(data):
        return _build_canonical(harness_name, data, "ok", exit_code, duration)

    # Pass 3: Raw fallback
    return _build_canonical(harness_name, {
        "overview": raw_text[:5000],
        "steps": [],
        "assumptions": [],
        "output_files": [],
    }, "partial", exit_code, duration)


def _strip_diff_syntax(text: str) -> str:
    """Strip unified diff syntax and reassemble the original text.

    Handles output like:
        a//tmp/plan.json -> b//tmp/plan.json
        @@ -0,0 +1,42 @@
        +{
        +  "overview": ...
    by removing line-prefix markers (+, -, spaces) and diff headers.
    """
    lines = text.split('\n')
    result = []
    in_diff = False
    for line in lines:
        # Detect diff header (e.g., "a//tmp/... → b//tmp/..." or "a/... -> b/...")
        if (line.strip().startswith('a/') and
            (' -> b/' in line or '\u2192 b/' in line)):
            in_diff = True
            continue
        # Diff separator lines
        if line.strip().startswith('@@') and in_diff:
            continue
        # Non-diff hunk header (e.g., "  ┊ review diff")
        if 'review diff' in line or 'tool output' in line:
            in_diff = True
            continue
        if in_diff:
            # Strip diff line prefixes
            if line.startswith('+'):
                result.append(line[1:])
            elif line.startswith(' '):
                result.append(line[1:])
            # Skip '-' lines (removed lines in the diff)
            continue
        else:
            result.append(line)
    return '\n'.join(result).strip()


def _extract_from_events_stream(text: str) -> str | None:
    """
    Extract embedded plan JSON from an events-stream output.

    Handles multiple event formats:
    - {"type":"text","text":"..."} (direct text)
    - {"type":"text","part":{"text":"..."}} (nested text)
    - {"type":"tool_use",...} with file writes: extracts written file content
      (opencode writes plan to a file; we grab that content)
    - {"type":"tool_result",...} with bash output: extracts cat/read output

    Returns the concatenated content, or None if nothing extracted.
    """
    text_parts = []
    file_writes = []  # (file_path, content) for last-resort fallback
    tool_results = []  # bash output (e.g., cat file contents)
    all_events = []  # collect all parsed events for later priority passes

    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # Skip non-object JSON (strings, numbers, etc.)
        if not isinstance(event, dict):
            continue

        all_events.append(event)

        # --- Text events (hermes chat -q, opencode text output) ---
        if event.get("type") == "text":
            if "text" in event and isinstance(event["text"], str):
                text_parts.append(event["text"])
            elif "part" in event and isinstance(event["part"], dict):
                part_text = event["part"].get("text", "")
                if part_text and isinstance(part_text, str):
                    text_parts.append(part_text)

        # --- Tool use events (opencode file writes) ---
        if event.get("type") == "tool_use":
            part = event.get("part", {})
            if isinstance(part, dict) and part.get("type") == "tool" and part.get("tool") == "write":
                state = part.get("state", {})
                if isinstance(state, dict) and state.get("status") == "completed":
                    input_data = state.get("input", {})
                    if isinstance(input_data, dict):
                        content = input_data.get("content", "")
                        filepath = input_data.get("path", "")
                        if content and isinstance(content, str):
                            file_writes.append((filepath, content))

        # --- Tool result events (bash/cat output) ---
        if event.get("type") == "tool_result":
            part = event.get("part", {})
            if isinstance(part, dict) and part.get("type") == "tool" and part.get("tool") == "shell":
                state = part.get("state", {})
                if isinstance(state, dict):
                    output = state.get("output", "")
                    if output and isinstance(output, str):
                        tool_results.append(output)

    # Priority 1: direct text events (most reliable)
    if text_parts:
        raw_text = ''.join(text_parts)
        # Strip markdown code fences from extracted text before returning.
        # Harnesses (e.g., opencode) often wrap their JSON output in
        # ```json ... ``` fences inside the text event payload.
        stripped = _strip_markdown_code_fences(raw_text)
        return stripped

    # Priority 2: tool_use events — opencode may write JSON to a bash
    # heredoc inside a tool_use event's command input (non-deterministic).
    tool_uses = [ev for ev in all_events if ev.get('type') == 'tool_use']
    if tool_uses:
        for tu in tool_uses:
            part = tu.get('part', {})
            state = part.get('state', {})
            inp = state.get('input', {})
            cmd = inp.get('command', '')
            if not cmd:
                continue
            # Extract heredoc content: cat << 'HEREDOC' ... HEREDOC
            for delim in ['JSONEOF', 'EOF', 'HEREDOC', 'JSON']:
                if delim in cmd:
                    chunks = cmd.split(delim)
                    if len(chunks) >= 2:
                        heredoc = chunks[1].strip()
                        if heredoc:
                            return _strip_markdown_code_fences(heredoc)

    # Priority 3: tool result output (e.g., cat plan.json)
    if tool_results:
        return _strip_markdown_code_fences('\n'.join(tool_results))

    # Priority 3: file write content (opencode writes plan to file)
    if file_writes:
        # Return the LAST file write (most likely the final plan)
        _, last_content = file_writes[-1]
        return _strip_markdown_code_fences(last_content)

    return None


def _strip_markdown_code_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences."""
    text = text.strip()
    # Match ```json\n...\n``` or ```\n...\n```
    m = re.search(r'```(?:json)?\s*\n(.+?)\n```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try without newline after fence
    m = re.search(r'```(?:json)?\s*(.+?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _repair_llm_json(text: str) -> str:
    """
    Repair common LLM JSON structural errors.

    LLMs often close the `steps` array prematurely:
      ..."]},  "assumptions": ...
    instead of:
      ..."],  "assumptions": ...

    The "]" already closes the array; the "}" is an erroneous object-close
    placed before the comma. Replace "]}," with "]," to remove the stray "}".
    """
    # Replace ]}, (with optional whitespace) with ],
    text = re.sub(r'\]\}\s*,', r'],', text)
    return text


def _validate_sections(data: dict) -> bool:
    """All four sections must be present and non-empty."""
    for key in ["overview", "steps", "assumptions", "output_files"]:
        if key not in data or not data[key]:
            return False
    return True


def _extract_from_headings(text: str) -> dict:
    """Extract plan sections from markdown headings."""
    result = {
        "overview": "",
        "steps": [],
        "assumptions": [],
        "output_files": [],
    }

    # Split by headings
    sections = re.split(r'^##\s+', text, flags=re.MULTILINE)

    current_key = None
    for section in sections:
        lines = section.strip().split('\n')
        if not lines:
            continue

        heading = lines[0].strip().lower()
        content = '\n'.join(lines[1:]).strip()

        if 'overview' in heading or 'summary' in heading:
            current_key = 'overview'
            result['overview'] = content
        elif 'step' in heading:
            current_key = 'steps'
            result['steps'] = _parse_list(content)
        elif 'assumption' in heading:
            current_key = 'assumptions'
            result['assumptions'] = _parse_list(content)
        elif 'output' in heading or 'file' in heading:
            current_key = 'output_files'
            result['output_files'] = _parse_list(content)

    return result


def _parse_list(text: str) -> list[str]:
    """Parse a markdown list or comma-separated values into a list."""
    items = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        # Remove list markers: - , * , 1. , 2. , etc.
        line = re.sub(r'^[-*]|\d+\.\s*', '', line).strip()
        if line:
            items.append(line)
    if not items and ',' in text:
        # Fallback: comma-separated
        items = [x.strip() for x in text.split(',') if x.strip()]
    return items


def _build_canonical(harness_name: str, data: dict, status: str,
                     exit_code: int, duration: float) -> dict:
    """Assemble the canonical output dict."""
    return {
        "harness": harness_name,
        "status": status,
        "plan_sections": {
            "overview": data.get("overview", ""),
            "steps": data.get("steps", []),
            "assumptions": data.get("assumptions", []),
            "output_files": data.get("output_files", []),
        },
        "exit_code": exit_code,
        "duration_s": round(duration, 2),
    }
