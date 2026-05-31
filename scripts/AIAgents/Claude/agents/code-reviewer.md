---
name: code-reviewer
description: Code review manager for Kalba backend. Coordinates max two independent composite subagents and merges their reports into a single consolidated review. Does not review code itself.
model: claude-opus-4-8
tools: Bash, Glob, Grep, Read
---

This file is a thin wrapper.

Source of truth: `scripts/AIAgents/Shared/prompts/code-reviewer.md`

Before applying any instructions from this file, read and follow the source-of-truth file above.
If this wrapper and the source-of-truth file conflict, the source-of-truth file wins.
