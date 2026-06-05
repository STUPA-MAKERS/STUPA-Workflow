# Contributing — Antragsplattform

Verbindlicher Workflow: **TDD (Red-Green-Refactor)**, CI-Gate blockiert PRs
(`sds/testing.md`). Dieses Dokument fasst Workflow, Definition of Done und die
Branch-Protection-Konfiguration zusammen.

## TDD: Red → Green → Refactor

1. **Red** — Test zuerst schreiben, der das gewünschte Verhalten beschreibt. Lauf
   lassen, *muss fehlschlagen* (kein Vorab-Code → echter Test).
2. **Green** — minimalen Produktivcode schreiben, bis der Test grün ist. Nicht mehr.
3. **Refactor** — Duplikate/Schmutz entfernen, Tests bleiben grün.

Kein `skip`/`xfail` ohne begründeten, verlinkten Grund (Issue).

## Tests lokal

Backend (`backend/`):

```bash
pip install -e '.[dev]'
ruff check .                       # Lint
basedpyright                       # Typen (0 Fehler erforderlich)
pytest                             # schnelle Unit-Suite (kein Docker)
pytest --cov --cov-report=term-missing   # mit Coverage (Gate 85 %)
pytest -m integration              # Integration (testcontainers, Docker nötig)
```

Coverage-Gate für kritische Module (100 % Branch) lokal prüfen:

```bash
pytest --cov --cov-report=xml
python -m scripts.coverage_critical coverage.xml pyproject.toml
```

Frontend (`frontend/`, ab T-03):

```bash
npm ci
npm run lint
npx tsc --noEmit
npm test -- --coverage          # Gate 80 %
npx playwright test             # E2E gegen Compose-Stack
```

## Coverage-Gates (CI bricht bei Unterschreitung)

- Backend gesamt **≥ 85 %** (Lines + Branches) — `[tool.coverage.report] fail_under`.
- Frontend gesamt **≥ 80 %** — `jest.config` `coverageThreshold`.
- **100 % Branch** für kritische Module (`auth`, `voting`, `flow`, `budget`,
  `webhooks`, `audit`) — eigenes Gate via `scripts/coverage_critical.py`. Greift
  automatisch, sobald das jeweilige Modul existiert.

## CI-Stages (Reihenfolge, schnelle zuerst)

`Lint → Typecheck → BE-Unit → BE-Integration → Contract (Schemathesis) →
FE-Unit → E2E (Playwright vs Compose) → Coverage-Gate → Image-Build + Smoke`
(`.github/workflows/ci.yml`). Rotes PR ⇒ blockiert.

## Definition of Done (je Task/Modul)

- Tests test-first geschrieben, alle grün.
- Coverage-Gate gehalten (modul-spezifisch für kritische Module).
- `ruff` + `basedpyright` (BE) / `eslint` + `tsc` (FE) grün.
- Contract-Tests grün, betroffene E2E grün.
- Kein `skip`/`xfail` ohne verlinkten Grund.

## Branch-Protection (`main`)

In **Settings → Branches → Branch protection rule** für `main` setzen:

- ✅ **Require a pull request before merging** (≥ 1 Review).
- ✅ **Require status checks to pass before merging** → *Require branches up to date*.
  Pflicht-Checks (Job-Namen aus `ci.yml`):
  `be-lint`, `be-typecheck`, `be-unit`, `be-integration`, `be-contract`,
  `coverage-gate`, `image-build-smoke`, `pytex`, `compose`.
  FE-Checks (`fe-unit`, `e2e`) als Pflicht ergänzen, sobald `frontend/` existiert (T-03).
- ✅ **Require conversation resolution before merging**.
- ✅ **Do not allow bypassing the above settings** (auch für Admins).
- 🚫 Force-Push / Branch-Löschung deaktiviert.

## Pre-Commit

```bash
pip install pre-commit && pre-commit install
```

Läuft `ruff` (Lint + Format) und `basedpyright` vor jedem Commit
(`.pre-commit-config.yaml`).
