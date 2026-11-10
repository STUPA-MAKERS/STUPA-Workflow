import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * § 000634: a record row of Verwaltung has the anatomy of the shared record row. The page
 * sets no inset and no height for the row and no font for its title.
 */
const LISTS = [
  { name: 'oauth-grants/oauth-grants.component', row: 'og__row', title: 'og__name' },
  { name: 'delegations/delegations.component', row: 'dl__row', title: 'dl__title' },
  { name: 'delegations/substitute-pool.component', row: 'sp__row', title: 'sp__member' },
  { name: 'committees/gremium-members.component', row: 'gmm__row', title: 'gmm__name' },
  { name: 'cd-variants/cd-variants.component', row: 'cdv__variant', title: 'cdv__name' },
  { name: 'help-tickets/help-tickets.component', row: 'ht__row', title: 'ht__name' },
];

const read = (rel: string): string => readFileSync(join(__dirname, rel), 'utf8');

/** The declarations of every rule whose selector ends with `selector`. */
function declarationsOf(scss: string, selector: string): string {
  const escaped = selector.replace(/[.\s]/g, (c) => (c === '.' ? '\\.' : '\\s+'));
  const rule = new RegExp(`\\.${escaped}\\s*\\{([^{}]*)\\}`, 'g');
  return [...scss.matchAll(rule)].map((m) => m[1]).join('\n');
}

describe('AdminRecordRows', () => {
  it.each(LISTS)('$name lists its records in the shared record row group', ({ name }) => {
    const html = read(`${name}.html`);
    expect(html).toMatch(/class="rowgroup rowgroup--records\b/);
    expect(html).toMatch(/\browgroup__title\b/);
  });

  it.each(LISTS)('$name sets no inset or height for the row and no font for the title', ({ name, row, title }) => {
    const scss = read(`${name}.scss`);
    expect(declarationsOf(scss, row)).not.toMatch(/(^|\s)(padding|padding-inline|min-height)\s*:/);
    expect(declarationsOf(scss, title)).not.toMatch(/(^|\s)(font|font-size|font-weight|color)\s*:/);
  });
});
