import type { FormFieldDef } from '@core/api/models';
import { formatAnswer, isEmptyAnswer } from './answer-format';
import { normalizePositions, positionValue, positionsTotal, preferredOffer } from './positions';

const env = { lang: 'de', yes: 'Ja', no: 'Nein' };
const f = (type: FormFieldDef['type'], extra: Partial<FormFieldDef> = {}): FormFieldDef => ({
  key: 'k',
  type,
  label: { de: 'K' },
  ...extra,
});

describe('answer-format', () => {
  it('knows an empty answer from a given one', () => {
    for (const v of [null, undefined, '', '  ', [], {}, { from: '', to: null }]) {
      expect(isEmptyAnswer(v)).toBe(true);
    }
    for (const v of [0, false, 'x', [1], { from: '2026-01-01' }]) {
      expect(isEmptyAnswer(v)).toBe(false);
    }
  });

  it('formats a currency answer as euro and keeps what is no number', () => {
    expect(formatAnswer(f('currency'), 12.5, env).replace(/\s/g, ' ')).toBe('12,50 €');
    expect(formatAnswer(f('currency'), '3', { ...env, lang: 'en' })).toBe('€3.00');
    expect(formatAnswer(f('currency'), 'abc', env)).toBe('abc');
    expect(formatAnswer(f('currency'), true, env)).toBe('true');
  });

  it('formats a computed amount as euro and another computed value as is (spec 002842)', () => {
    const amount = f('computed', { isPromoted: true, promoteTarget: 'amount' });
    expect(formatAnswer(amount, 29.4, env).replace(/\s/g, ' ')).toBe('29,40 €');
    expect(formatAnswer(amount, 29.4, { ...env, lang: 'en' })).toBe('€29.40');
    expect(formatAnswer(amount, 'abc', env)).toBe('abc');
    expect(formatAnswer(f('computed'), 29.4, env)).toBe('29.4');
  });

  it('formats the requested funding in euro like a currency field', () => {
    expect(formatAnswer(f('funding'), 600, env)).toBe(formatAnswer(f('currency'), 600, env));
  });

  it('gives an empty answer as an empty string, whatever the type', () => {
    expect(formatAnswer(f('currency'), '', env)).toBe('');
  });

  it('keeps the text of a type without its own format, and of a broken select', () => {
    expect(formatAnswer(f('text'), 42, env)).toBe('42');
    expect(formatAnswer(f('select'), 'x', env)).toBe('x');
    expect(formatAnswer(f('select', { options: [{ value: 'x', label: { en: 'Only EN' } }] }), 'x', env)).toBe(
      'Only EN',
    );
  });
});

describe('positions', () => {
  it('reads broken answers without throwing', () => {
    expect(normalizePositions('x')).toEqual([]);
    expect(
      normalizePositions([
        null,
        { label: 3, offers: [{ label: 'A', value: '12.5', preferred: true }, null, { value: true }] },
      ]),
    ).toEqual([
      {
        label: '',
        offers: [
          { label: 'A', value: 12.5, preferred: true },
          { label: '', value: null, preferred: false },
        ],
        noOffers: false,
        noOffersReason: '',
      },
    ]);
  });

  it('keeps the id of a position', () => {
    expect(normalizePositions([{ id: 'p-1', label: 'A', offers: [] }])[0].id).toBe('p-1');
    expect(normalizePositions([{ id: 3, label: 'A', offers: [] }])[0].id).toBeUndefined();
  });

  it('takes the value of a position from its preferred offer', () => {
    const p = { offers: [{ label: 'A', value: 5, preferred: false }, { label: 'B', value: 7, preferred: true }] };
    expect(preferredOffer(p)?.label).toBe('B');
    expect(positionValue(p)).toBe(7);
    expect(positionValue({ offers: [{ label: 'A', value: null, preferred: true }] })).toBe(0);
    expect(positionsTotal([p, { offers: [] }])).toBe(7);
  });
});
