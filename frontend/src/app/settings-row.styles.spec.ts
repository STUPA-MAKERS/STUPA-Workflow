import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * § 000631: a settings row is a child of the shared settings row group. The stylesheet of
 * the page sets no height, surface or corners for the row.
 */
const PAGES = [
  { name: 'pages/admin/notifications/notification-settings.component', row: 'ns__row' },
  { name: 'pages/admin/help-tickets/help-tickets.component', row: 'ht__row' },
  { name: 'pages/account/notifications.component', row: 'nt__row' },
];

const read = (rel: string): string => readFileSync(join(__dirname, rel), 'utf8');

/** The declarations of every rule whose selector names the class `row`. */
function declarationsOf(scss: string, row: string): string {
  const rule = new RegExp(`[^{}]*\\.${row}\\b[^{}]*\\{([^{}]*)\\}`, 'g');
  return [...scss.matchAll(rule)].map((m) => m[1]).join('\n');
}

describe('SettingsRows', () => {
  it.each(PAGES)('$name lists its settings in the shared settings row group', ({ name }) => {
    expect(read(`${name}.html`)).toMatch(/class="rowgroup rowgroup--settings\b/);
  });

  it.each(PAGES)('$name sets no height, surface or corners for the row', ({ name, row }) => {
    const rules = declarationsOf(read(`${name}.scss`), row);
    expect(rules).not.toMatch(/min-height|background|border-radius/);
  });
});
