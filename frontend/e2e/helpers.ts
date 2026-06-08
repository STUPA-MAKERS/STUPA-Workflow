import { readFileSync } from 'node:fs';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

/** Vom Seed-Service geschriebene, deterministische Fixtures (scripts/e2e.sh). */
export interface Artifacts {
  sessionCookieName: string;
  adminCookie: string;
  applicantEmail: string;
  typeId: string;
  gremiumId: string | null;
  budgetPotId: string | null;
  states: { initial: string; locked: string };
  fieldKeys: string[];
}

export function readArtifacts(): Artifacts {
  const file = process.env.E2E_ARTIFACTS_FILE;
  if (!file) throw new Error('E2E_ARTIFACTS_FILE nicht gesetzt — scripts/e2e.sh nutzen');
  return JSON.parse(readFileSync(file, 'utf-8')) as Artifacts;
}

export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? 'http://127.0.0.1:8025';

/** Eindeutiger Bezeichner pro Testlauf — verhindert Kreuz-Interferenz der Szenarien. */
export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e.test`;
}

/**
 * Antrag öffentlich anlegen (POST /api/applications). Unauthentifiziert → CSRF-frei
 * (middleware.py: Enforcement nur mit Auth-Cookie). Altcha ist im e2e-Stack AUS.
 */
export async function createApplication(
  request: APIRequestContext,
  opts: { typeId: string; email: string; title: string },
): Promise<string> {
  const res = await request.post('/api/applications', {
    data: {
      typeId: opts.typeId,
      applicantEmail: opts.email,
      data: { titel: opts.title },
    },
  });
  expect(res.ok(), `POST /api/applications → ${res.status()}: ${await res.text()}`).toBeTruthy();
  const body = (await res.json()) as { applicationId: string };
  return body.applicationId;
}

/** Magic-Link anfordern (POST /api/auth/magic-link). Antwortet immer 202. */
export async function requestMagicLink(
  request: APIRequestContext,
  opts: { email: string; applicationId: string },
): Promise<void> {
  const res = await request.post('/api/auth/magic-link', {
    data: { email: opts.email, application_id: opts.applicationId },
  });
  expect([200, 202]).toContain(res.status());
}

/**
 * Den jüngsten an `email` zugestellten Magic-Link-Token aus mailpit ziehen.
 * Wartet aktiv (Worker stellt asynchron zu) statt `sleep` — bis die Mail da ist.
 * Token steht im Link-Fragment `#t=<token>` (security.md §1: nie an den Server).
 */
export async function fetchMagicLinkToken(
  request: APIRequestContext,
  email: string,
): Promise<string> {
  const deadline = Date.now() + 30_000;
  let lastBody = '';
  while (Date.now() < deadline) {
    const list = await request.get(`${MAILPIT_URL}/api/v1/search`, {
      params: { query: `to:${email}` },
    });
    if (list.ok()) {
      const msgs = (await list.json()) as { messages?: { ID: string }[] };
      if (msgs.messages && msgs.messages.length > 0) {
        const id = msgs.messages[0].ID;
        const msg = await request.get(`${MAILPIT_URL}/api/v1/message/${id}`);
        const body = (await msg.json()) as { Text?: string; HTML?: string };
        lastBody = body.Text ?? body.HTML ?? '';
        const token = extractToken(lastBody);
        if (token) return token;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Kein Magic-Link-Token in mailpit für ${email}. Letzter Body: ${lastBody}`);
}

/** Token aus Link `…/antrag/<id>#t=<token>` (oder `?t=…`) extrahieren. */
export function extractToken(body: string): string | null {
  const m = body.match(/[#?]t=([A-Za-z0-9._-]+)/);
  return m ? m[1] : null;
}

/**
 * Eine geschützte Route als Unauth aufrufen und prüfen, dass KEIN Inhalt erscheint.
 * Der authGuard löst einen Full-Page-Redirect auf `/api/auth/login` aus; ohne
 * konfiguriertes OIDC (kein Mock-Keycloak im e2e-Stack) endet das in 404/Login —
 * jedenfalls NICHT auf der geschützten Seite.
 */
export async function expectAccessDenied(page: Page, deniedHeading: RegExp): Promise<void> {
  await expect(page.getByRole('heading', { name: deniedHeading })).toHaveCount(0);
}
