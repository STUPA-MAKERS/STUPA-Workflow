import { expect, test } from '@playwright/test';
import { uniqueEmail } from './helpers';

/** A minimal PDF, so the server sniffs `application/pdf`. */
const PDF = Buffer.from(
  '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
    '2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n',
);

/**
 * Scenario 1 (part): the public apply wizard against the real stack (testing.md
 * §3.1). The test drives the wizard (board Antrag-stellen) through ALL steps to the
 * review: application type → "Angaben" (the dynamic form of the seeded form version
 * with a draft upload, Z4) → "Kontakt" → "Prüfen & absenden". It then checks that the
 * review shows the entered values and the uploaded file.
 *
 * The upload goes to `POST /apply/attachments` as a draft. The e2e stack runs without
 * ALTCHA and without ClamAV, so the file stays "In Prüfung". The final click on "Antrag
 * absenden" is not part of the assertion; `02-magic-link-flow.spec.ts` covers the real
 * application creation and the follow-up journey.
 */
test('@gating öffentlicher Apply-Wizard: alle Schritte bis Review-Zusammenfassung', async ({
  page,
}) => {
  const email = uniqueEmail('apply');
  await page.goto('/apply');
  await expect(page.getByRole('heading', { level: 1, name: 'Antrag stellen' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Antrags-Fortschritt' })).toBeVisible();

  // Step 1: pick the application type. The first radio is the first type.
  await page.getByRole('radio').first().click();
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Step 2: the fields of the seeded form version. The system field `title` is
  // mandatory; the file field takes a draft upload.
  await expect(page.getByRole('heading', { level: 2, name: 'Angaben zum Vorhaben' })).toBeVisible();
  await page.locator('formly-form input[type="text"]').first().fill('E2E Testantrag');
  await page
    .locator('app-draft-files input[type="file"]')
    .first()
    .setInputFiles({ name: 'Angebot.pdf', mimeType: 'application/pdf', buffer: PDF });
  await expect(page.locator('app-draft-files').getByText('Angebot.pdf').first()).toBeVisible();
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Step 3: contact. The email address is mandatory.
  await expect(page.getByRole('heading', { level: 2, name: 'Kontakt' })).toBeVisible();
  await page.locator('input[type="email"]').fill(email);
  await page.getByRole('button', { name: 'Weiter' }).click();

  // Step 4: the review shows the answers, the contact and the file.
  await expect(page.getByRole('heading', { level: 2, name: 'Prüfen & absenden' })).toBeVisible();
  const review = page.locator('.wz__review');
  await expect(review.getByText(email)).toBeVisible();
  await expect(review.getByText('E2E Testantrag')).toBeVisible();
  await expect(review.getByText('Angebot.pdf')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Antrag absenden' })).toBeVisible();
});
