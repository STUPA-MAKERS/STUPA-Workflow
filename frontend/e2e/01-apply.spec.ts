import { expect, test } from '@playwright/test';
import { uniqueEmail } from './helpers';

/**
 * Scenario 1 (part): the public apply wizard against the real stack (testing.md
 * §3.1). The test drives the wizard through ALL steps to the review summary. The
 * steps are application type, contact, the dynamic form of the seeded form version,
 * and review. The test then checks that the summary shows the entered values.
 *
 * The final click on `Antrag absenden` is not part of the assertion, on purpose.
 * The frontend ALTCHA component is a stub. It emits `altcha-stub-solution`, and the
 * backend schema `AltchaSolutionStr` rejects that value with 422 as a malformed
 * altcha solution. The real captcha wiring is a separate task, see
 * deploy/docker-compose.yml. The UI submit is therefore blocked independent of T-40
 * (issue #111). `02-magic-link-flow.spec.ts` covers the real application creation
 * and the follow-up journey: magic link, edit, flow, and read-only.
 */
test('@gating öffentlicher Apply-Wizard: alle Schritte bis Review-Zusammenfassung', async ({
  page,
}) => {
  const email = uniqueEmail('apply');
  await page.goto('/apply');
  await expect(page.getByRole('heading', { name: 'Antrag stellen' })).toBeVisible();

  // Step 1: pick the application type. The first radio is the first type.
  await page.getByRole('radio').first().click();
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Step 2: contact. The email address is mandatory.
  await page.locator('input[type="email"]').fill(email);
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Step 3: fields of the seeded form version. The field `titel` is mandatory.
  await page.locator('formly-form input[type="text"]').first().fill('E2E Testantrag');
  await page.getByRole('button', { name: 'Weiter' }).click();

  await expect(page.getByRole('heading', { name: 'Prüfen & Absenden' })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await expect(page.getByText('E2E Testantrag')).toBeVisible();
  // The submit button exists, so the wizard is complete. The doc comment above tells
  // why the test does not click it.
  await expect(page.getByRole('button', { name: 'Antrag absenden' })).toBeVisible();
});
