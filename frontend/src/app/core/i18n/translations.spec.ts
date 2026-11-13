import { de } from './translations';
import { en } from './translations.en';

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

/** The German texts name the budget tree with the words of budget law. */
describe('BudgetTerms', () => {
  /** The areas whose texts keep "Budget": Antragsart, flow, permissions and token scopes. */
  const KEPT = /^(account\.scope\.|admin\.forms\.|admin\.form\.metric\.|admin\.flow\.|admin\.roles\.section\.)/;

  it('§F/finance/budget/000852: no German text outside the kept areas says "Budget", and none says "Stammplan"', () => {
    const texts = Object.entries(de).map(([key, value]) => [key, String(value).replace('Anträge ohne Budget', '')] as const);
    expect(texts.filter(([key, value]) => !KEPT.test(key) && /Budget/.test(value)).map(([key]) => key)).toEqual([]);
    expect(texts.filter(([, value]) => /Stammplan/.test(value)).map(([key]) => key)).toEqual([]);
    expect(en['budget.plan.version.base']).toBe('Budget plan');
  });
});
