---
name: ship-code-change
description: 'Git workflow: create branch, commit, run code-reviewer, run tests, push, and open a PR for Kalba backend work. Use when shipping a finished task or preparing a backend PR.'
argument-hint: 'feature-name or short shipping summary'
user-invocable: true
---

# Ship Code Change

Use this skill when the user wants a backend task shipped end-to-end.

## Branch Rules

- Start new work from `main` unless the user explicitly names a different base branch.
- Branch names must start with `banaszki/`.
- For code-review follow-up fixes, stay on the current work branch. Do not create a new branch.

## Workflow

1. Create the branch when this is new work.

```bash
git checkout main
git pull
git checkout -b banaszki/<feature-name>
```

2. Stage only the files for the current task.

- Check recent commit message style with `git log --oneline -5`.
- Stage only task-related files.
- Do not commit unrelated workspace changes.

3. Run code review before the first commit.

```bash
git diff --cached
```

- In Copilot Chat, invoke `.github/prompts/code-reviewer.prompt.md` with the staged diff.
- Present the full list of Required Changes to the user.
- Apply all required changes, restage them, and rerun review if the staged diff changed.
- Present the final review verdict and wait for explicit user approval before continuing.
- Skip this step only if the user explicitly says to skip review.

4. Commit the approved staged changes.

- Use the project's existing commit message style.
- Commit only the reviewed task files.

5. Run backend validation locally.

```bash
uv run pytest -q --tb=short
```

- Tests require PostgreSQL. Use the local database or `docker compose -f docker-compose.local.yml up -d`.
- If tests fail, fix the issues, restage the fix, rerun Step 3, and commit the follow-up change on the same branch.
- If no automated test covers the change, note that explicitly in the PR body.

6. Push and open the PR.

```powershell
$prBodyPath = Join-Path $PWD ".github/pr-body.md"
$prBody = @"
## Summary
- <what changed and why>

## Test plan
- [ ] uv run pytest -q --tb=short
- [ ] <manual verification if needed>

Generated with GitHub Copilot
"@
$prBody | Set-Content -Path $prBodyPath
git push -u origin <current-branch>
gh pr create --base main --title "<short title under 70 chars>" --body-file $prBodyPath
Remove-Item $prBodyPath
```

- Return the PR URL to the user.
- Keep the PR focused on the current task only.