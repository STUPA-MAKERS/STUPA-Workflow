import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';

test.use({ storageState: ADMIN_STATE });

/**
 * Budgets: the admin opens the page "Budgets" and sees real budgets, served from the
 * database over the budget API.
 *
 * The page is `/admin/budgets`, its heading is "Budgets", and the budgets render through
 * the shared `app-data-table`. The assertion uses a budget every deployment has: migration
 * `0002_seed` ships VS-Mittel and QS-Mittel. The old path `/admin/cost-centres` leads here.
 */
test('@gating Admin Budgets zeigt die Budgets aus der Datenbank', async ({ page }) => {
  await page.goto('/admin/cost-centres');
  await expect(page).toHaveURL(/\/admin\/budgets$/);
  await expect(page.getByRole('heading', { name: 'Budgets', level: 1 })).toBeVisible();

  await expect(page.locator('table.dt__table')).toContainText('QS-Mittel');
});
