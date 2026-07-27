import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { FullConfig } from '@playwright/test';
import { readArtifacts } from './helpers';

export const ADMIN_STATE = 'e2e/.auth/admin.json';

/**
 * Global setup: build a Playwright `storageState` from the seed artifact. The artifact
 * holds the admin session that the seed service minted (`ap_session` cookie). Admin
 * specs use it with `test.use({ storageState: ADMIN_STATE })`. They need no UI login
 * and no Keycloak.
 *
 * `secure: false`: the e2e stack runs on plain HTTP (127.0.0.1). With the secure flag
 * the browser would not send the cookie. The server reads only the value, so the flag
 * has no meaning on the inbound path.
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
