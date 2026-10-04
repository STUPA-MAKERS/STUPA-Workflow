import type { FormFieldDef } from '@core/api/models';
import { formatAnswer, formatEuro, isEmptyAnswer } from './answer-format';
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

  it('formats euro and refuses what is no number', () => {
    expect(formatEuro(12.5, 'de')?.replace(/\s/g, ' ')).toBe('12,50 €');
    expect(formatEuro('3', 'en')).toBe('€3.00');
    for (const v of [null, undefined, '', true, 'abc', Infinity]) expect(formatEuro(v, 'de')).toBeNull();
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

  it('takes the value of a position from its preferred offer', () => {
    const p = { offers: [{ label: 'A', value: 5, preferred: false }, { label: 'B', value: 7, preferred: true }] };
    expect(preferredOffer(p)?.label).toBe('B');
    expect(positionValue(p)).toBe(7);
    expect(positionValue({ offers: [{ label: 'A', value: null, preferred: true }] })).toBe(0);
    expect(positionsTotal([p, { offers: [] }])).toBe(7);
  });
});
