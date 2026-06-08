import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright-E2E (T-40) gegen den *echten* Compose-Stack — NICHT gegen `ng serve`
 * und NICHT gegen die Mock-API (seit #101 AUS). Der Stack wird von `scripts/e2e.sh`
 * hochgefahren (eigener COMPOSE_PROJECT_NAME, `down -v`); diese Config startet
 * KEINEN Webserver, sondern fährt gegen den laufenden `web`-Container.
 *
 * Tiers via Tag: Specs mit `@full` (Live-Vote-WS, Protokoll→PDF) laufen nur opt-in
 * (`scripts/e2e.sh --full`); das CI-Gate läuft den Rest (`--grep-invert @full`).
 *
 * Determinismus (testing.md §3, „keine Flakes"): `workers: 1` + `fullyParallel:
 * false` — die Szenarien teilen einen geseedeten Antragstyp und eine Admin-Session;
 * serielle Ausführung schließt Zustands-Races aus. Retries begrenzt (CI: 1).
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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Stack läuft auf plain HTTP hinter dem Proxy; selbstsignierte Edge-Certs egal.
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
