import { expect, test } from '@playwright/test';
import { readArtifacts, uniqueEmail } from './helpers';

/**
 * Szenario 1 (Teil): Antrag stellen über den öffentlichen Apply-Wizard gegen den
 * echten Stack (testing.md §3.1). Public, Altcha-Stub, bis Bestätigungsseite.
 * Der seedete Default-Antragstyp `foerderantrag` hat eine aktive Form-/Flow-Version.
 */
test('@gating öffentlicher Apply-Wizard → Bestätigung', async ({ page }) => {
  readArtifacts(); // stellt sicher, dass geseedet wurde
  await page.goto('/apply');
  await expect(page.getByRole('heading', { name: 'Antrag stellen' })).toBeVisible();

  // Schritt 1: Antragsart wählen (erster Typ).
  await page.getByRole('radio').first().click();
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Schritt 2: Kontakt (E-Mail Pflicht).
  await page.locator('input[type="email"]').fill(uniqueEmail('apply'));
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Schritt 3: Formularfelder (Pflichtfeld „titel").
  await page.locator('formly-form input[type="text"]').first().fill('E2E Testantrag');
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Review: Altcha-Stub lösen, absenden.
  await expect(page.getByRole('heading', { name: 'Prüfen & Absenden' })).toBeVisible();
  await page.locator('app-altcha button').click();
  await page.getByRole('button', { name: 'Antrag absenden' }).click();

  // Erfolg: Bestätigungsseite.
  await expect(page).toHaveURL(/\/apply\/confirmation/);
  await expect(page.getByText('Antrag eingegangen')).toBeVisible();
});
