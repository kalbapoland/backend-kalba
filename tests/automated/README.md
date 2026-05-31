# Automated Test Support

This directory contains backend-side helpers used by mobile automated tests.

Today it contains:

1. deterministic reset/seed script for local Android/iOS E2E
2. trainer-account bootstrap helper for smoke owner-flow tests

Run locally from the backend root:

```bash
uv run python tests/automated/seed_mobile_e2e_fixtures.py
```

Ensure trainer account exists for UI owner-flow tests:

```bash
uv run python tests/automated/ensure_smoke_trainer.py
```

Safety notes:

1. The helper runs only for `APP_ENV=local` by default.
2. Use `--force` to override this guard explicitly.
3. It always refuses `APP_ENV=stage` and `APP_ENV=prod`.
4. It refuses non-local database hosts unless `--force` is provided.
5. When running outside local env or against a non-local DB host, `KALBA_E2E_PASSWORD` is required.
6. Existing user password is unchanged unless `--reset-password` is provided.
7. Existing non-trainer account is not promoted unless `--allow-promote-existing` is provided.

Seed script safety notes:

1. Cleanup deletes only records linked to deterministic E2E user emails.
2. Seed script also refuses `APP_ENV=stage` and `APP_ENV=prod`.
3. Seed script refuses non-local DB hosts unless `--force` is provided.
4. Running outside local env or against a non-local DB host requires `KALBA_E2E_PASSWORD`.
