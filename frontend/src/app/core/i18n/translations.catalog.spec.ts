import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { placeholdersOf } from './placeholders';
import { de } from './translations';

/**
 * The backend keeps a copy of the key catalog: every key with its placeholders. The
 * server refuses an override for a key that the catalog lacks and an override whose
 * placeholders differ from the default. This spec fails when the copy is stale.
 *
 * Regenerate the copy after a change to the DE catalog:
 * `UPDATE_I18N_CATALOG=1 npx jest src/app/core/i18n/translations.catalog.spec.ts`.
 */
const FILE = resolve(__dirname, '../../../../../backend/app/modules/translations/catalog.json');

function render(): string {
  const keys = Object.keys(de).sort();
  const lines = keys.map((key) => `  ${JSON.stringify(key)}: ${JSON.stringify(placeholdersOf(de[key as keyof typeof de]))}`);
  return `{\n${lines.join(',\n')}\n}\n`;
}

describe('backend key catalog', () => {
  it('matches the DE catalog', () => {
    const expected = render();
    if (process.env['UPDATE_I18N_CATALOG']) writeFileSync(FILE, expected);
    expect(readFileSync(FILE, 'utf8')).toBe(expected);
  });
});
