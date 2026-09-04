import { readFileSync } from 'node:fs';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

/** Deterministic fixtures that the seed service writes (scripts/e2e.sh). */
export interface Artifacts {
  sessionCookieName: string;
  adminCookie: string;
  applicantEmail: string;
  typeId: string;
  gremiumId: string | null;
  states: { initial: string; locked: string };
  fieldKeys: string[];
}

export function readArtifacts(): Artifacts {
  const file = process.env.E2E_ARTIFACTS_FILE;
  if (!file) throw new Error('E2E_ARTIFACTS_FILE nicht gesetzt — scripts/e2e.sh nutzen');
  return JSON.parse(readFileSync(file, 'utf-8')) as Artifacts;
}

export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? 'http://127.0.0.1:8025';

/**
 * Build a unique address for each test run. It keeps the scenarios apart.
 *
 * The domain is `e2e-antrag.de`, not `.test` or `.example`. The email-validator behind
 * the Pydantic `EmailStr` type rejects reserved special-use TLDs. Such a TLD gives a
 * 422 on POST /applications.
 */
export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e-antrag.de`;
}

/**
 * Create an application over the public API (POST /api/applications). The call is
 * unauthenticated and needs no CSRF token. The middleware enforces CSRF only with an
 * auth cookie (middleware.py). ALTCHA is OFF in the e2e stack.
 */
export async function createApplication(
  request: APIRequestContext,
  opts: { typeId: string; email: string; title: string },
): Promise<string> {
  const res = await request.post('/api/applications', {
    data: {
      typeId: opts.typeId,
      applicantEmail: opts.email,
      // `title`, not `titel`: the server prepends a mandatory system field named
      // `title` to every effective form (forms/validation.py, `system_title_field`),
      // so a payload without it answers 422 and no scenario past this point can run.
      data: { title: opts.title },
    },
  });
  expect(res.ok(), `POST /api/applications → ${res.status()}: ${await res.text()}`).toBeTruthy();
  const body = (await res.json()) as { applicationId: string };
  return body.applicationId;
}

/** Request a magic link (POST /api/auth/magic-link). The route always answers 202. */
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
 * Pull the newest magic-link token that mailpit holds for `email`. The helper polls
 * until the mail arrives instead of a fixed `sleep`, because the worker delivers the
 * mail asynchronously. The token sits in the link fragment `#t=<token>` (security.md
 * §1: the token never goes to the server).
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

/** Extract the token from a link `…/antrag/<id>#t=<token>` or `?t=…`. */
export function extractToken(body: string): string | null {
  const m = body.match(/[#?]t=([A-Za-z0-9._-]+)/);
  return m ? m[1] : null;
}

/**
 * Open a guarded route as an unauthenticated visitor and check that NO content
 * appears. The authGuard triggers a full page redirect to `/api/auth/login`. The e2e
 * stack has no mock Keycloak and no configured OIDC, so the redirect ends in a 404 or
 * on the login page. It never ends on the guarded page.
 */
export async function expectAccessDenied(page: Page, deniedHeading: RegExp): Promise<void> {
  await expect(page.getByRole('heading', { name: deniedHeading })).toHaveCount(0);
}
