"""
Standardized plan-generation prompt template.

Injected into all harness adapters so every harness produces
output in a consistent, parseable structure.
"""

PLAN_PROMPT_TEMPLATE = """\
Generate an implementation plan for the following request.
Output ONLY a JSON object with this exact structure (no markdown, no extra text):
{{
  "overview": "<one-paragraph summary of what will be built>",
  "steps": ["<step 1>", "<step 2>", ...],
  "assumptions": ["<assumption 1>", ...],
  "output_files": ["<file that will be created or modified>", ...]
}}

Constraints:
- Do NOT execute any code, write any files, or run any commands.
- Produce a planning document only — analysis and specification.
- Include file paths, module boundaries, and data flow in the steps.

USER REQUEST:
{user_prompt}
"""


def build_plan_prompt(user_prompt: str) -> str:
    """Build the standardized plan prompt for a given user request."""
    return PLAN_PROMPT_TEMPLATE.format(user_prompt=user_prompt)
