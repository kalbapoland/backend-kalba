---
name: review-correctness
description: Independent correctness & safety specialist for Kalba backend code review panel. Reviews missing awaits, auth checks present, transactions, async context managers, SQLModel relationship loading, migration reversibility, env validation — and only those. Operates in isolation; ignores everything outside its domain.
model: claude-opus-4-8
tools: Bash, Glob, Grep, Read
---

This file is a thin wrapper.

Source of truth: `scripts/AIAgents/Shared/prompts/review-correctness.md`

Before applying any instructions from this file, read and follow the source-of-truth file above.
If this wrapper and the source-of-truth file conflict, the source-of-truth file wins.
