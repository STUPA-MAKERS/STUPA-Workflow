import { de, en } from './translations';

/**
 * Catalog parity.
 *
 * The `en` catalog has the type `Partial` because a missing key falls back to DE
 * at runtime. The compiler therefore does not catch drift. This test checks that
 * both locales carry the same key set. No string then stays in one language only.
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
