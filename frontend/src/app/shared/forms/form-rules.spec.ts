import type { FormFieldDef, FormRule } from '@core/api/models';
import fixture from './form-rules.fixture.json';
import computedFixture from './computed.fixture.json';
import {
  brokenRules,
  computeValues,
  formattedValue,
  costTotal,
  finiteNumber,
  placeholderReasons,
  promotedAmount,
  ruleContext,
  ruleMet,
} from './form-rules';

const fields = fixture.fields as unknown as FormFieldDef[];
const rules = fixture.rules as unknown as FormRule[];

function field(key: string, type: FormFieldDef['type'], extra: Partial<FormFieldDef> = {}): FormFieldDef {
  return { key, type, label: { de: key }, required: false, ...extra } as FormFieldDef;
}

function position(value: unknown, preferred = true): Record<string, unknown> {
  return { label: 'P', offers: [{ label: 'A', value, preferred }] };
}

describe('computed fields (specs 002960-002962, shared fixture)', () => {
  const computedFields = computedFixture.fields as unknown as FormFieldDef[];
  it.each(computedFixture.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const got = computeValues(computedFields, c.data as Record<string, unknown>);
    expect(Object.keys(got).sort()).toEqual(Object.keys(c.values).sort());
    for (const [key, value] of Object.entries(c.values)) {
      expect(got[key]).toBeCloseTo(value as number, 9);
    }
  });

  it('rounds money half up away from 0 and percent to four places', () => {
    expect(formattedValue('money', 0.125)).toBe(0.13);
    expect(formattedValue('money', -0.125)).toBe(-0.13);
    expect(formattedValue('percent', 1000 / 1200)).toBe(0.8333);
  });

  it('gives no value for a format that needs a number and for a number that is not finite', () => {
    expect(formattedValue('money', true)).toBeNull();
    expect(formattedValue('number', Infinity)).toBeNull();
    expect(formattedValue('number', undefined)).toBeNull();
    expect(formattedValue('number', true)).toBe(true);
  });

  it('gives a computed amount whole cents and none below 0', () => {
    const amount = field('summe', 'computed', {
      compute: { var: 'x' },
      isPromoted: true,
      promoteTarget: 'amount',
    });
    expect(computeValues([amount], { x: 29.405 })).toEqual({ summe: 29.41 });
    expect(computeValues([amount], { x: -1 })).toEqual({});
    expect(computeValues([amount], {})).toEqual({});
  });
});

describe('form rules (spec 001671, shared fixture)', () => {
  it.each(fixture.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    expect(brokenRules(rules, fields, c.data as Record<string, unknown>)).toEqual(c.broken);
  });
});

describe('finiteNumber', () => {
  it.each([
    [3, 3],
    ['4.5', 4.5],
    [Number.NaN, null],
    [Infinity, null],
    ['', null],
    ['  ', null],
    ['x', null],
    [null, null],
    [true, null],
  ])('reads %p as %p', (raw, out) => {
    expect(finiteNumber(raw)).toBe(out);
  });
});

describe('costTotal and promotedAmount', () => {
  const kosten = field('kosten', 'positions');
  const mehr = field('mehr', 'positions');

  it('adds the preferred offers of every positions field', () => {
    expect(costTotal([kosten, mehr], { kosten: [position(1.5)], mehr: [position('2')] })).toBe(3.5);
  });

  it('has no total without a preferred offer', () => {
    expect(costTotal([kosten], { kosten: [position(5, false)] })).toBeNull();
    expect(costTotal([kosten], { kosten: 'x' })).toBeNull();
    expect(costTotal([kosten], { kosten: [null, { offers: 'x' }, position(true)] })).toBeNull();
    expect(costTotal([field('a', 'text')], { a: 'x' })).toBeNull();
  });

  it('lets a promoted number after the positions replace the total', () => {
    const summe = field('summe', 'number', { isPromoted: true, promoteTarget: 'amount' });
    expect(promotedAmount([kosten, summe], { kosten: [position(10)], summe: 7 })).toBe(7);
    expect(promotedAmount([kosten, summe], { kosten: [position(10)] })).toBe(10);
    expect(promotedAmount([kosten, field('t', 'text')], { kosten: [position(10)], t: '3' })).toBe(10);
  });

  it('takes a computed amount in whole cents from 0 (specs 002840, 002841)', () => {
    const km = field('km', 'number');
    const summe = field('summe', 'computed', { isPromoted: true, promoteTarget: 'amount' });
    expect(promotedAmount([km, summe], { km: 84, summe: 29.400000000000002 })).toBe(29.4);
    expect(promotedAmount([km, summe], { summe: 29.405 })).toBe(29.41);
    expect(promotedAmount([km, summe], { summe: -1 })).toBeNull();
    expect(promotedAmount([km, summe], { summe: '5' })).toBeNull();
    expect(promotedAmount([field('c', 'computed')], { c: 5 })).toBeNull();
  });

  it('lets a filled-in funding win', () => {
    const funding = field('f', 'funding');
    expect(promotedAmount([kosten, funding], { kosten: [position(10)], f: 4 })).toBe(4);
    expect(promotedAmount([kosten, funding], { kosten: [position(10)], f: true })).toBe(10);
    expect(promotedAmount([kosten, funding], { kosten: [position(10)] })).toBe(10);
    expect(promotedAmount([], {})).toBeNull();
  });

  it('puts amount and costTotal beside the answers', () => {
    expect(ruleContext([kosten], { kosten: [position(10)], a: 1 })).toEqual({
      kosten: [position(10)],
      a: 1,
      amount: 10,
      costTotal: 10,
    });
  });
});

describe('ruleMet', () => {
  it('needs exactly true', () => {
    expect(ruleMet({ logic: { var: 'a' } }, { a: true })).toBe(true);
    expect(ruleMet({ logic: { var: 'a' } }, { a: 1 })).toBe(false);
  });

  it('counts an expression that cannot be evaluated as met', () => {
    expect(ruleMet({ logic: { eval: ['x'] } }, {})).toBe(true);
  });

  it('passes on an error that is not about the expression', () => {
    const broken = new Proxy(
      {},
      {
        ownKeys: () => {
          throw new TypeError('boom');
        },
      },
    );
    expect(() => ruleMet({ logic: broken }, {})).toThrow('boom');
  });
});

describe('placeholderReasons (spec 001640)', () => {
  it('flags 0 € and 1 €, short labels and duplicates', () => {
    expect(
      placeholderReasons([
        { label: 'Amazon', value: 0 },
        { label: ' x ', value: 1 },
        { label: 'amazon ', value: 50 },
        { label: 'Thomann', value: 60 },
      ]),
    ).toEqual([['value', 'duplicate'], ['value', 'label'], ['duplicate'], []]);
  });

  it('leaves an empty offer to the required check', () => {
    expect(placeholderReasons([{ label: '', value: null }, { label: '', value: null }])).toEqual([[], []]);
  });
});
