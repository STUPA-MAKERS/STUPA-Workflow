# E2E-Tests (T-40) — Playwright vs echtem Compose-Stack

End-to-End-Abdeckung der Kern-User-Journeys (testing.md §3) gegen den **echten**
Stack (FastAPI + Angular + Postgres + Redis + MinIO + pytex hinter Nginx), **nicht**
gegen die Mock-API (seit #101 AUS). Magic-Link-Mails landen im `mailpit`-SMTP-Sink.

## Ausführen

```bash
# Gating-Subset (Standard; entspricht dem CI-Gate)
scripts/e2e.sh

# Full-Tier (zusätzlich opt-in/flakeanfällige Szenarien)
scripts/e2e.sh --full
```

`scripts/e2e.sh` fährt den Stack mit eigenem `COMPOSE_PROJECT_NAME=antrag-e2e` hoch
(berührt andere Stacks nicht), schreibt ein Wegwerf-`deploy/.env` (Mock AUS, mailpit-
SMTP, Altcha + Rate-Limit AUS für Determinismus), seedet deterministische Fixtures,
läuft Playwright und räumt restlos ab (`down -v`). Voraussetzung: in `frontend/`
einmalig `npm ci && npx playwright install --with-deps chromium`.

## Tiers

| Tier | Tag | Wann | Inhalt |
|------|-----|------|--------|
| **gating** (sharp, CI-Gate) | alles außer `@full` | jeder PR | deterministische Kern-Journeys, kein Keycloak/pytex/ClamAV auf dem Gate-Pfad |
| **full** (opt-in) | `@full` | `scripts/e2e.sh --full`, CI-Job `e2e-full` (Label `run-e2e-full` / `workflow_dispatch` / `RUN_E2E_FULL`) | Live-Vote-WS (2 Contexts + Beamer), Protokoll→PDF |

Begründung der Trennung (Frederiks Regel „lieber stabil als flaky"): WS-Live-Vote-
Timing und der pytex-tectonic-Bundle-Download (Minuten, netzabhängig) sind im CI-
Runner nicht zuverlässig deterministisch. Statt ein flakiges Gate zu erzwingen läuft
ein zuverlässiges Subset scharf; der Rest ist als `@full`/`fixme` dokumentiert
(testing.md §6: kein stiller skip — jeder mit begründetem Grund).

## Abgedeckt (gating, scharf)

- **01 apply** — öffentlicher Apply-Wizard → Bestätigung (Szenario 1, Teil).
- **02 magic-link-flow** — Antrag anlegen → Magic-Link (mailpit) → bearbeiten →
  Admin schaltet via Flow-Transition nach `pruefung` → read-only/gesperrt
  (Szenarien 1 + 2 + read-only).
- **03 rbac** — Unauth sieht geschützte Routen nicht (Szenario 7).
- **04 admin-form** — Form-Builder: Feld hinzufügen → neue Form-Version (Szenario 6).
- **05 budget-pots** — Budget-Töpfe-Sicht + Topf anlegen.

## Bewusst NICHT im Gate (opt-in/dokumentiert)

- **Live-Vote (WS, 2 Contexts + Beamer)** und **async Voting** — `e2e/full/live-vote.spec.ts`
  (`@full`, `fixme`): WS-Timing nicht gate-stabil; braucht Live-Vote-Seed-Fixture.
- **Protokoll → PDF → Versand** — `e2e/full/protocol-pdf.spec.ts` (`@full`, `fixme`):
  pytex-Render lädt tectonic-Bundle (langsam/netzabhängig).
- **OIDC-Login via Keycloak** — der Gate-Stack läuft bewusst ohne Mock-Keycloak; der
  Admin wird über eine geseedete Server-Session authentifiziert (siehe unten). Echte
  OIDC-E2E gehören in den full-Tier mit Keycloak-Test-Realm (noch nicht im Compose).
- **Anhang-Download nach ClamAV-Freigabe** — ClamAV-Start (~300s) ist nicht gate-
  tauglich; der Upload-Pfad (Annahme/Quarantäne) ist davon unabhängig.

## Architektur-Notizen

- **Seed** (`deploy/e2e/seed.py`, One-Shot-Service `seed`): legt für den von `0018`
  geseedeten Default-Antragstyp `foerderantrag` eine **aktive Form- + Flow-Version**
  an (ohne sie schlägt `POST /applications` fehl). Mintet zusätzlich eine **Admin-
  Server-Session** mit der App-eigenen `create_principal_session` (kennt
  `SESSION_SECRET`) → `ap_session`-Cookie. Kein Prod-Backdoor: nur der Test-Seed nutzt
  die normale Signier-Funktion (analog Djangos `force_login`). `global-setup.ts` baut
  daraus den Admin-`storageState`.
- **CSRF**: nur bei vorhandenem Auth-Cookie erzwungen (middleware.py). Unauth-Setup-
  POSTs (apply/magic-link) sind CSRF-frei; authentifizierte Writes laufen über die
  echte Angular-UI, deren Interceptor das Double-Submit-Token spiegelt.

## Gefundener Defekt (nicht Teil von T-40)

Die BE-Mail verlinkt `/antrag/<id>#t=<token>` (Fragment, security.md §1 — Token nie
an den Server), das FE konsumiert den Token jedoch auf `/status?t=…&app=…` und hat
**keine** `/antrag/:id`-Route. Magic-Link-Landing ist dadurch End-to-End kaputt. Der
gating-Test deckt die Magic-Link-*Fähigkeit* über den vom FE unterstützten `/status`-
Pfad ab (Token aus mailpit gezogen). Die Route-/Fragment-Diskrepanz ist als separater
Bugfix-Task ausgelagert.
