import { expect, test } from '@playwright/test';
import { uniqueEmail } from './helpers';

/**
 * Szenario 1 (Teil): öffentlicher Apply-Wizard gegen den echten Stack (testing.md
 * §3.1). Treibt den Wizard durch ALLE Schritte bis zur Review-Zusammenfassung
 * (Antragsart → Kontakt → dynamisches Formular der geseedeten Form-Version →
 * Prüfen) und verifiziert, dass die Eingaben korrekt zusammengefasst werden.
 *
 * Der finale „Antrag absenden"-Klick ist hier BEWUSST nicht Teil der Assertion:
 * die FE-ALTCHA-Komponente ist aktuell ein Stub (emittiert `altcha-stub-solution`,
 * reale Captcha-Wiring = eigener Task, siehe deploy/docker-compose.yml), dessen
 * Lösung das Backend-Schema `AltchaSolutionStr` strukturell als „malformed altcha
 * solution" mit 422 ablehnt. Der UI-Submit ist damit unabhängig von T-40 blockiert
 * (Issue #111). Die Antrags-*Erstellung* + Folge-Journey (Magic-Link → bearbeiten →
 * Flow → read-only) ist über `02-magic-link-flow.spec.ts` real abgedeckt.
 */
test('@gating öffentlicher Apply-Wizard: alle Schritte bis Review-Zusammenfassung', async ({
  page,
}) => {
  const email = uniqueEmail('apply');
  await page.goto('/apply');
  await expect(page.getByRole('heading', { name: 'Antrag stellen' })).toBeVisible();

  // Schritt 1: Antragsart wählen (erster Typ).
  await page.getByRole('radio').first().click();
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Schritt 2: Kontakt (E-Mail Pflicht).
  await page.locator('input[type="email"]').fill(email);
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Schritt 3: Formularfelder der geseedeten Form-Version (Pflichtfeld „titel").
  await page.locator('formly-form input[type="text"]').first().fill('E2E Testantrag');
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Review: Zusammenfassung spiegelt die echten Eingaben wider.
  await expect(page.getByRole('heading', { name: 'Prüfen & Absenden' })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await expect(page.getByText('E2E Testantrag')).toBeVisible();
  // Absenden-Button ist vorhanden (Wizard vollständig); Klick s. Doc-Kommentar oben.
  await expect(page.getByRole('button', { name: 'Antrag absenden' })).toBeVisible();
});
