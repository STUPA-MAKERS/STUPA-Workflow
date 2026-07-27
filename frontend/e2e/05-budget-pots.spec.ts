import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

test.use({ storageState: ADMIN_STATE });

/**
 * Budget pots view (testing.md §3, the budget pots view from the task brief). The
 * admin opens `/budget/pots` and sees the seeded pot in the real list. The data comes
 * from the database over `GET /api/budget/pots`.
 */
test('@gating Admin Budget-Töpfe-Sicht zeigt geseedeten Topf', async ({ page }) => {
  readArtifacts();
  await page.goto('/budget/pots');
  await expect(page.getByRole('heading', { name: 'Budget-Töpfe' })).toBeVisible();

  await expect(page.locator('table.pots__table')).toContainText('E2E-Topf');
});
