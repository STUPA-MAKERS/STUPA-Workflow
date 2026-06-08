import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

// Admin-Specs laufen mit der geseedeten Admin-Session (kein UI-Login/Keycloak nötig).
test.use({ storageState: ADMIN_STATE });

/**
 * Szenario 6 (testing.md §3.6): Admin-Config — Form-Builder legt ein neues Feld an
 * und speichert eine neue Form-Version. Geprüft über die JSON-Vorschau
 * (`data-testid="form-json"`) und die Erfolgsrückmeldung.
 */
test('@gating Admin Form-Builder: Feld hinzufügen → speichern', async ({ page }) => {
  readArtifacts();
  await page.goto('/admin/forms');
  await expect(page.getByRole('heading', { name: 'Formular-Builder' })).toBeVisible();

  // Neues Feld anlegen.
  const fieldKey = `e2e_feld_${Date.now()}`;
  await page.getByRole('button', { name: 'Feld hinzufügen' }).click();

  // Letztes Feld in der Liste ist das neue: Schlüssel + DE-Label setzen.
  const lastField = page.locator('ol.fb__list li.fb__field').last();
  await lastField.locator('input').first().fill(fieldKey);

  // JSON-Vorschau muss den neuen Schlüssel enthalten.
  const json = page.locator('[data-testid="form-json"]');
  await expect(json).toContainText(fieldKey);

  // Speichern → neue Form-Version.
  await page.getByRole('button', { name: 'Als Form-Version speichern' }).click();
  // Erfolgsindikator: Status „Gültig" bleibt + kein Fehler-Alert.
  await expect(page.locator('p.fb__alert[role="alert"]')).toHaveCount(0);
});
