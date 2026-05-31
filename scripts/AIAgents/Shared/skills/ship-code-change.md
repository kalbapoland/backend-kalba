# Ship Code Change

Use this skill when the user wants to ship Kalba work end-to-end.

## Modes

- `frontend` — ship the frontend repo only.
- `backend` — ship the backend repo only.
- `oba` — ship both repos as two separate workflows. Do not mix files, branches, commits, or PRs across repos.

If the mode is unclear, infer it from the changed files and the current workspace. If it is still ambiguous, ask the user.

## Common Rules

- Start from `main` unless the user explicitly names a different base branch.
- Derive the developer prefix from the current workspace convention; do not hardcode it.
- Stage only task-related files.
- Run code review before the first commit.
- Do not commit without explicit approval when the review workflow is in play.
- Keep PRs focused on one repo and one task.

## Frontend Workflow

Use the frontend-specific review prompt and validation steps.

- Review with `.github/prompts/code-reviewer.prompt.md` using the staged diff.
- Validate with `npm test -- --runInBand` and `npx tsc --noEmit`.
- If the change affects web/shared UI, run `npm run web`.
- If the change affects native-specific behavior, run at least one of `npm run ios` or `npm run android`.

## Backend Workflow

Use the backend-specific review prompt and validation steps.

- Review with `.github/prompts/code-reviewer.prompt.md` using the staged diff.
- Validate with `uv run pytest -q --tb=short`.
- Use the local PostgreSQL environment when tests need it.

## oba Workflow

- Treat frontend and backend as two independent shipping jobs.
- Ship the repo with the relevant changes first, then ship the other repo.
- Each repo gets its own branch, review, commit, validation, push, and PR.
- If both repos change in one task, do not try to force them into one branch or one PR.