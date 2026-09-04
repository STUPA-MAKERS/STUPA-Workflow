import { expect, test } from '@playwright/test';
import { ADMIN_STATE } from './global-setup';

test.use({ storageState: ADMIN_STATE });

/**
 * Budget view (testing.md §3): the admin opens the budget tree and sees real cost
 * centres, served from the database over the budget API.
 *
 * This scenario used to open `/budget/pots` and look for the seeded `BudgetPot` named
 * "E2E-Topf". All three of those moved:
 *
 *  - the page is `/admin/budget-pots` and its heading is "Budgets & Kostenstellen";
 *  - it renders through the shared `app-data-table`, so `table.pots__table` is gone;
 *  - it lists cost centres (`Budget`), which is a different model from `BudgetPot`.
 *    `BudgetPot` now survives only to carry extra form fields (forms/service.py). It
 *    has no route and no page, so the seeded pot cannot appear here at all.
 *
 * The assertion therefore moves to a cost centre that every deployment has: migration
 * `0002_seed` ships the default budgets VS-Mittel and QS-Mittel. That is a firmer
 * fixture than a seeded one — it is part of the schema rather than of this suite.
 */
test('@gating Admin Budget-Sicht zeigt Kostenstellen aus der Datenbank', async ({ page }) => {
  await page.goto('/admin/budget-pots');
  await expect(page.getByRole('heading', { name: 'Budgets & Kostenstellen' })).toBeVisible();

  await expect(page.locator('table.dt__table')).toContainText('QS-Mittel');
});
