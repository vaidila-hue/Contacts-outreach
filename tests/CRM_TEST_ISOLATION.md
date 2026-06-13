# CRM test isolation

Production CRM data lives in:

- `data/outreach.csv`
- `data/backups/outreach/`

Tests must **never** read or write these paths.

## Protection layers

### 1. Autouse fixture (`tests/conftest.py`)

`isolate_production_crm_paths` runs for **every** pytest test and monkeypatches:

- `paths.OUTREACH_CSV` → `{tmp_path}/crm_isolated/outreach.csv`
- `paths.OUTREACH_BACKUP_DIR` → `{tmp_path}/crm_isolated/backups/outreach`

All code that resolves paths through `src.paths` at runtime (including
`outreach_store`, `outreach_persistence`, and `send_queue`) uses the isolated
locations.

### 2. Write guard (`src/crm_path_guard.py`)

When `PYTEST_CURRENT_TEST` is set, `assert_crm_write_path_allowed()` raises
`ProductionCrmPathError` if a write targets:

- `paths.PRODUCTION_OUTREACH_CSV`
- any path under `paths.PRODUCTION_OUTREACH_BACKUP_DIR`

Guards are invoked from `outreach_persistence.py` before backup creation,
prune deletes, and atomic outreach writes.

### 3. Immutable production constants (`src/paths.py`)

`PRODUCTION_OUTREACH_CSV` and `PRODUCTION_OUTREACH_BACKUP_DIR` are fixed
references to repo `data/` paths. Tests patch `OUTREACH_CSV` / `OUTREACH_BACKUP_DIR`
but must not patch the `PRODUCTION_*` names.

## Writing new tests

- Prefer relying on the autouse fixture alone for outreach paths.
- If a test defines its own fixture, still patch **both** `OUTREACH_CSV` and
  `OUTREACH_BACKUP_DIR` (or inherit from autouse via `paths` module).
- Never import `OUTREACH_CSV` or `OUTREACH_BACKUP_DIR` at module level in tests; use
  `paths.OUTREACH_CSV` at runtime so autouse monkeypatch applies.
- Never pass `outreach_path=paths.PRODUCTION_OUTREACH_CSV` to persistence helpers.

## Regression tests

`tests/test_crm_test_isolation.py` verifies production files and backup
directories are untouched during representative outreach writes.
