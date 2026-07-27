import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

// Admin specs run with the seeded admin session. They need no UI login and no Keycloak.
test.use({ storageState: ADMIN_STATE });

/**
 * Scenario 6 (testing.md §3.6): admin config. The form builder adds a new field and
 * **persists** a new form version.
 *
 * Proof of persistence: after the save the success message `Gespeichert.` appears.
 * This toast fires only on a 2xx from
 * `POST /admin/application-types/{id}/form-versions` (form-builder.component.ts:198).
 * The server therefore created the new form version. The builder does not load
 * existing versions back into the UI, so the test cannot compare after a reload.
 */
test('@gating Admin Form-Builder: Feld hinzufügen → Form-Version persistiert', async ({ page }) => {
  readArtifacts();
  await page.goto('/admin/forms');
  await expect(page.getByRole('heading', { name: 'Formular-Builder' })).toBeVisible();

  // A new field is valid only with a key and a German label, which gives formValid.
  const fieldKey = `e2e_feld_${Date.now()}`;
  await page.getByRole('button', { name: 'Feld hinzufügen' }).click();
  await page.getByRole('textbox', { name: 'Schlüssel' }).fill(fieldKey);
  await page.getByRole('textbox', { name: 'Bezeichnung (DE)' }).fill('E2E Feld');

  await expect(page.locator('[data-testid="form-json"]')).toContainText(fieldKey);

  // The success toast fires only on a 2xx from the server, so it proves persistence.
  await page.getByRole('button', { name: 'Als Form-Version speichern' }).click();
  await expect(page.getByText('Gespeichert.')).toBeVisible();
});
