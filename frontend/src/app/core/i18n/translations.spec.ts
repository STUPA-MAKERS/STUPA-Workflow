import { de, en } from './translations';

/**
 * Catalog parity: `en` is typed as `Partial` (missing keys fall back to DE at
 * runtime) — so the compiler does not catch drift. This test ensures both
 * locales carry exactly the same key set, so no string exists unnoticed in only
 * one language.
 */
describe('translation catalog parity', () => {
  const deKeys = Object.keys(de).sort();
  const enKeys = Object.keys(en).sort();

  it('has identical key sets for DE and EN', () => {
    const missingInEn = deKeys.filter((k) => !(k in en));
    const extraInEn = enKeys.filter((k) => !(k in de));
    expect(missingInEn).toEqual([]);
    expect(extraInEn).toEqual([]);
  });

  it('has no empty translations', () => {
    for (const [key, value] of [...Object.entries(de), ...Object.entries(en)]) {
      expect(`${key}=${(value ?? '').trim()}`).not.toBe(`${key}=`);
    }
  });
});
