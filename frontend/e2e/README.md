# E2E-Tests (T-40) — Playwright vs echtem Compose-Stack

End-to-End-Abdeckung der Kern-User-Journeys (testing.md §3) gegen den **echten**
Stack (FastAPI + Angular + Postgres + Redis + MinIO + pytex hinter Nginx), **nicht**
gegen die Mock-API (seit #101 AUS). Magic-Link-Mails landen im `mailpit`-SMTP-Sink.

## Ausführen

```bash
scripts/e2e.sh
```

Fährt den Stack mit eigenem `COMPOSE_PROJECT_NAME=antrag-e2e` hoch (berührt andere
Stacks nicht), schreibt ein Wegwerf-`deploy/.env` (Mock AUS, mailpit-SMTP, Altcha +
Rate-Limit AUS für Determinismus), seedet deterministische Fixtures, läuft Playwright
und räumt restlos ab (`down -v`). Voraussetzung: in `frontend/` einmalig
`npm ci && npx playwright install --with-deps chromium`.

## Abgedeckt — gating (scharf, jeder PR, CI-Job `e2e`)

Deterministisch, kein Keycloak/pytex/ClamAV auf dem Gate-Pfad:

- **01 apply** — öffentlicher Apply-Wizard durch ALLE Schritte bis zur Review-
  Zusammenfassung (Antragsart → Kontakt → dynamisches Formular der geseedeten Form-
  Version → Prüfen). Der finale Submit-Klick ist NICHT Teil der Assertion: die
  FE-ALTCHA-Komponente ist ein Stub (`altcha-stub-solution`), den das Backend-Schema
  als „malformed altcha solution" mit 422 ablehnt — der UI-Submit ist unabhängig von
  T-40 blockiert (Issue #111; reale Captcha-Wiring ist ein eigener Task). Die
  Antrags-*Erstellung* + Folge-Journey ist über 02 real abgedeckt (Szenario 1, Teil).
- **02 magic-link-flow** — Antrag anlegen → Magic-Link (echtes SMTP via mailpit) →
  bearbeiten → Admin schaltet via Flow-Transition nach `pruefung` → read-only/gesperrt
  (Szenarien 1 + 2 + read-only).
- **03 rbac** — Unauth sieht geschützte Routen nicht (Szenario 7).
- **04 admin-form** — Form-Builder: Feld hinzufügen → Form-Version **persistiert**
  (Erfolgs-Toast nur auf 2xx vom Server) (Szenario 6).
- **05 budget-pots** — Budget-Töpfe-Sicht + Topf anlegen.

**T-40 deckt damit 4/7 SDS-Szenarien real grün ab** (1 apply+magic-link, 2 flow,
6 admin-config, 7 RBAC) **plus** Budget-Töpfe + read-only.

## Bewusst (noch) NICHT abgedeckt — als Follow-up-Issues, keine hohlen Stubs

Frederiks Regel „lieber stabil als flaky": voll-grün für alle 7 Szenarien gegen den
realen Stack ist im CI nicht zuverlässig deterministisch (WS-Timing, pytex-tectonic,
Keycloak, ClamAV). Diese Szenarien sind als klar benannte Issues ausgelagert statt
als leere `test.fixme()`-Stubs Abdeckung vorzutäuschen:

| Szenario (SDS) | Issue |
|----------------|-------|
| 3 async Voting | #107 |
| 4 Live-Vote (WS, 2 Contexts + Beamer) | #108 |
| 5 Protokoll → PDF → Versand (pytex) | #109 |
| OIDC-Login via Keycloak-Test-Realm | #110 |

## Architektur-Notizen

- **Seed** (`deploy/e2e/seed.py`, One-Shot-Service `seed`): legt für den von `0018`
  geseedeten Default-Antragstyp `foerderantrag` eine **aktive Form- + Flow-Version**
  an (ohne sie schlägt `POST /applications` fehl). Mintet eine **Admin-Server-Session**
  mit der App-eigenen `create_principal_session` (kennt `SESSION_SECRET`) →
  `ap_session`-Cookie. Kein Prod-Backdoor: nur der Test-Seed nutzt die normale
  Signier-Funktion (analog Djangos `force_login`). `global-setup.ts` baut daraus den
  Admin-`storageState`.
- **CSRF**: nur bei vorhandenem Auth-Cookie erzwungen (middleware.py). Unauth-Setup-
  POSTs (apply/magic-link) sind CSRF-frei; authentifizierte Writes laufen über die
  echte Angular-UI, deren Interceptor das Double-Submit-Token spiegelt.
- **OIDC + Altcha AUS**: die optionalen Secrets dürfen NICHT als leerer String
  gesetzt sein (`min_length=16` in `app.settings` → sonst bricht `get_settings()` →
  migrate exit 1). `scripts/e2e.sh` strippt die leeren Zeilen aus dem e2e-`.env`.
- **Migration 0019** (`application.manage`): die Flow-Transition-Endpunkte + das FE-
  Gating verlangen die Permission `application.manage`, die in `0003` an KEINE Rolle
  geseedet war (Seed-Lücke wie `form.configure`/`flow.configure` in 0010/0016) → ohne
  sie kann auch ein Admin keinen Antrag durch den Flow schalten. `0019_seed_application_manage`
  zieht sie idempotent an die admin-Rolle nach (down_revision = 0018, single head).
- **web-Healthcheck/Mounts** (overlay): web nutzt `127.0.0.1` statt `localhost`
  (IPv4; nginx lauscht nur IPv4, da der conf-Mount read-only ist) und `:z`-Mounts
  (SELinux/podman lokal; No-op auf CI-docker).

## Gefundener Defekt (separater Bugfix-Task, nicht Teil von T-40)

Die BE-Mail verlinkt `/antrag/<id>#t=<token>` (Fragment, security.md §1 — Token nie
an den Server), das FE konsumiert den Token jedoch auf `/status?t=…&app=…` und hat
**keine** `/antrag/:id`-Route → Magic-Link-Landing ist End-to-End kaputt. Der
gating-Test deckt die Magic-Link-*Fähigkeit* über den FE-unterstützten `/status`-Pfad
ab (Token aus mailpit gezogen).
