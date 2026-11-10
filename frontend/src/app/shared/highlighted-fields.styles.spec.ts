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

describe('highlightedFields (§000598)', () => {
  it.each(FIELDS)('%s %s reads the yellow field tokens', (file, selector) => {
    const body = rule(readFileSync(join(APP, file), 'utf8'), selector);
    expect(body).toMatch(/background: var\(--field-bg, /);
  });
});
