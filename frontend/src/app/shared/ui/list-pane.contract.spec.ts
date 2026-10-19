/**
 * One set of rules for the list pane pages (`_list-pane.scss`) and one fade for a scroll
 * area (`_scroll-fade.scss`).
 *
 * The lists of applications, bookings, invoices, tasks, votes, tickets, meetings and
 * gremien each had a copy of the column, the chips, the scroll area with its fade, the
 * groups and the row menu. jsdom applies no styles, so this spec reads the sources.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '../..');
const read = (path: string) => readFileSync(join(APP, path), 'utf8');

const PAGES: [scss: string, block: string][] = [
  ['pages/applications/applications-list.component.scss', 'apps'],
  ['pages/expenses/expenses.component.scss', 'exp'],
  ['pages/invoices/invoices.component.scss', 'inv'],
  ['pages/tasks/tasks.component.scss', 'tasks'],
  ['features/voting/voting-page/voting.component.scss', 'vl'],
  ['pages/tickets/tickets.component.scss', 'tk'],
  ['features/meetings/meetings-list/meetings-list.component.scss', 'mtl'],
  ['features/gremien/gremien-page/gremien.component.scss', 'grl'],
];

describe('the list pane pages', () => {
  it.each(PAGES)('%s takes the scroll area and the groups from the list pane', (scss, block) => {
    const src = read(scss);
    expect(src).toMatch(/@use '[./]+\/shared\/ui\/list-pane' as lp;/);
    expect(src).toContain(`@include lp.scroll(--${block}-fade);`);
    expect(src).toContain(`@include lp.split-scroll(--${block}-fade);`);
    expect(src).toContain('@include lp.stack;');
  });

  it.each(PAGES)('%s spells out no fade of its own for the rows', (scss, block) => {
    const src = read(scss);
    expect(src).not.toContain(`.${block}__scroll.is-fade-start`);
    expect(src).toContain(`@include fade.fade-y(var(--${block}-fade));`);
  });

  it('shares the row menu of the applications, the bookings and the invoices', () => {
    for (const [scss, block] of PAGES.slice(0, 3)) {
      expect(read(scss)).toContain(`@include lp.hover-menu(${block});`);
      expect(read(scss)).not.toContain(`.${block}__menuSlot {`);
    }
  });

  it('keeps the fades in one partial, for the rows and for the chips', () => {
    const fade = read('shared/ui/_scroll-fade.scss');
    expect(fade).toContain('@mixin fade-y($size)');
    expect(fade).toContain('@mixin fade-x($size)');
    const pane = read('shared/ui/_list-pane.scss');
    expect(pane).toContain("@use 'scroll-fade' as fade;");
    expect(pane).toContain('@include fade.fade-x(var(#{$fade}));');
  });
});
