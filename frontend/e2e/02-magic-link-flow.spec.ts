import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import {
  createApplication,
  fetchMagicLinkToken,
  readArtifacts,
  requestMagicLink,
  uniqueEmail,
} from './helpers';

/**
 * Scenarios 1 and 2: magic-link edit, flow run, and read-only in the
 * locked status. The test bundles three core journeys into one deterministic run
 * against the real stack:
 *
 *  1. Create the application over the API. Request a magic link. Read the token from
 *     mailpit, a real SMTP sink. Open /status. The application is editable in the
 *     initial status `entwurf`.
 *  2. The admin (seeded session) moves the application to `pruefung` with a flow
 *     transition (edit_allowed=false).
 *  3. The applicant loads the page again. The application is read-only and locked.
 *
 * The test opens the magic link over `/status?t=…&app=…`, with the token pulled from
 * mailpit.
 * The magic-link request is unauthenticated, so it needs no CSRF token. The page shows the list
 * beside the detail. The detail is the article of the open application, so the checks look there
 * and not at its row in the list. A transition fires straight from its own button: `fire(t)` posts
 * and reloads. There is no confirmation dialog, and a wait for one hangs the test until the 60 s
 * budget runs out. The applicant then loads again with the cookie session, and the view is
 * read-only.
 */
test('@gating Magic-Link bearbeiten → Flow-Transition → read-only', async ({ browser, request }) => {
  const art = readArtifacts();
  const email = uniqueEmail('antrag');

  const appId = await createApplication(request, {
    typeId: art.typeId,
    email,
    title: 'Magic-Link Antrag',
  });
  await requestMagicLink(request, { email, applicationId: appId });
  const token = await fetchMagicLinkToken(request, email);

  const applicant = await browser.newContext();
  const ap = await applicant.newPage();
  await ap.goto(`/status?t=${token}&app=${appId}`);
  await expect(ap.getByRole('heading', { level: 1, name: 'Magic-Link Antrag' })).toBeVisible();
  await expect(ap.getByRole('heading', { name: 'Verlauf' })).toBeVisible();
  await expect(ap.getByRole('button', { name: /Angaben bearbeiten/ })).toBeEnabled();

  const admin = await browser.newContext({ storageState: ADMIN_STATE });
  const ad = await admin.newPage();
  await ad.goto(`/applications/${appId}`);
  const detail = ad.locator('app-applications-detail');
  await expect(detail.getByRole('button', { name: 'Zur Prüfung' })).toBeVisible();
  await detail.getByRole('button', { name: 'Zur Prüfung' }).click();
  await expect(detail.locator('.ad__line').getByText('In Prüfung')).toBeVisible();

  await ap.goto(`/status?app=${appId}`);
  await expect(ap.getByText('Im aktuellen Status gesperrt')).toBeVisible();
  await expect(ap.getByRole('button', { name: /Angaben bearbeiten/ })).toBeDisabled();

  await applicant.close();
  await admin.close();
});
