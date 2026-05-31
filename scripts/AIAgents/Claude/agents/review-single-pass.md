---
name: review-single-pass
description: Single-pass full-spectrum reviewer for Kalba backend. Covers all 7 domains in one context window for small diffs (< 100 changed lines). Used by the code-reviewer manager as a cost-efficient alternative to the full specialist panel.
model: claude-opus-4-8
tools: Bash, Glob, Grep, Read
---

This file is a thin wrapper.

Source of truth: `scripts/AIAgents/Shared/prompts/review-single-pass.md`

Before applying any instructions from this file, read and follow the source-of-truth file above.
If this wrapper and the source-of-truth file conflict, the source-of-truth file wins.
