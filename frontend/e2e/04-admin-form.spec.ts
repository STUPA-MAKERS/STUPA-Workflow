import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

// Admin-Specs laufen mit der geseedeten Admin-Session (kein UI-Login/Keycloak nötig).
test.use({ storageState: ADMIN_STATE });

/**
 * Szenario 6 (testing.md §3.6): Admin-Config — Form-Builder legt ein neues Feld an
 * und **persistiert** eine neue Form-Version.
 *
 * Persistenz-Beweis: nach „Speichern" erscheint die Erfolgs-Meldung „Gespeichert."
 * — dieser Toast feuert ausschließlich auf das 2xx von
 * `POST /admin/application-types/{id}/form-versions` (form-builder.component.ts:198),
 * d. h. der Server hat die neue Form-Version wirklich angelegt. (Der Builder lädt
 * bestehende Versionen nicht zurück in die UI, daher kein Reload-Vergleich.)
 */
test('@gating Admin Form-Builder: Feld hinzufügen → Form-Version persistiert', async ({ page }) => {
  readArtifacts();
  await page.goto('/admin/forms');
  await expect(page.getByRole('heading', { name: 'Formular-Builder' })).toBeVisible();

  // Neues, gültiges Feld (Schlüssel + DE-Bezeichnung ⇒ formValid).
  const fieldKey = `e2e_feld_${Date.now()}`;
  await page.getByRole('button', { name: 'Feld hinzufügen' }).click();
  await page.getByRole('textbox', { name: 'Schlüssel' }).fill(fieldKey);
  await page.getByRole('textbox', { name: 'Bezeichnung (DE)' }).fill('E2E Feld');

  // JSON-Vorschau spiegelt den neuen Schlüssel (Builder-Zustand korrekt).
  await expect(page.locator('[data-testid="form-json"]')).toContainText(fieldKey);

  // Speichern → echte Persistenz: Erfolgs-Toast nur bei 2xx vom Server.
  await page.getByRole('button', { name: 'Als Form-Version speichern' }).click();
  await expect(page.getByText('Gespeichert.')).toBeVisible();
});
