<!--
Definition of Done — bitte VOR dem Review durchgehen. Die Liste fragt unsere
wiederkehrenden Review-Fehlerklassen vorab ab; jeder Haken steht für einen Fehler,
der uns schon mind. einmal gekostet hat. Punkte, die für diesen PR nicht zutreffen,
mit `[x] n/a — <kurzer Grund>` abhaken (nicht löschen). Begründung je Punkt:
docs/CONTRIBUTING.md / CONTRIBUTING.md → „Definition of Done".
-->

## Was & Warum

<!-- Knapp: was ändert sich, welches Issue/Task (T-/#), warum so. -->

Closes #

## Definition of Done

### Backend / Contract
- [ ] **tz-aware** — alle Zeitstempel `timestamptz` (DB) bzw. aware `datetime` (Python). **Kein** naive/aware-Mix; keine `datetime.utcnow()` (→ `datetime.now(UTC)`).
- [ ] **problem+json auf ALLEN Fehlerpfaden** — jeder 4xx/5xx liefert `application/problem+json` (auch neue Pfade/Branches). Kein nackter String / Default-FastAPI-`detail`.
- [ ] **RBAC serverseitig erzwungen** — Berechtigung wird im Backend geprüft (nicht nur FE-Gating); keine Privilege-Escalation (z. B. Objekt-Owner ≠ Caller, Rollen aus dem Request nicht vertrauen).
- [ ] **Inputs strikt typisiert** — Enums/`Literal` statt freier Strings; Query/Body/Path validiert (Pydantic/`Annotated`), keine offenen `str`-Statusfelder.
- [ ] **Migration single-head** — `alembic heads` = **ein** head, `alembic upgrade head` läuft grün. Neue Revision = **Hash-ID** (`alembic revision`, kein `--rev-id`/`000N`); `down_revision` = aktueller head.
- [ ] **Contract-Tests grün** — Schemathesis (`--checks all`) bleibt grün; OpenAPI spiegelt die Änderung.

### FE/BE-Vertrag (Namensgleichheit)
- [ ] **Feld-/Header-/Cookie-Namen identisch** FE↔BE, **camelCase** im JSON. Kein FE-erfundenes Feld; keine stillen Umbenennungen (`snake_case`↔`camelCase`-Drift).

### Frontend / UX
- [ ] **i18n de/en Parity** — jeder neue String in **beiden** Locales (`de` + `en`), keine hartkodierten Texte.
- [ ] **a11y** — Labels/`aria-*`, Fokus-Reihenfolge, Tastatur-Bedienbarkeit, Kontrast.
- [ ] **Dark/Light** — in **beiden** Themes geprüft (keine fixen Farben, die im anderen Theme brechen).
- [ ] **FE-Selbstcheck via Visual-Harness** — Vorher/Nachher-Screenshots erzeugt und gesichtet (kein „sieht-wohl-ok"); relevante Screens unten verlinkt/angehängt.

### Tests & Gates
- [ ] Tests test-first, alle grün; Coverage-Gate gehalten (kritische Module 100 % Branch).
- [ ] `ruff` + `basedpyright` (BE) / `eslint` + `tsc` (FE) **0** Fehler.
- [ ] Kein `skip`/`xfail` ohne verlinkten Grund.

## Screenshots (Vorher / Nachher)

<!-- Visual-Harness-Ausgabe für betroffene Screens, je Theme. -->
