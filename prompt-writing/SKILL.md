---
name: prompt-writing
description: "Write production-grade prompts using Anthropic's canonical prompt engineering patterns from Claude Code docs and platform best practices."
version: 1.0.1
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [prompt-engineering, writing, claude, anthropic]
---

# Prompt Writing

Write effective prompts that produce high-quality, consistent output from Claude and other LLMs. This skill codifies patterns from Anthropic's Prompt Library, Common Workflows, Best Practices, and Prompting Best Practices.

## Core prompt structure

Every effective prompt contains these elements, in this order:

1. **Role** — One sentence that sets persona and expertise level. Example: "You are a senior Python developer specializing in async I/O."
2. **Context** — Background information, constraints, and references. What the model should know before acting.
3. **Task** — Clear, specific instruction describing the outcome, not the steps.
4. **Verification** — How the model should check its own work (tests, validation, comparison).
5. **Output format** — Structure, length, audience, or format the response should follow.

## Key patterns

### Describe the outcome, not the steps

Say what you want and let the model find the files. The prompt below works without naming a single file path:

```
add rate limiting to the public API and make sure existing tests still pass
```

### Give it a way to check its own work

Ask for run, test, compare, or verify in the same prompt so the model iterates instead of stopping after one attempt:

```
write the migration, run it against the dev database, and confirm the schema matches
```

### Point at a reference

Name an existing file, test, or pattern to match so the output is consistent with what already exists:

```
add a settings page that follows the same layout as the profile page
```

### State the measurable target

When the goal is performance or coverage, give the metric and threshold so completion is unambiguous:

```
get the bundle size under 200KB and show me what you removed
```

### Give it the artifact

Paste errors, logs, screenshots, and plan output directly in the prompt. The model reads the source instead of a description of it:

```
why is the build failing? @build.log
```

### Say how you want the answer

Name the format, length, or audience so the explanation fits how you'll use it:

```
explain how the payment retry logic works as an HTML page with a diagram
```

## Advanced techniques

### XML structure for complex prompts

Wrap multi-part instructions in XML tags. The model parses structured prompts more reliably than plain text:

```xml
<instructions>
  Write a test for the notification service.
</instructions>
<context>
  The service sends push notifications and handles retry logic.
</context>
<reference>
  See tests/test_email_service.py for the pattern to follow.
</reference>
```

### Role setting in system prompts

Even a single sentence focuses behavior and tone:

```
You are a senior security engineer reviewing code for vulnerabilities.
```

### Few-shot examples

When you need a specific format, provide 2-3 examples of the desired input/output pair. This is one of the most reliable ways to steer format, tone, and structure.

### Long context

When working with large inputs, put long documents at the top of the prompt above your query and instructions. Ground responses in quotes from the source material.

### Default to action

For agentic tasks, explicitly tell the model to implement rather than just suggest:

```xml
<default_to_action>
By default, implement changes rather than only suggesting them. If the user's intent is unclear, infer the most useful likely action and proceed.
</default_to_action>
```

## Prompt anti-patterns to avoid

- **Kitchen sink** — Don't cram unrelated tasks into one prompt. Use separate prompts or subagents.
- **Vague instructions** — "Fix the login bug" is worse than "Users report login fails after session timeout. Check token refresh in src/auth/, write a failing test, then fix it."
- **Over-specification** — Don't micromanage steps when the model can figure out the path.
- **Missing verification** — Always include a way to validate the result.

## Workflow for writing prompts

When writing a prompt for a task:

1. Identify the **role** the model should take
2. Gather relevant **context** (files, error messages, references)
3. Define the **outcome** clearly and specifically
4. Add **verification** criteria (tests, checks, comparison)
5. Specify the **output format** (structure, length, style)
6. Use XML tags if the prompt has multiple sections
7. Include examples if the output format needs to be precise

## Sources

- Claude Code Prompt Library: https://code.claude.com/docs/en/prompt-library
- Common Workflows: https://code.claude.com/docs/en/common-workflows
- Best Practices: https://code.claude.com/docs/en/best-practices
- Prompting Best Practices: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- How Anthropic teams use Claude Code: https://claude.com/blog/how-anthropic-teams-use-claude-code
