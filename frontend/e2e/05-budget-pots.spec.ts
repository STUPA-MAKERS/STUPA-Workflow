import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

test.use({ storageState: ADMIN_STATE });

/**
 * Budget-Töpfe-Sicht (testing.md §3, „Budget-Töpfe-Sicht" aus dem Auftrag). Admin
 * öffnet `/budget/pots`, sieht den geseedeten Topf und legt einen weiteren an.
 */
test('@gating Admin Budget-Töpfe: Liste + Topf anlegen', async ({ page }) => {
  readArtifacts();
  await page.goto('/budget/pots');
  await expect(page.getByRole('heading', { name: 'Budget-Töpfe' })).toBeVisible();

  // Geseedeter Topf ist sichtbar.
  await expect(page.locator('table.pots__table')).toContainText('E2E-Topf');

  // Neuen Topf anlegen.
  const name = `Topf ${Date.now()}`;
  await page.locator('input#pot-name').fill(name);
  await page.locator('input#pot-total').fill('5000');
  await page.getByRole('button', { name: 'Anlegen' }).click();

  // Erscheint in der Tabelle.
  await expect(page.locator('table.pots__table')).toContainText(name);
});
