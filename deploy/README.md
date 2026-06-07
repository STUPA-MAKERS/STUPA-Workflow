# deploy

Compose-Stack für eine VM. Plain HTTP intern; TLS terminiert der externe Nginx Proxy
Manager. Einziger Host-Port ist `web` auf `127.0.0.1:8080` — alle anderen Services
hängen nur am internen Netz und sind nicht vom Internet erreichbar.

## Start

```bash
cp .env.example .env        # Werte einsetzen, NIE committen
docker compose config -q    # Topologie validieren
docker compose up -d --build
```

## Services

| Service | Rolle | Host-Port |
|---|---|---|
| `web` | nginx, serviert die gebaute SPA, routet `/api` → `api` | `127.0.0.1:8080` |
| `migrate` | One-Shot: `alembic upgrade head`, dann Exit | — |
| `api` | FastAPI (uvicorn `--proxy-headers`) | — |
| `worker` | arq (Mail-Versand, nächtlicher Budget-Rollup) | — |
| `postgres` | PostgreSQL 16 | — |
| `redis` | Redis 7 (arq-Broker, Rate-Limit, Altcha-Replay) | — |
| `minio` | S3-Objektspeicher (Anhänge) | — |
| `clamav` | Virenscan (langer erster Start: Signaturen) | — |
| `pytex` | interner Markdown→PDF-Renderer | — |
| `altcha` | ALTCHA Sentinel (Captcha-Verifier) | — |
| `backup` | tägliches verschlüsseltes Backup (pg_dump + MinIO-Spiegel, age); Profil `prod`/`backup` | — |

`web` wird über das `..`-Repo-Root in zwei Stufen gebaut (`web/Dockerfile`): Stage 1
baut mit Node das Angular-Frontend, Stage 2 serviert es per nginx. `web/nginx.conf` ist
ins Image gebacken, aber zusätzlich gemountet — so lassen sich prod-Edits (z. B.
`real_ip`-CIDR des Proxy Managers) ohne Rebuild machen.

## Migrationen

`migrate` läuft einmalig vor `api`/`worker` (beide haben
`depends_on: migrate: service_completed_successfully`). `alembic upgrade head` ist
idempotent — schon eingespielte Revisionen werden übersprungen. Kein manueller
Migrationsschritt nötig, auch nicht beim Update: `docker compose up -d --build` zieht
das neue Image und `migrate` spielt offene Revisionen ein, bevor die App hochfährt.

Optional läuft `migrate` unter einem eigenen DB-User (`DB_MIGRATION_URL`), getrennt vom
Laufzeit-User der App.

## Netze

- `internal` — bridge, keine publizierten Ports → kein Ingress. Egress bleibt offen
  (Worker: SMTP/WebDAV/Webhooks, pytex: tectonic-Bundle, api: OIDC).
- `proxy` — in prod das vom Nginx Proxy Manager verwaltete Netz; dort `external: true`
  setzen und das NPM-Netz referenzieren.

## Konfiguration

Alle Secrets in `.env` (Vorlage: `.env.example`). Pflichtwerte für den API-Start:
`DATABASE_URL`, `SESSION_SECRET`, `MAGIC_LINK_SECRET`. OIDC, SMTP und Altcha aktivieren
sich, sobald ihre Werte gesetzt sind — fehlen sie, bleiben die jeweiligen Funktionen
sauber abgeschaltet (kein Crash). Vollständige Referenz im
[Configuration-Wiki](https://github.com/frederikbeimgraben/antragsplattform/wiki/Configuration).

## Profile

- **prod** — hinter NPM, externe Keycloak/SMTP/Nextcloud, ClamAV aktiv, **kein**
  Host-Port außer `web`. Aktiviert zusätzlich den `backup`-Service:
  ```bash
  docker compose --profile prod up -d --build
  ```
  Für das echte NPM-Netz im compose `proxy:` auf `external: true` umstellen.
- Default (ohne Profil) = Smoke-/Dev-Stack ohne `backup`.

## Backup & Restore

Tägliches verschlüsseltes Backup (PostgreSQL + MinIO, age) und die getestete
Restore-Prozedur: siehe [`backup/README.md`](backup/README.md). Restore-Test:
`../scripts/restore-smoke.sh`.

## Smoke-Test

```bash
../scripts/smoke.sh        # up + warten bis healthy
../scripts/smoke.sh down   # Stack inkl. Volumes abräumen
```
