import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E tests (T-40) run against the real compose stack. They do not run against
 * `ng serve` or the mock API. The mock API is off since #101. `scripts/e2e.sh` starts the
 * stack with its own COMPOSE_PROJECT_NAME and a `down -v`. This config starts no web server.
 * It uses the `web` container that already runs.
 *
 * The tests cover the deterministic subset that binds the gate. The open scenarios (async
 * voting, live-vote WebSocket, protocol to PDF, OIDC) moved to follow-up issues. See
 * e2e/README.md.
 *
 * Determinism (testing.md section 3, "no flakes"): `workers: 1` and `fullyParallel: false`.
 * The scenarios share one seeded application type and one admin session. Serial execution
 * prevents state races. Retries stay limited to 1 in CI.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8080';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : [['list']],
  use: {
    baseURL: BASE_URL,
    // Force German. The i18n detection in `i18n.service.ts` reads navigator.language, and
    // Chromium defaults to en-US. The specs match the German strings.
    locale: 'de-DE',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // The stack runs on plain HTTP behind the proxy. Self-signed edge certificates do not
    // matter.
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
