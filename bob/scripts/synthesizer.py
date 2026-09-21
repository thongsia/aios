#!/usr/bin/env python3
"""
Two-phase synthesis engine (redesigned).

Phase 1 (evaluation) — parallel per-plan evaluations via subprocess.
  Each evaluation sees only ONE plan's compact summary + rubric.
  Results are reduced in the main process to select the best plan.

Phase 2 (augmentation) — single subprocess with retry logic.
  Takes the basis plan + strength bullets from other plans.
  Retries on JSON extraction failure (up to 2 retries).

On synthesis failure, falls back to the selected basis plan.
With a single plan, both phases are skipped.
"""

import json
import re
import subprocess
import os
import warnings
from collections import namedtuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SynthesisResult = namedtuple('SynthesisResult', ['plan_text', 'metadata'])

SAFETY_MARGIN = 15        # seconds reserved for parsing, fallback, dispatch
MAX_AUG_RETRIES = 2       # retry attempts for augmentation (3 total)
EVAL_TIMEOUT_FRACTION = 0.5  # eval gets 50% of usable timeout (was 0.4 — too aggressive for slow models)
AUG_TIMEOUT_FRACTION = 0.5   # augmentation gets the remaining 50%
COMPACT_OVERVIEW_LIMIT = 200  # truncate overview in compact summaries


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes, carriage returns, and terminal control chars."""
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)  # ESC[...m sequences
    text = re.sub(r'\x1b\].*?\x07', '', text)           # OSC sequences
    text = re.sub(r'\r', '', text)                       # carriage returns
    return text


def _repair_json_control_chars(text: str) -> str:
    """Replace literal control characters inside JSON quoted strings with escapes.
    
    LLM output (especially from `hermes chat -q` terminal rendering) often
    contains raw newlines and tabs inside quoted strings, which json.loads()
    rejects. This walks the text character-by-character and escapes controls
    only inside quoted strings.
    """
    result: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            result.append('"')
            i += 1
            while i < len(text):
                ch2 = text[i]
                if ch2 == '\\':
                    result.append(ch2)
                    i += 1
                    if i < len(text):
                        result.append(text[i])
                        i += 1
                elif ch2 == '"':
                    result.append('"')
                    i += 1
                    break
                elif ord(ch2) < 0x20:
                    escapes = {'\n': '\\n', '\t': '\\t', '\r': '\\r'}
                    result.append(escapes.get(ch2, f'\\u{ord(ch2):04x}'))
                    i += 1
                else:
                    result.append(ch2)
                    i += 1
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def _extract_json(text: str) -> str | None:
    """Extract a JSON object from LLM output.
    
    Handles plain JSON, `````json ... ``` ``` fences, preamble text,
    nested braces (tries ALL opening braces, not just the first),
    literal control chars inside quoted strings (hermes terminal output),
    and trailing commas. Returns the JSON string or None if nothing
    parseable is found.
    """
    if not text:
        return None
    
    text = _strip_ansi(text).strip()
    
    # Pre-repair: escape literal control chars in quoted strings
    text = _repair_json_control_chars(text)
    # Remove trailing commas before ] or }
    text = re.sub(r',(\s*[\]\}])', r'\1', text)
    
    # Strategy 1: markdown code fences
    m = re.search(r'```(?:json)?\s*\n?(.+?)\n?```', text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Strategy 2: balanced braces — try EVERY opening brace
    brace_positions = [i for i, c in enumerate(text) if c == '{']
    for first_open in brace_positions:
        depth = 0
        last_close = -1
        for i in range(first_open, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    last_close = i
                    break
        if last_close > first_open:
            candidate = text[first_open:last_close + 1]
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                continue  # try next brace
    
    # Strategy 3: entire text
    try:
        json.loads(text)
        return text
    except (json.JSONDecodeError, ValueError):
        pass
    
    return None


# ---------------------------------------------------------------------------
# Timeout splitting
# ---------------------------------------------------------------------------

def _split_timeout(total: int) -> tuple[int, int]:
    """Return (eval_timeout, aug_timeout) that sum to at most `total`."""
    usable = max(total - SAFETY_MARGIN, 0)
    if usable <= 0:
        return (total // 2, total - total // 2)
    eval_t = max(1, int(usable * EVAL_TIMEOUT_FRACTION))
    aug_t = usable - eval_t
    if eval_t + aug_t > total:
        aug_t = total - eval_t
    return eval_t, aug_t


# ---------------------------------------------------------------------------
# Plan rendering (compact for evaluation, full for fallback)
# ---------------------------------------------------------------------------

def _get_sections(plan: dict) -> dict:
    """Extract overview/steps/assumptions/output_files from any schema."""
    if 'plan_sections' in plan:
        ps = plan['plan_sections']
        return {
            'overview': ps.get('overview', ''),
            'steps': ps.get('steps', []),
            'assumptions': ps.get('assumptions', []),
            'output_files': ps.get('output_files', []),
        }
    return {
        'overview': plan.get('overview', ''),
        'steps': plan.get('steps', []),
        'assumptions': plan.get('assumptions', []),
        'output_files': plan.get('output_files', []),
    }


def _build_compact_plan(plan: dict, score: dict) -> str:
    """Build a compact text summary of a plan for evaluation prompts.

    Truncates the overview to COMPACT_OVERVIEW_LIMIT chars to prevent
    noisy partial plans from polluting the prompt context.
    """
    sec = _get_sections(plan)
    harness = plan.get('harness', 'unknown')
    ws = score.get('weighted_score', 0)

    lines = [
        f"Plan: {harness} (auto-score: {ws:.2f})",
        "",
        f"OVERVIEW:",
        f"{sec['overview'][:COMPACT_OVERVIEW_LIMIT]}",
        "",
        f"STEPS ({len(sec['steps'])} total):",
    ]
    for i, step in enumerate(sec['steps'], 1):
        lines.append(f"{i}. {step}")
    if sec['assumptions']:
        lines.append("")
        lines.append(f"ASSUMPTIONS ({len(sec['assumptions'])}):")
        for a in sec['assumptions']:
            lines.append(f"- {a}")
    if sec['output_files']:
        lines.append("")
        lines.append("OUTPUT FILES:")
        lines.append(", ".join(sec['output_files']))
    lines.append("")

    return "\n".join(lines)


def _render_plan(plan: dict) -> str:
    """Render a plan dict as markdown for final output / fallback."""
    sec = _get_sections(plan)

    lines = []
    if sec['overview']:
        lines.append(f"## Overview\n{sec['overview']}\n")
    if sec['steps']:
        lines.append("## Steps\n")
        for i, step in enumerate(sec['steps'], 1):
            if isinstance(step, dict):
                title = step.get('title', '')
                details = step.get('details', '')
                if isinstance(details, list):
                    details = '\n'.join(f'   - {d}' for d in details)
                if title and details:
                    lines.append(f"{i}. **{title}**\n{details}")
                elif title:
                    lines.append(f"{i}. **{title}**")
                else:
                    lines.append(f"{i}. {step}")
            else:
                lines.append(f"{i}. {step}")
        lines.append("")
    if sec['assumptions']:
        lines.append("## Assumptions\n")
        for a in sec['assumptions']:
            lines.append(f"- {a}")
        lines.append("")
    if sec['output_files']:
        lines.append("## Output Files\n")
        for f in sec['output_files']:
            lines.append(f"- {f}")
        lines.append("")

    if not lines:
        return "[bob] WARNING: Plan has no renderable content.\n"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 1: Per-plan evaluation
# ---------------------------------------------------------------------------

EVAL_PLAN_PROMPT = """\
You are an objective plan evaluator. Review the implementation plan below
and identify specific strengths and weaknesses.

User request:
{user_prompt}

Plan to evaluate:
{compact_plan}

Return ONLY a JSON object:
{{
  "strengths": ["<specific strength 1>", ...],
  "weaknesses": ["<specific weakness 1>", ...]
}}
"""


def _evaluate_single_plan(harness: str, compact: str,
                          user_prompt: str, score: dict,
                          timeout: int) -> dict:
    """Evaluate a single plan via hermes chat subprocess.

    Returns:
        {"harness": str, "strengths": [...], "weaknesses": [...], "error": str|None}
    """
    prompt = EVAL_PLAN_PROMPT.format(
        user_prompt=user_prompt[:800],  # truncate for compact eval prompt
        compact_plan=compact,
    )
    env = _synthesis_env()
    result = _eval_fallback_single(harness,
                                    "Evaluation LLM returned empty output")

    try:
        proc = subprocess.run(
            ["hermes", "chat", "-q", prompt,
             "--ignore-rules", "--max-turns", "1"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if proc.returncode != 0:
            return _eval_fallback_single(
                harness,
                f"hermes chat exit code {proc.returncode}: "
                f"{proc.stderr.strip()}")

        text = _extract_json(proc.stdout)
        if not text:
            return _eval_fallback_single(
                harness,
                f"JSON extraction failed (stdout: {len(proc.stdout)} bytes)")

        data = json.loads(text)
        if not isinstance(data, dict):
            return _eval_fallback_single(harness, "Non-object JSON returned")
        if 'strengths' not in data or not isinstance(data['strengths'], list):
            data['strengths'] = []
        if 'weaknesses' not in data or not isinstance(data['weaknesses'], list):
            data['weaknesses'] = []

        return {
            'harness': harness,
            'strengths': data['strengths'],
            'weaknesses': data['weaknesses'],
            'error': None,
        }

    except subprocess.TimeoutExpired:
        return _eval_fallback_single(harness, "Evaluation LLM timed out")
    except subprocess.SubprocessError as e:
        return _eval_fallback_single(harness, str(e))
    except json.JSONDecodeError as e:
        return _eval_fallback_single(harness,
                                      f"Invalid JSON: {e}")
    except Exception as e:
        return _eval_fallback_single(harness, str(e))


def _eval_fallback_single(harness: str, reason: str) -> dict:
    return {
        'harness': harness,
        'strengths': [],
        'weaknesses': [],
        'error': reason,
    }


def _evaluate_all_plans(plans: list[dict], scores: list[dict],
                        user_prompt: str, timeout: int,
                        fallback_harness: str) -> dict:
    """Phase 1: evaluate all plans in parallel, then reduce.

    Returns the aggregated evaluation dict with best_plan_harness selection.
    """
    evaluations = []
    workers = min(len(plans), 4)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _evaluate_single_plan,
                plan['harness'],
                _build_compact_plan(plan, score),
                user_prompt, score, timeout,
            ): plan['harness']
            for plan, score in zip(plans, scores)
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                ev = future.result()
                evaluations.append(ev)
                status = "OK" if ev['error'] is None else f"FAIL ({ev['error'][:60]})"
                print(f"[bob]   {name} evaluation: {status}")
            except Exception as e:
                evaluations.append(_eval_fallback_single(name, str(e)))
                print(f"[bob]   {name} evaluation: ERROR ({e})")

    # Select best plan: highest auto-score
    ranked = sorted(
        zip(plans, scores),
        key=lambda x: x[1]["weighted_score"],
        reverse=True,
    )
    best_name = ranked[0][0]["harness"]
    best_score = ranked[0][1]["weighted_score"]

    rationale = (
        f"Highest auto-scored plan ({best_name}, "
        f"{best_score:.2f}/5)."
    )

    return {
        'evaluations': evaluations,
        'best_plan_harness': best_name,
        'rationale': rationale,
    }


# ---------------------------------------------------------------------------
# Phase 2: Augmentation (with retry)
# ---------------------------------------------------------------------------

AUGMENTATION_PROMPT = """\
You are a plan synthesizer. Augment the basis plan by incorporating
strengths from the other evaluated plans.

User request:
{user_prompt}

Basis plan ({basis_harness}, score: {basis_score:.2f}):
{basis_plan_compact}

Strengths to incorporate from other plans:
{strength_bullets}

Instructions:
1. Start with the basis plan as-is.
2. For each strength listed above, incorporate it into the plan where
   it improves the steps or adds missing detail.
3. Produce a single coherent plan in this exact JSON format:
{{
  "overview": "<final overview>",
  "steps": ["<step 1>", ...],
  "assumptions": ["<assumption>", ...],
  "output_files": ["<file>", ...],
  "augmentation_log": ["<what was taken from which harness>", ...]
}}
Output ONLY the JSON object, no extra text.
"""


def _build_strength_bullets(evaluations: list[dict]) -> str:
    """Build a compact list of strengths to incorporate from non-basis plans."""
    bullets = []
    for ev in evaluations:
        harness = ev.get('harness', 'unknown')
        for s in ev.get('strengths', []):
            bullets.append(f"- [{harness}] {s}")
    if not bullets:
        return "(No additional strengths identified by evaluation)"
    return "\n".join(bullets)


def _validate_augmentation(data: dict) -> tuple[dict | None, list[str] | None]:
    """Validate augmentation JSON; return (plan_dict, aug_log) or (None, None)."""
    if not isinstance(data, dict):
        return None, None
    if 'overview' not in data or 'steps' not in data:
        return None, None
    aug_log = data.get('augmentation_log')
    if aug_log is not None and not isinstance(aug_log, list):
        aug_log = None
    return data, aug_log


def _augment_plan(basis_plan: dict, basis_score: dict,
                  evaluations: list[dict],
                  user_prompt: str, timeout: int) -> tuple[dict | None, list[str] | None]:
    """Phase 2: augment the basis plan with strengths from other plans.

    Retries up to MAX_AUG_RETRIES times on JSON extraction failure.
    """
    strength_bullets = _build_strength_bullets(evaluations)

    prompt = AUGMENTATION_PROMPT.format(
        user_prompt=user_prompt[:800],
        basis_harness=basis_plan['harness'],
        basis_score=basis_score['weighted_score'],
        basis_plan_compact=_build_compact_plan(basis_plan, basis_score),
        strength_bullets=strength_bullets,
    )

    env = _synthesis_env()

    for attempt in range(1, MAX_AUG_RETRIES + 2):
        try:
            proc = subprocess.run(
                ["hermes", "chat", "-q", prompt,
                 "--ignore-rules", "--max-turns", "1"],
                capture_output=True, text=True, timeout=timeout, env=env,
            )
            if proc.returncode != 0:
                if attempt <= MAX_AUG_RETRIES:
                    prompt += (
                        f"\n\nPrevious attempt failed with exit code "
                        f"{proc.returncode}. Try again with ONLY a JSON object."
                    )
                    continue
                return None, None

            text = _extract_json(proc.stdout)
            if not text:
                if attempt <= MAX_AUG_RETRIES:
                    prompt += (
                        f"\n\nPrevious attempt produced no parseable JSON "
                        f"(stdout: {len(proc.stdout)} bytes). "
                        f"Output ONLY a JSON object."
                    )
                    continue
                return None, None

            data = json.loads(text)
            plan_data, aug_log = _validate_augmentation(data)
            if plan_data is None:
                if attempt <= MAX_AUG_RETRIES:
                    prompt += (
                        f"\n\nPrevious attempt produced JSON missing "
                        f"'overview' or 'steps' fields. Include both."
                    )
                    continue
                return None, None

            retries = max(0, attempt - 1)
            if retries:
                print(f"[bob]   Augmentation OK ({attempt} attempt{'s' if attempt > 2 else ''})")
            else:
                print(f"[bob]   Augmentation OK")
            return plan_data, aug_log

        except subprocess.TimeoutExpired:
            return None, None
        except subprocess.SubprocessError:
            return None, None
        except json.JSONDecodeError:
            if attempt <= MAX_AUG_RETRIES:
                prompt += "\n\nPrevious attempt had invalid JSON. Fix and try again."
                continue
            return None, None
        except Exception:
            return None, None

    return None, None


# ---------------------------------------------------------------------------
# Main synthesis entry point
# ---------------------------------------------------------------------------

def synthesize(plans: list[dict], scores: list[dict],
               user_prompt: str, timeout: int = 300) -> SynthesisResult:
    """Two-phase synthesis: evaluate plans, select the best, augment it.

    Args:
        plans: List of normalized plan dicts.
        scores: List of score dicts corresponding to each plan.
        user_prompt: The original user request.
        timeout: Total timeout budget for both LLM phases (default 300s).

    Returns:
        SynthesisResult(plan_text, metadata) on every path.
    """
    ranked = sorted(
        zip(plans, scores),
        key=lambda x: x[1]["weighted_score"],
        reverse=True,
    )
    eval_timeout, aug_timeout = _split_timeout(timeout)

    # --- Single-plan short-circuit ---
    if len(ranked) == 1:
        plan, score = ranked[0]
        text = _render_plan(plan)
        note = (f"[bob] Only 1 plan available ({plan['harness']}); "
                f"returned as-is without synthesis.\n")
        return SynthesisResult(note + text,
                               metadata={"evaluation": None,
                                         "augmentation_log": None})

    # --- Phase 1: Parallel per-plan evaluations ---
    print(f"[bob] Phase 1: Evaluating {len(plans)} plans in parallel...")
    evaluation = _evaluate_all_plans(
        [p for p, _ in ranked],
        [s for _, s in ranked],
        user_prompt, eval_timeout,
        fallback_harness=ranked[0][0]["harness"],
    )

    # Match selected harness to ranked plans
    best_name = evaluation["best_plan_harness"]
    best_idx = None
    for i, (p, _) in enumerate(ranked):
        if p["harness"] == best_name:
            best_idx = i
            break
    if best_idx is None:
        warnings.warn(
            f"[bob] Evaluation selected '{best_name}' which doesn't match "
            f"any harness. Falling back to highest auto-scored: "
            f"{ranked[0][0]['harness']}."
        )
        best_idx = 0
    best_plan, best_score = ranked[best_idx]

    print(f"[bob]   Best plan: {best_name} "
          f"(auto-score: {best_score['weighted_score']:.2f})")

    # --- Phase 2: Augmentation ---
    print("[bob] Phase 2: Augmenting basis plan...")
    augmented, aug_log = _augment_plan(
        best_plan, best_score,
        evaluation.get('evaluations', []),
        user_prompt, aug_timeout,
    )

    if augmented is not None:
        text = _render_plan(augmented)
        return SynthesisResult(text, metadata={
            "evaluation": evaluation,
            "augmentation_log": aug_log,
        })
    else:
        # Augmentation failed — return basis plan with evaluation context
        text = _render_plan(best_plan)
        rationale = evaluation.get("rationale", "Augmentation failed.")
        header = (
            f"[bob] WARNING: Augmentation phase failed. "
            f"Returning the selected basis plan from "
            f"{best_plan['harness']} (score: "
            f"{best_score['weighted_score']:.2f}) as fallback.\n"
            f"[bob] Selection rationale: {rationale}\n"
        )
        return SynthesisResult(header + text, metadata={
            "evaluation": evaluation,
            "augmentation_log": None,
        })


def _synthesis_env() -> dict:
    """Build environment for the synthesis Hermes subprocess."""
    env = os.environ.copy()
    env["HERMES_PROFILE"] = "bob-worker"
    env["HERMES_HOME"] = str(Path.home() / ".hermes")
    return env
