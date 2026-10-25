import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';
import { readArtifacts } from './helpers';

/** Admin specs run with the seeded admin session. They need no UI login and no Keycloak. */
test.use({ storageState: ADMIN_STATE });

/**
 * Scenario 6: admin config. The editor adds a question and **persists** a new form version.
 *
 * Proof of persistence: the success toast "Gespeichert." fires only on a 2xx from
 * `POST /admin/application-types/{id}/form-versions` (form-editor.component.ts). The editor does
 * not load older versions back into the UI, so the test cannot compare after a reload.
 *
 * `/admin/forms` is the list of application types, and the editor sits at
 * `/admin/forms/{typeId}`. The outline (left column) lists the questions of every group, and
 * "Frage hinzufügen" under a group opens the menu of the question types. The card of the selected
 * question (accent outline, middle column) holds the fields. The save control is "Speichern".
 *
 * The test waits for the new question to exist before it addresses it, because `.last()` resolves
 * against the DOM as it is at that moment. Playwright waits for the found element to be actionable,
 * not for one more to appear. An early fill writes the key into the previous question, so the new
 * one keeps an empty key, `formValid()` stays false and the save button never enables. The test
 * asserts the `[disabled]="!formValid()"` state, so a recurrence fails in seconds instead of inside
 * a minute-long click.
 */
test('@gating Admin Form-Editor: Frage hinzufügen → Form-Version persistiert', async ({ page }) => {
  const art = readArtifacts();
  await page.goto(`/admin/forms/${art.typeId}`);

  const save = page.getByRole('button', { name: 'Speichern', exact: true });
  await expect(save).toBeVisible();

  const outline = page.getByRole('navigation', { name: 'Fragen des Formulars' });
  const rows = outline.locator('.fe__list').first().locator(':scope > li');
  const before = await rows.count();

  await outline.getByRole('button', { name: /Frage hinzufügen/ }).first().click();
  await page.getByRole('menuitem').first().click();
  await expect(rows).toHaveCount(before + 1);

  const question = page.locator('article.fe__card--sel');
  await expect(question).toHaveAttribute('data-q', `0:${before}`);
  const key = `e2e_frage_${Date.now()}`;
  await question.getByRole('textbox', { name: 'Schlüssel' }).fill(key);
  await question.getByRole('textbox', { name: 'Bezeichnung (DE)' }).fill('E2E Frage');

  await expect(save).toBeEnabled();

  await save.click();
  await expect(page.getByText('Gespeichert.')).toBeVisible();
});

/**
 * The admin frame (board Verwaltung): the admin navigation stands beside every admin page.
 * The home page lists the pages; a click opens one, and the navigation stays and marks it.
 * Desktop Chrome is 1280px wide, so the navigation is a column (from 1200px).
 * The settings search narrows the entries.
 */
test('Admin-Rahmen: über die Verwaltungsnavigation zur Formularliste', async ({ page }) => {
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: 'Verwaltung', level: 1 })).toBeVisible();
  const nav = page.getByRole('navigation', { name: 'Verwaltungsbereiche' });
  await nav.getByRole('link', { name: /Anträge & Formulare/ }).click();
  await expect(page).toHaveURL(/\/admin\/forms$/);
  await expect(nav.getByRole('link', { name: /Anträge & Formulare/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await nav.getByRole('searchbox', { name: 'Einstellungen durchsuchen' }).fill('Kostenstellen');
  await expect(nav.getByRole('link')).toHaveCount(1);
  await nav.getByRole('link', { name: /Kostenstellen/ }).click();
  await expect(page).toHaveURL(/\/admin\/cost-centres$/);
});
