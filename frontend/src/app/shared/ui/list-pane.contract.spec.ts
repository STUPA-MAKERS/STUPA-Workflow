/**
 * One set of rules for the list pane pages (`_list-pane.scss`).
 *
 * The lists of applications, bookings, invoices, tasks, votes, tickets, meetings and
 * gremien each had a copy of the column, the chips, the scroll area, the groups and the
 * row menu. A scroll area is cut at its edges, never faded. jsdom applies no styles, so
 * this spec reads the sources.
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
  it.each(PAGES)('%s takes the scroll area and the groups from the list pane', (scss) => {
    const src = read(scss);
    expect(src).toMatch(/@use '[./]+\/shared\/ui\/list-pane' as lp;/);
    expect(src).toContain('@include lp.scroll;');
    expect(src).toContain('@include lp.split-scroll;');
    expect(src).toContain('@include lp.stack;');
  });

  it.each(PAGES)('%s does not fade the rows or the chips', (scss) => {
    const src = read(scss);
    expect(src).not.toMatch(/fade\.fade-|mask-image/);
  });

  it('shares the row menu of the applications, the bookings and the invoices', () => {
    for (const [scss, block] of PAGES.slice(0, 3)) {
      expect(read(scss)).toContain(`@include lp.hover-menu(${block});`);
      expect(read(scss)).not.toContain(`.${block}__menuSlot {`);
    }
  });

  it('cuts the phone chips at the screen edges, not at the gutter', () => {
    const pane = read('shared/ui/_list-pane.scss');
    expect(pane).not.toContain('scroll-fade');
    expect(pane).toMatch(/@mixin phone-chips \{[^}]*margin-inline: calc\(-1 \* var\(--space-4\)\);/);
  });
});
