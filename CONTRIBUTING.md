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

Die Checkliste im PR-Template (`.github/pull_request_template.md`) ist verbindlich.
Sie fragt unsere **wiederkehrenden Review-Fehlerklassen** vorab ab — jeder Punkt
steht für einen Fehler, der uns schon mindestens einmal gekostet hat. Hier dieselben
Punkte als Fließtext mit kurzer Begründung, je „warum":

- **tz-aware (timestamptz, kein naive/aware-Mix).** Alle Zeitstempel `timestamptz`
  in der DB und aware `datetime` in Python (`datetime.now(UTC)`, nie `utcnow()`).
  *Warum:* naive Werte aus einer Migration/einem Seed haben schon RBAC zum Absturz
  gebracht (`can't compare offset-naive and offset-aware`), was als Folgefehler
  einen Meeting-WS-403 erzeugte. Ein einziger naiver Wert vergiftet jeden Vergleich.
- **problem+json auf ALLEN Fehlerpfaden.** Jeder 4xx/5xx liefert
  `application/problem+json` — auch neu hinzugekommene Branches. *Warum:* der Contract
  (Schemathesis) und das FE erwarten ein einheitliches Fehlerschema; ein nackter
  String oder das FastAPI-Default-`detail` bricht beides und entgeht der lokalen
  Sichtprüfung leicht.
- **RBAC serverseitig erzwungen, keine Privilege-Escalation.** Die Berechtigung wird
  im Backend geprüft, nicht nur per FE-Gating; Rollen/Owner kommen aus der Session,
  nicht aus dem Request-Body. *Warum:* FE-Gating ist Komfort, keine Sicherheit — wer
  die Route direkt aufruft, umgeht es. Objekt-Owner ≠ Caller ist der häufigste Leak.
- **FE/BE-Contract-Namensgleichheit.** Gleiche Feld-/Header-/Cookie-Namen auf beiden
  Seiten, **camelCase** im JSON. *Warum:* `snake_case`↔`camelCase`-Drift und
  FE-erfundene Felder (die es im Backend nie gab) sind ein Dauerbrenner; sie
  kompilieren beidseitig, scheitern aber zur Laufzeit still.
- **Inputs strikt typisiert (Enums/Literals statt freier Strings).** Query/Body/Path
  über Pydantic/`Annotated` validiert, Statusfelder als Enum/`Literal`. *Warum:* ein
  offenes `str`-Statusfeld akzeptiert Tippfehler und ungültige Übergänge, die erst
  tief im Code knallen — der `lang`-Param war genau so ein Fall (frei statt `de|en`).
- **i18n de/en Parity.** Jeder neue String in beiden Locales, nichts hartkodiert.
  *Warum:* fehlende `en`-Keys fallen lokal (de) nicht auf und erscheinen erst im
  englischen UI als roher Key.
- **a11y.** Labels/`aria-*`, Fokus-Reihenfolge, Tastatur, Kontrast.
- **Dark/Light.** In beiden Themes geprüft. *Warum:* fixe Farben brechen regelmäßig
  im jeweils anderen Theme; der Prod-Build (inlineCritical) verhält sich zudem anders
  als der Dev-Build — gegen den **Prod**-Build prüfen.
- **FE-Selbstcheck via Visual-Harness (Vorher/Nachher).** Screenshots erzeugen und
  *ansehen*, je Theme. *Warum:* „sieht wohl ok aus" ist kein Selbstcheck; die meisten
  Layout-Regressionen sind nur visuell sichtbar.
- **Migration single-head.** `alembic heads` = ein head, `alembic upgrade head` grün
  (s. „Datenbank-Migrationen" unten).

Plus die harten Gates:

- Tests test-first geschrieben, alle grün.
- Coverage-Gate gehalten (modul-spezifisch für kritische Module).
- `ruff` + `basedpyright` (BE) / `eslint` + `tsc` (FE) grün.
- Contract-Tests grün, betroffene E2E grün.
- Kein `skip`/`xfail` ohne verlinkten Grund.

## Datenbank-Migrationen (Alembic)

**Neue Migration = `alembic revision` mit Hash-ID** (Alembic-Default), `down_revision`
= aktueller head. Die alte fortlaufende `000N`-Konvention ist abgeschafft.

```bash
cd backend
alembic revision -m "kurzbeschreibung"   # erzeugt z.B. aa50a10a8072_kurzbeschreibung.py
alembic heads                            # MUSS genau einen head zeigen
alembic upgrade head                     # MUSS grün durchlaufen
```

*Warum Hash statt `000N`:* parallele Wellen vergaben unabhängig dieselbe nächste
Nummer (`0016` kollidierte zweimal), was bei jedem Merge Hand-Renumbering erzwang.
Zufalls-Hashes kollidieren praktisch nie; der head-Vergleich (single-head-Gate)
bleibt der einzige Mergekonflikt-Punkt — und der ist beabsichtigt sichtbar.

Regeln:

- **Kein `--rev-id`, keine `000N`-Präfixe** mehr. Alembic vergibt die Hash-ID.
- **Bestehende Migrationen werden nicht umbenannt** — die `0001…0017`-Kette bleibt,
  wie sie ist; nur *neue* Revisions bekommen Hash-IDs.
- `down_revision` zeigt auf den **aktuellen** head (das macht `alembic revision`
  automatisch, solange genau ein head existiert).
- Tabellen/Modelle entstehen weiterhin via `Base.metadata.create_all` in `0002`
  (Single-Source-Pattern); reine Daten-/Constraint-Migrationen bekommen eine eigene
  Revision.
- Details: `backend/migrations/README.md`.

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
