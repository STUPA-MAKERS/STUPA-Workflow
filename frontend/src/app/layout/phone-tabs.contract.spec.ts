/**
 * Contract of the pages with tabs on a phone. They all take the tab pager of the kit
 * (`app-tab-pager`), as the boards do: a sideways swipe moves to the next tab and shows
 * its page beside the one that leaves, and the line under the tabs and the pages run over
 * the page gutter to the screen edges (`--tab-pager-bleed`). jsdom does no layout, so
 * this spec reads the sources.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const app = join(__dirname, '..');
const read = (path: string): string => readFileSync(join(app, path), 'utf8');

const PAGES: [base: string, paged: string, handler: string][] = [
  ['pages/applications/applications-detail.component', 'phone()', 'selectTab'],
  ['pages/tickets/ticket-detail.component', 'phone()', 'selectTab'],
  ['features/gremien/gremium-detail/gremium-detail.component', 'phone()', 'selectTab'],
  ['pages/dashboard/dashboard.component', 'true', 'setTab'],
  ['pages/todos/board-view/todo-board-view.component', 'true', 'selectPhoneColumn'],
];

describe('the pages with tabs on a phone', () => {
  it.each(PAGES)('%s pages its tabs with the tab pager', (base, paged, handler) => {
    const html = read(`${base}.html`);
    expect(html).toContain('<app-tab-pager');
    expect(html).toContain(`[paged]="${paged}"`);
    expect(html).toContain(`(activeChange)="${handler}($event)"`);
    expect(html).toContain('appTabPage');
  });

  it.each(PAGES)('%s runs the tabs and the pages to the screen edges', (base) => {
    expect(read(`${base}.scss`)).toMatch(/--tab-pager-bleed: var\(--(space-4|bv-gutter)\);/);
  });

  it('keeps no pager of its own on the board', () => {
    const ts = read('pages/todos/board-view/todo-board-view.component.ts');
    expect(ts).not.toContain('placeInk');
    expect(ts).not.toContain('scrollTo(');
  });

  it('runs the rule under the head of the application and the ticket to the edges too', () => {
    for (const [base] of PAGES.slice(0, 2)) {
      expect(read(`${base}.scss`)).toMatch(/__head \{\s*margin-inline: calc\(-1 \* var\(--space-4\)\);\s*padding-inline: var\(--space-4\);/);
    }
  });
});
