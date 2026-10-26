import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { de } from './translations';
import { en } from './translations.en';

/**
 * The backend keeps a copy of the key catalog: every key with its built-in DE text and,
 * where one exists, its EN text. The server refuses an override for a key that the
 * catalog lacks and an override whose placeholders differ from the DE text, and it
 * serves the built-in texts to an admin who translates. This spec fails when the copy
 * is stale.
 *
 * Regenerate the copy after a change to the DE or the EN catalog:
 * `UPDATE_I18N_CATALOG=1 npx jest src/app/core/i18n/translations.catalog.spec.ts`.
 */
const FILE = resolve(__dirname, '../../../../../backend/app/modules/translations/catalog.json');

function render(): string {
  const keys = Object.keys(de).sort() as (keyof typeof de)[];
  const lines = keys.map((key) => {
    const entry: { de: string; en?: string } = { de: de[key] };
    const english = en[key];
    if (english !== undefined) entry.en = english;
    return `  ${JSON.stringify(key)}: ${JSON.stringify(entry)}`;
  });
  return `{\n${lines.join(',\n')}\n}\n`;
}

describe('backend key catalog', () => {
  it('matches the DE and the EN catalog', () => {
    const expected = render();
    if (process.env['UPDATE_I18N_CATALOG']) writeFileSync(FILE, expected);
    expect(readFileSync(FILE, 'utf8')).toBe(expected);
  });
});
