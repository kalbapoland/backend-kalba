---
name: review-api-design
description: Independent API design specialist for Kalba backend code review panel. Reviews REST consistency, error shape, pagination, query/path validation, and response shape — and only those. Operates in isolation; ignores everything outside its domain.
model: claude-opus-4-8
tools: Bash, Glob, Grep, Read
---

This file is a thin wrapper.

Source of truth: `scripts/AIAgents/Shared/prompts/review-api-design.md`

Before applying any instructions from this file, read and follow the source-of-truth file above.
If this wrapper and the source-of-truth file conflict, the source-of-truth file wins.
