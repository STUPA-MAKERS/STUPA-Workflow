import { de, en } from './translations';

/**
 * Catalog-Parity: `en` ist als `Partial` typisiert (fehlende Keys fallen zur
 * Laufzeit auf DE zurück) — der Compiler fängt Drift also nicht. Dieser Test
 * stellt sicher, dass beide Locales exakt dieselbe Key-Menge führen, damit kein
 * String unbemerkt nur in einer Sprache existiert.
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
