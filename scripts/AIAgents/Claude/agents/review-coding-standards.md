---
name: review-coding-standards
description: Independent coding standards specialist for Kalba backend code review panel. Reviews typing, async/await style, Pydantic, exception specificity, and HTTP status semantics — and only those. Operates in isolation; ignores everything outside its domain.
model: claude-opus-4-8
tools: Bash, Glob, Grep, Read
---

This file is a thin wrapper.

Source of truth: `scripts/AIAgents/Shared/prompts/review-coding-standards.md`

Before applying any instructions from this file, read and follow the source-of-truth file above.
If this wrapper and the source-of-truth file conflict, the source-of-truth file wins.
