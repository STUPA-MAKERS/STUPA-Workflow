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
 * Szenarien 1 + 2 (testing.md §3): Magic-Link-Bearbeitung + Flow-Durchlauf +
 * Read-only im gesperrten Status. Bündelt drei Kern-Journeys in einem
 * deterministischen Ablauf gegen den echten Stack:
 *
 *  1. Antrag anlegen (API) → Magic-Link anfordern → Token aus mailpit (echtes SMTP-
 *     Sink) → /status öffnen → Antrag ist bearbeitbar (Initialstatus `entwurf`).
 *  2. Admin (geseedete Session) schaltet den Antrag via Flow-Transition nach
 *     `pruefung` (edit_allowed=false).
 *  3. Applicant lädt erneut → Antrag ist read-only/gesperrt.
 *
 * HINWEIS (in PR dokumentiert): die BE-Mail verlinkt `/antrag/<id>#t=<token>`,
 * das FE konsumiert den Token jedoch auf `/status?t=…&app=…`. Diese Route-/Fragment-
 * Diskrepanz ist ein gefundener Defekt; der Test deckt die Magic-Link-*Fähigkeit*
 * über den vom FE unterstützten Pfad ab. Die echte Link-Landing ist als Bugfix-Task
 * ausgelagert (nicht Teil von T-40).
 */
test('@gating Magic-Link bearbeiten → Flow-Transition → read-only', async ({ browser, request }) => {
  const art = readArtifacts();
  const email = uniqueEmail('antrag');

  // 1) Antrag anlegen + Magic-Link anfordern (unauth, CSRF-frei).
  const appId = await createApplication(request, {
    typeId: art.typeId,
    email,
    title: 'Magic-Link Antrag',
  });
  await requestMagicLink(request, { email, applicationId: appId });
  const token = await fetchMagicLinkToken(request, email);

  // 2) Applicant-Kontext: Token einlösen, Bearbeitbarkeit prüfen.
  const applicant = await browser.newContext();
  const ap = await applicant.newPage();
  await ap.goto(`/status?t=${token}&app=${appId}`);
  await expect(ap.getByRole('heading', { name: 'Antragsstatus' })).toBeVisible();
  await expect(ap.locator('ol.timeline')).toBeVisible();
  // Bearbeitbar: Editier-Formular + Speichern-Button vorhanden.
  await expect(ap.getByRole('button', { name: 'Änderungen speichern' })).toBeVisible();

  // 3) Admin-Kontext: Antrag zur Prüfung schalten (Flow-Transition).
  const admin = await browser.newContext({ storageState: ADMIN_STATE });
  const ad = await admin.newPage();
  await ad.goto(`/applications/${appId}`);
  await expect(ad.getByRole('heading')).toBeVisible();
  await ad.getByRole('button', { name: 'Zur Prüfung' }).click();
  // Bestätigungsdialog → Ausführen.
  await ad.getByRole('button', { name: 'Ausführen' }).click();
  await expect(ad.getByText('In Prüfung')).toBeVisible();

  // 4) Applicant lädt erneut (Cookie-Session) → read-only/gesperrt.
  await ap.goto(`/status?app=${appId}`);
  await expect(ap.getByText('Gesperrt')).toBeVisible();
  await expect(ap.getByRole('button', { name: 'Änderungen speichern' })).toHaveCount(0);

  await applicant.close();
  await admin.close();
});
