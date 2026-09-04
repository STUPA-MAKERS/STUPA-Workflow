import { expect, test } from '@playwright/test';

/**
 * Scenario 7 (testing.md §3.7): RBAC fails closed. An unauthenticated visitor must
 * NOT see a guarded area. The authGuard either triggers a full page redirect to
 * `/api/auth/login`, or it routes to `/forbidden` when a session exists but lacks the
 * permission. Without configured OIDC the redirect ends in a 404, because the e2e
 * stack has no mock Keycloak (the mock is OFF since #101). The test checks that the
 * guarded content stays hidden and that the visitor lands on login or forbidden.
 */
const GUARDED = ['/applications', '/admin', '/admin/cost-centres', '/admin/forms'];

for (const path of GUARDED) {
  test(`@gating Unauth sieht ${path} nicht`, async ({ page }) => {
    await page.goto(path);
    await page.waitForURL(/auth\/login|forbidden/, { timeout: 15_000 });
    expect(new URL(page.url()).pathname).not.toBe(path);
  });
}
