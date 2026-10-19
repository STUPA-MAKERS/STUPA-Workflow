/**
 * One head for every detail sheet (`.sheet-head` in `src/styles.scss`).
 *
 * The detail sheets of the meetings, the bookings, the transfers, the invoices, the
 * tickets, the applications and the to-dos each had a copy of the head rule (column,
 * gap, padding, rule) and two of them a copy of the way back to the list. jsdom applies
 * no styles, so this spec reads the sources.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '../..');
const read = (path: string) => readFileSync(join(APP, path), 'utf8');
const global = readFileSync(join(APP, '../styles.scss'), 'utf8');

const SHEETS: [html: string, scss: string, block: string][] = [
  ['features/meetings/meeting-detail-sheet/meeting-detail-sheet.component.html', 'features/meetings/meeting-detail-sheet/meeting-detail-sheet.component.scss', 'ms'],
  ['pages/expenses/booking-detail/booking-detail.component.html', 'pages/budget/_finance-sheet.scss', 'fd'],
  ['pages/expenses/transfer-detail/transfer-detail.component.html', 'pages/budget/_finance-sheet.scss', 'fd'],
  ['pages/invoices/invoice-detail/invoice-detail.component.html', 'pages/budget/_finance-sheet.scss', 'fd'],
  ['pages/tickets/ticket-detail.component.html', 'pages/tickets/ticket-detail.component.scss', 'td'],
  ['pages/applications/applications-detail.component.html', 'pages/applications/applications-detail.component.scss', 'ad'],
  ['features/todos/card-detail/todo-card-detail.component.html', 'features/todos/card-detail/todo-card-detail.component.scss', 'cd'],
];

describe('the head of a detail sheet', () => {
  it('is defined once, in styles.scss', () => {
    expect(global).toMatch(
      /\n\.sheet-head \{[^}]*gap: var\(--sheet-head-gap\);[^}]*border-bottom: var\(--border-width\) solid var\(--color-border\);/,
    );
    expect(global).toMatch(/\n\.sheet-back-link \{[^}]*border-radius: var\(--radius-pill\);/);
  });

  it.each(SHEETS)('%s uses the shared head and has no copy of it', (html, scss, block) => {
    expect(read(html)).toMatch(new RegExp(`<header class="sheet-head ${block}__head[\\s"]`));
    const own = read(scss).match(new RegExp(`\\.${block}__head \\{([^}]*)\\}`))?.[1] ?? '';
    expect(own).not.toContain('border-bottom');
    expect(own).not.toContain('padding-bottom');
  });

  it.each(['pages/tickets/ticket-detail.component', 'pages/applications/applications-detail.component'])(
    '%s uses the shared way back to the list',
    (base) => {
      expect(read(`${base}.html`)).toContain('class="sheet-back-link');
      expect(read(`${base}.scss`)).not.toMatch(/__backLink \{/);
    },
  );
});
