/**
 * One layout for the form dialogs (`_dialog-form.scss`): a host without a box and a column
 * of fields 16px apart. The meeting dialogs used it; the decision, the agenda, the sub
 * booking, the to-do transfer and the report dialog had a copy. jsdom applies no styles,
 * so this spec reads the sources.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '../..');
const read = (path: string) => readFileSync(join(APP, path), 'utf8');

const DIALOGS: [scss: string, form: string][] = [
  ['features/todos/transfer-dialog/todo-transfer-dialog.component.scss', 'tt'],
  ['features/help/report-dialog/report-dialog.component.scss', 'rd'],
  ['pages/expenses/sub-booking-dialog/sub-booking-dialog.component.scss', 'sd-form'],
  ['pages/applications/agenda-dialog/agenda-dialog.component.scss', 'agd'],
  ['pages/applications/decision-dialog/decision-dialog.component.scss', 'ddg'],
];

describe('the form dialogs', () => {
  it('keep the layout in one partial', () => {
    const df = read('shared/ui/_dialog-form.scss');
    expect(df).toMatch(/@mixin host \{\s*:host \{\s*display: contents;/);
    expect(df).toMatch(/@mixin form \{[^}]*gap: var\(--space-4\);/);
  });

  it.each(DIALOGS)('%s takes the host and the form from it', (scss, form) => {
    const src = read(scss);
    expect(src).toMatch(/@use '[./]+\/shared\/ui\/dialog-form' as df;/);
    expect(src).toContain('@include df.host;');
    expect(src).toContain(`.${form} {\n  @include df.form;\n}`);
    expect(src).not.toMatch(/^:host \{/m);
  });
});
