import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * §002690: every list page of Verwaltung is the records screen of the kit with the search of
 * Benutzer: an `app-search-pill` of size `md` with the × button and the count of hits in the
 * search slot, and no table.
 */
const PAGES = [
  'users/users.component',
  'roles/roles.component',
  'oauth-grants/oauth-grants.component',
  'committees/gremien.component',
  'committees/gremium-members.component',
  'committees/substitute-pool.component',
  'delegations/delegations.component',
  'budgets/admin-budgets.component',
  'calendars/calendars.component',
  'webhooks/webhooks.component',
  'cd-variants/cd-variants.component',
  'forced-status/forced-status.component',
  'audit/audit-log.component',
];

const read = (rel: string): string => readFileSync(join(__dirname, rel), 'utf8');

/** The markup of the search slot of a template. */
function searchSlot(html: string): string {
  const start = html.indexOf('<ng-template screenSearch>');
  if (start < 0) return '';
  return html.slice(start, html.indexOf('</ng-template>', start));
}

describe('adminListPages', () => {
  it.each(PAGES)('%s is a records screen with the search of Benutzer', (name) => {
    const html = read(`${name}.html`);
    expect(html.trimStart().startsWith('<app-records-screen')).toBe(true);
    const slot = searchSlot(html);
    expect(slot).toContain('role="search"');
    expect(slot).toContain('<app-search-pill');
    expect(slot).toContain('size="md"');
    expect(slot).toContain('[clearable]="true"');
    expect(slot).toMatch(/\[results\]="[^"]+"/);
    expect(html.slice(0, html.indexOf('</app-records-screen>'))).not.toContain('<app-data-table');
  });
});
