/**
 * Contract of the pages with tabs on a phone. The line under the tabs runs over the page
 * gutter to the screen edges, as on the boards, and a sideways swipe over the panels
 * changes the tab (`appSwipeTabs` of the kit). jsdom does no layout, so this spec reads
 * the sources.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const app = join(__dirname, '..');
const read = (path: string): string => readFileSync(join(app, path), 'utf8');

const PAGES: [base: string, handler: string][] = [
  ['pages/applications/applications-detail.component', 'selectTab'],
  ['pages/tickets/ticket-detail.component', 'selectTab'],
  ['features/gremien/gremium-detail/gremium-detail.component', 'selectTab'],
  ['pages/dashboard/dashboard.component', 'setTab'],
];

describe('the pages with tabs on a phone', () => {
  it.each(PAGES)('%s changes the tab with a swipe', (base, handler) => {
    const html = read(`${base}.html`);
    expect(html).toContain('[appSwipeTabs]="tabs()"');
    expect(html).toContain('[appSwipeTabsActive]="tab()"');
    expect(html).toContain(`(appSwipeTabsActiveChange)="${handler}($event)"`);
  });

  it.each(PAGES)('%s runs the tab line to the screen edges', (base) => {
    expect(read(`${base}.scss`)).toMatch(/__(tabs|tabbar) \{\s*margin-inline: calc\(-1 \* var\(--space-4\)\);/);
  });

  it('runs the rule under the head of the application and the ticket to the edges too', () => {
    for (const [base] of PAGES.slice(0, 2)) {
      expect(read(`${base}.scss`)).toMatch(/__head \{\s*margin-inline: calc\(-1 \* var\(--space-4\)\);\s*padding-inline: var\(--space-4\);/);
    }
  });
});
