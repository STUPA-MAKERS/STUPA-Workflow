import { expect, test } from '@playwright/test';

/**
 * Szenario 7 (testing.md §3.7): RBAC fail-closed. Ein unauthentifizierter Besucher
 * darf geschützte Bereiche NICHT sehen. Der authGuard löst entweder einen Full-Page-
 * Redirect auf `/api/auth/login` aus (ohne konfiguriertes OIDC → 404; kein Mock-
 * Keycloak im e2e-Stack, Mock seit #101 AUS) oder routet (bei vorhandener, aber
 * unzureichender Session) nach `/forbidden`. Geprüft: der geschützte Inhalt erscheint
 * nicht und der Besucher landet auf Login/Forbidden.
 */
const GUARDED = ['/applications', '/admin', '/budget/pots', '/admin/forms'];

for (const path of GUARDED) {
  test(`@gating Unauth sieht ${path} nicht`, async ({ page }) => {
    await page.goto(path);
    await page.waitForURL(/auth\/login|forbidden/, { timeout: 15_000 });
    // Doppelt abgesichert: nicht mehr auf der geschützten Route.
    expect(new URL(page.url()).pathname).not.toBe(path);
  });
}
