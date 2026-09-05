import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

// Admin specs run with the seeded admin session. They need no UI login and no Keycloak.
test.use({ storageState: ADMIN_STATE });

/**
 * Scenario 6 (testing.md §3.6): admin config. The editor adds a question and
 * **persists** a new form version.
 *
 * Proof of persistence: the success toast "Gespeichert." fires only on a 2xx from
 * `POST /admin/application-types/{id}/form-versions` (form-editor.component.ts). The
 * server therefore created the version. The editor does not load older versions back
 * into the UI, so the test cannot compare after a reload.
 *
 * What moved since this was written: `/admin/forms` is now the LIST of application
 * types, and the editor sits at `/admin/forms/{typeId}`. It was renamed from
 * form-builder to form-editor, fields became questions grouped in sections, the save
 * control is "Speichern", and the `[data-testid="form-json"]` mirror no longer
 * exists. The key and label inputs kept their labels.
 */
test('@gating Admin Form-Editor: Frage hinzufügen → Form-Version persistiert', async ({ page }) => {
  const art = readArtifacts();
  await page.goto(`/admin/forms/${art.typeId}`);

  const save = page.getByRole('button', { name: 'Speichern', exact: true });
  await expect(save).toBeVisible();

  // Wait for the question to EXIST before addressing it. `.last()` resolves against the
  // DOM as it is at that moment: Playwright waits for the element it finds to be
  // actionable, not for one more to appear. Filling too early wrote the key into the
  // previous question, so the new one kept an empty key, `formValid()` stayed false, and
  // the save button never enabled — a 60s wait that reads as a timeout, not as a race.
  const group = page.locator('.fe__group').first();
  const questions = group.locator('.fe__list > li');
  const before = await questions.count();

  await group.getByRole('button', { name: /Frage hinzufügen/ }).click();
  await page.getByRole('menuitem').first().click();
  await expect(questions).toHaveCount(before + 1);

  const question = questions.last();
  const key = `e2e_frage_${Date.now()}`;
  await question.getByRole('textbox', { name: 'Schlüssel' }).fill(key);
  await question.getByRole('textbox', { name: 'Bezeichnung (DE)' }).fill('E2E Frage');

  // `[disabled]="!formValid()"`. Assert the state, so a recurrence fails here in seconds
  // instead of inside a minute-long click.
  await expect(save).toBeEnabled();

  // The toast fires only on a 2xx from the server, so it proves persistence.
  await save.click();
  await expect(page.getByText('Gespeichert.')).toBeVisible();
});
