import { devices, expect, test, type Page } from '@playwright/test';
import { AXE_ROUTES, MISSING, type Ids } from './axe-routes';
import { ADMIN_STATE } from './global-setup';
import { measureOpaqueHeads } from './opaque-heads';

/**
 * §ui-kit:NF/usability/layout/002420: on a phone, every bar and head that sticks over
 * scrolling content is opaque in every state, also before the page script has noted the
 * scroll. The name `opaqueBeforeScript` is the test of the rule.
 *
 * The rows showed through the search bar of a phone list on a fast scroll, and the fault came
 * back with each new look of the heads, because only a browser computes the colours. The check
 * runs on every route without a parameter (`axe-routes.ts`), in the light theme and in very
 * high contrast, which gives the bars another colour. The page is made taller and scrolled, so
 * the bars stick, and `measureOpaqueHeads` reads them with and without their state classes.
 */
const MODES = [
  { name: 'light', theme: 'light', display: {} },
  { name: 'very high contrast', theme: 'dark', display: { veryHigh: true } },
] as const;
const PHONE = devices['Pixel 7'];
/** The routes of the check have no parameter, so no id is read. */
const NO_IDS: Ids = {
  application: MISSING,
  meeting: MISSING,
  gremium: MISSING,
  ticket: MISSING,
  board: MISSING,
  card: MISSING,
  form: MISSING,
};

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

for (const mode of MODES) {
  test.describe(`opaqueBeforeScript ${mode.name}`, () => {
    for (const route of AXE_ROUTES.filter((r) => !r.path.includes(':') && !r.path.includes('*'))) {
      test(`${route.path || '/'} (${mode.name})`, async ({ browser, baseURL }) => {
        const context = await browser.newContext({
          ...PHONE,
          baseURL,
          locale: 'de-DE',
          storageState: route.public ? undefined : ADMIN_STATE,
        });
        await context.addInitScript((m) => {
          localStorage.setItem('ap.theme', m.theme);
          localStorage.setItem('ap.theme.display', JSON.stringify(m.display));
        }, mode);
        const page = await context.newPage();
        await page.goto(route.url(NO_IDS));
        await settle(page);
        await page.evaluate(() => {
          document.documentElement.style.minHeight = '400vh';
          window.scrollTo(0, 600);
        });
        await page.waitForTimeout(300);
        const report = await page.evaluate(measureOpaqueHeads);
        expect(report.seeThrough, 'opaqueBeforeScript').toEqual([]);
        await context.close();
      });
    }
  });
}
