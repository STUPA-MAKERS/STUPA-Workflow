/**
 * App spec 000598: with "Eingabefelder hervorheben" every input field is black on yellow.
 * Fields outside the kit field box draw their own surface, so each one reads the field
 * tokens. jsdom applies no component styles, so this spec reads the stylesheets.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '..');

const FIELDS: readonly (readonly [string, string])[] = [
  ['shared/formly/types/formly-positions.type.scss', '.pf'],
  ['shared/ui/chat/chat.component.scss', '.chat__editInput'],
  ['features/todos/card-detail/todo-card-detail.component.scss', '.cd__itemInput'],
  ['features/todos/card-detail/todo-card-detail.component.scss', '.cd__evInput'],
  ['features/meetings/top-sheet/top-sheet.component.scss', '.ts__titleInput'],
  ['features/meetings/agenda-pane/agenda-pane.component.scss', '.ap__input'],
  ['pages/admin/privacy/privacy.component.scss', '.pv__textarea'],
  ['pages/todos/board-settings/todo-board-settings.component.scss', '.bs__input'],
  ['pages/budget/cost-centre-select/cost-centre-select.component.scss', '.ccs__search'],
  ['pages/admin/mail-templates/mail-templates.component.scss', '.mt__area'],
  ['pages/admin/branding/branding-editor.component.scss', '.br__area'],
  ['pages/budget/budget-tree.component.scss', '.bt__numField'],
  ['pages/applications/force-status-dialog/force-status-dialog.component.scss', 'textarea'],
];

/** The declarations of every rule whose selector line is this selector. */
function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const all = [...css.matchAll(new RegExp(`(?:^|\\n)\\s*${esc} \\{([^}]*)\\}`, 'g'))];
  if (all.length === 0) throw new Error(`No rule ${selector}`);
  return all.map((m) => m[1]).join('\n');
}

const SURFACES: readonly (readonly [string, string])[] = [
  ['shared/ui/chat/chat.component.scss', '.chat__box'],
  ['features/todos/card-detail/todo-card-detail.component.scss', '.cd__area'],
  ['features/todos/link-picker/todo-link-picker.component.scss', '.lp__search'],
  ['pages/todos/board-view/todo-board-view.component.scss', '.bv__quick'],
  ['pages/applications/agenda-dialog/agenda-dialog.component.scss', '.agd__note'],
  ['pages/admin/gremien/gremium-dialog/gremium-dialog.component.scss', '.gd__mail'],
  ['features/meetings/attendance-sheet/attendance-sheet.component.scss', '.as__note'],
  ['pages/admin/forms/form-editor.component.scss', '.fe__pv-control'],
  ['pages/dashboard/dashboard.component.scss', '.dash__btn--fill'],
  ['pages/todos/board-picker/todo-board-picker.component.scss', '.bp__chip'],
  ['layout/public-header/public-header.component.scss', '.pub__icon'],
  ['features/help/help-menu/help-menu.component.scss', '.hm__head'],
  ['features/meetings/top-sheet/top-sheet.component.scss', '.ts__editor:not(.ts__editor--wait)'],
];

describe('highlightedFields (§000598)', () => {
  it.each(SURFACES)('%s %s includes the highlight surface', (file, selector) => {
    const body = rule(readFileSync(join(APP, file), 'utf8'), selector);
    expect(body).toMatch(/@include f\.highlight-surface;/);
  });

  it('the board picker paints the chosen row black on yellow', () => {
    const css = readFileSync(
      join(APP, 'pages/todos/board-picker/todo-board-picker.component.scss'),
      'utf8',
    );
    expect(rule(css, ".bp__row[aria-current='true']")).toMatch(/@include f\.highlight-chosen;/);
  });

  it.each([
    [
      'pages/budget/cost-centre-select/cost-centre-select.component.scss',
      ".ccs__opt[aria-selected='true']",
    ],
    ['features/todos/move-sheet/todo-move-sheet.component.scss', '.ms__row--on'],
    ['features/todos/link-picker/todo-link-picker.component.scss', '.lp__hit--on'],
    ['features/todos/pick-dialog/todo-pick-dialog.component.scss', '.pd__row--on'],
    [
      'features/meetings/handover-dialog/handover-dialog.component.scss',
      '.rowgroup.rowgroup--bg3 > .hd__mode--on',
    ],
    ['features/meetings/delegation-dialog/delegation-dialog.component.scss', '.dd__row--on'],
    ['features/meetings/agenda-item-dialog/agenda-item-dialog.component.scss', '.aid__row--on'],
    ['pages/budget/budget-dashboard.component.scss', '.tn--on'],
    ['pages/admin/admin-frame/admin-frame.component.scss', '.af__item--on'],
    ['pages/admin/forms/form-editor.component.scss', '.fe__row--on'],
    ['pages/applications/agenda-dialog/agenda-dialog.component.scss', '.agd__row--on'],
    ['features/meetings/attendance-sheet/attendance-sheet.component.scss', '.as__opt--on'],
    ['features/apply/apply-wizard.component.scss', '.wz__type.is-selected'],
    ['features/voting/ballot/ballot.component.scss', '.choice--on'],
    ['features/voting/ballot/ballot.component.scss', '.pchoice--on'],
    ['features/public-meeting/guest-view.component.scss', '.gv__item--now'],
  ])('%s %s paints the chosen row black on yellow', (file, selector) => {
    const body = rule(readFileSync(join(APP, file), 'utf8'), selector);
    expect(body).toMatch(/@include f\.highlight-chosen;/);
  });

  it.each([
    ['features/apply/apply-wizard.component.scss', '.wz__radio'],
    ['pages/admin/gremium-roles/gremium-role-matrix.component.scss', '.rm__box'],
  ])('%s %s covers its outer rim with the black ring', (file, selector) => {
    const body = rule(readFileSync(join(APP, file), 'utf8'), selector);
    expect(body).toMatch(/@include f\.ring;/);
  });

  it('the role matrix check box reads the check tokens', () => {
    const css = readFileSync(
      join(APP, 'pages/admin/gremium-roles/gremium-role-matrix.component.scss'),
      'utf8',
    );
    expect(css).toContain('var(--check-on, var(--color-accent))');
  });

  it('the public protocol pill buttons include the highlight surface', () => {
    const css = readFileSync(
      join(APP, 'features/public-protocols/_public-protocols.shared.scss'),
      'utf8',
    );
    expect(css).toMatch(/@mixin pill-button[\s\S]*@include f\.highlight-surface;/);
  });

  it.each(FIELDS)('%s %s reads the yellow field tokens', (file, selector) => {
    const body = rule(readFileSync(join(APP, file), 'utf8'), selector);
    expect(body).toMatch(/background: var\(--field-bg, /);
  });

  it('the TOP badge in a chosen row is a black ring, the current one black with a yellow number', () => {
    const css = readFileSync(join(APP, 'features/meetings/top-badge/top-badge.component.scss'), 'utf8');
    expect(css).toMatch(
      /:host-context\(:root\[data-fields='highlight'\] \.li--on\) \{[^}]*border: 2px solid var\(--field-text\);/,
    );
    expect(css).toMatch(/\.tb--now \{\s*background: var\(--field-text\);\s*color: var\(--field-bg\);/);
  });
});
