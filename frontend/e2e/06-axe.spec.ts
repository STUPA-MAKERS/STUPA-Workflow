import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { AXE_ROUTES, type Ids } from './axe-routes';
import { ADMIN_STATE } from './global-setup';
import { createApplication, readArtifacts, uniqueEmail } from './helpers';

/**
 * § NF/accessibility/conformance/000491: every route passes an axe check in both themes.
 *
 * jsdom cannot compute contrast or layout, so only a real browser finds these errors. The
 * check uses the WCAG 2.0, 2.1 and 2.2 A and AA tags, and a violation fails the test. The
 * setup creates one item of each kind that a detail route shows; `axe-routes.ts` has the
 * table and the reason for the fixed missing ids.
 */
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const THEMES = ['light', 'dark'] as const;

/** A cookie-authenticated unsafe request needs the XSRF cookie echoed in the header. */
async function xsrf(api: APIRequestContext): Promise<Record<string, string>> {
  await api.get('/api/auth/me');
  const token = (await api.storageState()).cookies.find((c) => c.name === 'XSRF-TOKEN')?.value;
  return token ? { 'X-XSRF-TOKEN': token } : {};
}

async function json<T>(res: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  expect(res.ok(), `${res.url()} → ${res.status()}: ${await res.text()}`).toBeTruthy();
  return (await res.json()) as T;
}

/**
 * The application goes through a context without the admin cookie: the public route needs
 * no CSRF token then, while a cookie-authenticated POST does (middleware.py).
 */
async function createIds(api: APIRequestContext, pub: APIRequestContext): Promise<Ids> {
  const art = readArtifacts();
  const headers = await xsrf(api);
  const application = await createApplication(pub, {
    typeId: art.typeId,
    email: uniqueEmail('axe'),
    title: 'Barrierefreiheit prüfen',
  });
  const gremium = art.gremiumId ?? (await json<{ id: string }[]>(await api.get('/api/committees')))[0].id;
  const meeting = await json<{ id: string }>(
    await api.post('/api/meetings', {
      headers,
      data: { gremiumId: gremium, title: 'Axe-Sitzung', date: '2030-01-15', startTime: '18:00' },
    }),
  );
  await json(await api.post('/api/tickets', { headers, data: { kind: 'bug', title: 'Axe', body: 'Prüfung' } }));
  const tickets = await json<{ items: { id: string }[] }>(await api.get('/api/tickets'));
  const boards = await json<{ id: string }[]>(await api.get('/api/todos/boards'));
  const card = await json<{ id: string }>(
    await api.post('/api/todos/cards', { headers, data: { boardId: boards[0].id, title: 'Axe-Karte' } }),
  );
  return {
    application,
    meeting: meeting.id,
    gremium,
    ticket: tickets.items[0].id,
    board: boards[0].id,
    card: card.id,
    form: art.typeId,
  };
}

/** Wait until the route has loaded its data and the skeletons are gone. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

let ids: Ids;

test.beforeAll(async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL, storageState: ADMIN_STATE });
  const pub = await playwright.request.newContext({ baseURL });
  ids = await createIds(api, pub);
  await Promise.all([api.dispose(), pub.dispose()]);
});

for (const theme of THEMES) {
  test.describe(`axe ${theme}`, () => {
    for (const route of AXE_ROUTES) {
      test(`@a11y ${route.path || '/'} (${theme})`, async ({ browser, baseURL }) => {
        const context = await browser.newContext({
          baseURL,
          locale: 'de-DE',
          storageState: route.public ? undefined : ADMIN_STATE,
        });
        await context.addInitScript((t) => localStorage.setItem('ap.theme', t), theme);
        const page = await context.newPage();
        await page.goto(route.url(ids));
        await settle(page);
        const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const found = result.violations.map((v) => ({
          rule: v.id,
          impact: v.impact,
          nodes: v.nodes.map((n) => n.target.join(' ')).slice(0, 5),
        }));
        expect(found).toEqual([]);
        await context.close();
      });
    }
  });
}
