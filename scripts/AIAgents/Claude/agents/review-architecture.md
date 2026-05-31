---
name: review-architecture
description: Independent architecture specialist for Kalba backend code review panel. Reviews layering (services vs handlers), DTO separation, Depends usage, and module coupling — and only those. Operates in isolation; ignores everything outside its domain.
model: claude-opus-4-8
tools: Bash, Glob, Grep, Read
---

This file is a thin wrapper.

Source of truth: `scripts/AIAgents/Shared/prompts/review-architecture.md`

Before applying any instructions from this file, read and follow the source-of-truth file above.
If this wrapper and the source-of-truth file conflict, the source-of-truth file wins.
