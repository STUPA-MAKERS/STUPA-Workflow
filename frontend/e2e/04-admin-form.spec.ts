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
 * exists. The key and label inputs kept their labels. Since the redesign (FE12b) the
 * questions are listed in an outline, and the card of the selected question holds the
 * fields.
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
  // The outline (left column) lists the questions of every group; "Frage hinzufügen"
  // under a group opens the menu of the question types.
  const outline = page.getByRole('navigation', { name: 'Fragen des Formulars' });
  const rows = outline.locator('.fe__list').first().locator(':scope > li');
  const before = await rows.count();

  await outline.getByRole('button', { name: /Frage hinzufügen/ }).first().click();
  await page.getByRole('menuitem').first().click();
  await expect(rows).toHaveCount(before + 1);

  // The new question is selected: its card in the middle column has the accent outline.
  const question = page.locator('article.fe__card--sel');
  await expect(question).toHaveAttribute('data-q', `0:${before}`);
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

/**
 * The admin frame (board Verwaltung): the admin navigation stands beside every admin page.
 * The home page lists the pages; a click opens one, and the navigation stays and marks it.
 * Desktop Chrome is 1280px wide, so the navigation is a column (from 1200px).
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
  // The settings search narrows the entries.
  await nav.getByRole('searchbox', { name: 'Einstellungen durchsuchen' }).fill('Kostenstellen');
  await expect(nav.getByRole('link')).toHaveCount(1);
  await nav.getByRole('link', { name: /Kostenstellen/ }).click();
  await expect(page).toHaveURL(/\/admin\/cost-centres$/);
});
