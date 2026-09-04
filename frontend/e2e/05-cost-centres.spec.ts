import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';

test.use({ storageState: ADMIN_STATE });

/**
 * Budget view (testing.md §3): the admin opens the cost-centre tree and sees real cost
 * centres, served from the database over the budget API.
 *
 * The page is `/admin/cost-centres`, its heading is "Budgets & Kostenstellen", and it
 * renders through the shared `app-data-table`. The assertion uses a cost centre every
 * deployment has: migration `0002_seed` ships VS-Mittel and QS-Mittel.
 */
test('@gating Admin Budget-Sicht zeigt Kostenstellen aus der Datenbank', async ({ page }) => {
  await page.goto('/admin/cost-centres');
  await expect(page.getByRole('heading', { name: 'Budgets & Kostenstellen' })).toBeVisible();

  await expect(page.locator('table.dt__table')).toContainText('QS-Mittel');
});
