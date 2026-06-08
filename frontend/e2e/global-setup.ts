import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { FullConfig } from '@playwright/test';
import { readArtifacts } from './helpers';

export const ADMIN_STATE = 'e2e/.auth/admin.json';

/**
 * Globaler Setup: baut aus dem Seed-Artefakt einen Playwright-`storageState` mit der
 * vom Seed-Service gemünzten Admin-Session (`ap_session`-Cookie). Admin-Specs nutzen
 * ihn via `test.use({ storageState: ADMIN_STATE })` — kein UI-Login, kein Keycloak.
 *
 * `secure: false`: der e2e-Stack läuft auf plain HTTP (127.0.0.1) — sonst sendet der
 * Browser das Cookie nicht. Der Server liest nur den Wert; das Secure-Flag ist
 * inbound bedeutungslos.
 */
export default function globalSetup(_config: FullConfig): void {
  const art = readArtifacts();
  const base = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8080';
  const url = new URL(base);

  const storage = {
    cookies: [
      {
        name: art.sessionCookieName,
        value: art.adminCookie,
        domain: url.hostname,
        path: '/',
        expires: Math.floor(Date.now() / 1000) + 30 * 24 * 3600,
        httpOnly: true,
        secure: false,
        sameSite: 'Lax' as const,
      },
    ],
    origins: [],
  };

  mkdirSync(dirname(ADMIN_STATE), { recursive: true });
  writeFileSync(ADMIN_STATE, JSON.stringify(storage, null, 2));
}
