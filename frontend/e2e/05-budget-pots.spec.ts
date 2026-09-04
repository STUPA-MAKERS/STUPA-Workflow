import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

test.use({ storageState: ADMIN_STATE });

/**
 * Budget view (testing.md §3): the admin opens the cost-centre tree and sees the
 * seeded pot in the real list. The data comes from the database over the budget API.
 *
 * Three things moved under this test since it was written, which is why it asserts
 * differently than it reads in the history: the page lives at `/admin/budget-pots`
 * rather than `/budget/pots`, its heading is "Budgets & Kostenstellen", and the
 * hand-rolled `table.pots__table` is gone — the page renders through the shared
 * `app-data-table`, whose table carries `dt__table`.
 */
test('@gating Admin Budget-Sicht zeigt geseedeten Topf', async ({ page }) => {
  readArtifacts();
  await page.goto('/admin/budget-pots');
  await expect(page.getByRole('heading', { name: 'Budgets & Kostenstellen' })).toBeVisible();

  await expect(page.locator('table.dt__table')).toContainText('E2E-Topf');
});
