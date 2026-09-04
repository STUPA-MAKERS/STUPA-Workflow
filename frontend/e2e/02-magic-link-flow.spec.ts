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
 * Scenarios 1 and 2 (testing.md §3): magic-link edit, flow run, and read-only in the
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
 * NOTE (documented in the PR): the backend mail links to `/antrag/<id>#t=<token>`,
 * but the frontend reads the token on `/status?t=…&app=…`. This route and fragment
 * mismatch is a defect that this work found. The test covers the magic-link
 * *capability* over the path that the frontend supports. A separate bugfix task
 * holds the real link landing. It is not part of T-40.
 */
test('@gating Magic-Link bearbeiten → Flow-Transition → read-only', async ({ browser, request }) => {
  const art = readArtifacts();
  const email = uniqueEmail('antrag');

  // 1) Create the application and request a magic link. Unauthenticated, so no CSRF.
  const appId = await createApplication(request, {
    typeId: art.typeId,
    email,
    title: 'Magic-Link Antrag',
  });
  await requestMagicLink(request, { email, applicationId: appId });
  const token = await fetchMagicLinkToken(request, email);

  // 2) Applicant context: redeem the token and check that the application is editable.
  const applicant = await browser.newContext();
  const ap = await applicant.newPage();
  await ap.goto(`/status?t=${token}&app=${appId}`);
  await expect(ap.getByRole('heading', { name: 'Antragsstatus' })).toBeVisible();
  await expect(ap.locator('ol.timeline')).toBeVisible();
  await expect(ap.getByRole('button', { name: 'Änderungen speichern' })).toBeVisible();

  // 3) Admin context: move the application to review with a flow transition.
  const admin = await browser.newContext({ storageState: ADMIN_STATE });
  const ad = await admin.newPage();
  await ad.goto(`/applications/${appId}`);
  await expect(ad.getByRole('button', { name: 'Zur Prüfung' })).toBeVisible();
  // A transition fires straight from its own button — `fire(t)` posts and reloads. The
  // confirmation dialog this used to click through ("Ausführen", with an optional note)
  // is gone; waiting for it hung the whole test until the 60s budget ran out, which read
  // as a magic-link failure rather than as the one obsolete step it was.
  await ad.getByRole('button', { name: 'Zur Prüfung' }).click();
  await expect(ad.getByText('In Prüfung')).toBeVisible();

  // 4) The applicant loads again with the cookie session. The view is now read-only.
  await ap.goto(`/status?app=${appId}`);
  await expect(ap.getByText('Gesperrt')).toBeVisible();
  await expect(ap.getByRole('button', { name: 'Änderungen speichern' })).toHaveCount(0);

  await applicant.close();
  await admin.close();
});
