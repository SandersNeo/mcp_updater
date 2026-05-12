---
name: always-use-goal
description: Use when the user requires all planning, status updates, or task framing to consistently use the `/goal` key. Apply this skill when the user explicitly asks to "always use /goal", wants goal-first communication, or wants every substantial work step to be introduced with a `/goal` line.
---

# Always Use /goal

Use `/goal` as the primary framing key in user-facing work whenever this skill is active.

## Core Rule

Start each substantial user-facing planning or progress message with a `/goal` line.

Examples:

```text
/goal Create the implementation plan file and start Phase 1.
```

```text
/goal Validate the updated PRD and dev spec and determine whether questions remain.
```

## Apply `/goal` Here

Use `/goal` in:

- task kickoffs
- implementation plans
- progress updates
- phase transitions
- clarification messages when the clarification is tied to the current goal

## Do Not Force `/goal` Here

Do not inject `/goal` into:

- shell commands
- code blocks unless the file content itself requires it
- JSON, YAML, or other structured formats where it would break syntax
- filenames, API parameters, or CLI flags unless the user explicitly wants that literal text there

## Working Pattern

When starting work:

```text
/goal State the concrete task being executed now.
```

When moving to the next step:

```text
/goal State the next concrete milestone.
```

When asking a question:

```text
/goal State the blocked objective, then ask the minimum necessary question.
```

## Priority

Treat this as a communication rule, not a code-generation rule.

Prefer preserving valid syntax and correct tool usage over forcing `/goal` into places where it does not belong.
