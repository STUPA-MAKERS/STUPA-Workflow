import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

test.use({ storageState: ADMIN_STATE });

/**
 * Budget-Töpfe-Sicht (testing.md §3, „Budget-Töpfe-Sicht" aus dem Auftrag). Admin
 * öffnet `/budget/pots` und sieht den vom Seed angelegten Topf in der echten Liste
 * (Daten aus der DB über `GET /api/budget/pots`).
 */
test('@gating Admin Budget-Töpfe-Sicht zeigt geseedeten Topf', async ({ page }) => {
  readArtifacts();
  await page.goto('/budget/pots');
  await expect(page.getByRole('heading', { name: 'Budget-Töpfe' })).toBeVisible();

  // Geseedeter Topf ist in der echten Liste sichtbar.
  await expect(page.locator('table.pots__table')).toContainText('E2E-Topf');
});
