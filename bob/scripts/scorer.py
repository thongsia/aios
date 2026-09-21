"""
Automated non-LLM scoring metrics for plan evaluation.

Scores on a 1-5 scale with weighted rubric:
  - Completeness (weight: 0.4)
  - Specificity (weight: 0.35)
  - Feasibility (weight: 0.25)
"""

import re
from statistics import mean


def score_plan(plan: dict) -> dict:
    """
    Score a normalized plan on a 1-5 scale.

    Returns:
        dict with completeness, specificity, feasibility, weighted_score
    """
    sections = plan.get("plan_sections", {})

    # Completeness: ratio of populated sections + step count
    section_count = sum(
        1 for s in ["overview", "steps", "assumptions", "output_files"]
        if sections.get(s)
    )
    step_count = len(sections.get("steps", []))
    completeness = min(5.0, section_count * 1.0 + step_count * 0.2)

    # Specificity: avg step length, presence of file paths, concrete details
    steps = sections.get("steps", [])
    if steps:
        avg_step_len = mean([len(s) for s in steps])
    else:
        avg_step_len = 0
    file_path_mentions = _count_file_paths(sections)
    specificity = min(5.0, avg_step_len / 50.0 + file_path_mentions * 0.3)

    # Feasibility: step count (not too few, not too many), has assumptions
    has_assumptions = bool(sections.get("assumptions"))
    feasibility = min(5.0, 2.0 + (3 <= step_count <= 20) * 1.5 + has_assumptions * 0.5)

    weighted = (
        completeness * 0.4
        + specificity * 0.35
        + feasibility * 0.25
    )

    return {
        "completeness": round(completeness, 1),
        "specificity": round(specificity, 1),
        "feasibility": round(feasibility, 1),
        "weighted_score": round(weighted, 2),
    }


def _count_file_paths(sections: dict) -> int:
    """Count mentions of file paths in the plan sections."""
    path_pattern = re.compile(r'(?:^|[/\s])(?:\.\.?/|\w[\w-]*\/)?[\w-]+\.\w{2,4}')
    count = 0
    for key, value in sections.items():
        if isinstance(value, str):
            count += len(path_pattern.findall(value))
        elif isinstance(value, list):
            for item in value:
                count += len(path_pattern.findall(item))
    return count
