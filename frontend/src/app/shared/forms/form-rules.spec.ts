import type { FormFieldDef, FormRule } from '@core/api/models';
import fixture from './form-rules.fixture.json';
import {
  brokenRules,
  costLine,
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
});

describe('costLine (specs 001630, 001631)', () => {
  const kosten = field('kosten', 'positions');
  const funding = field('f', 'funding');
  const people = field('n', 'number', { validation: { participants: true } });

  it('shows the total as the requested amount without a funding', () => {
    expect(costLine([kosten], { kosten: [position(120)] })).toEqual({
      total: 120,
      requested: 120,
      perPerson: null,
    });
  });

  it('shows the funding as the requested amount', () => {
    expect(costLine([kosten, funding], { kosten: [position(120)], f: 80 })).toEqual({
      total: 120,
      requested: 80,
      perPerson: null,
    });
  });

  it('adds the amount per person, rounded to the cent', () => {
    expect(costLine([kosten, funding, people], { kosten: [position(100)], f: 100, n: 3 }).perPerson).toBe(
      33.33,
    );
    expect(costLine([kosten, people], { kosten: [position(100)], n: 0 }).perPerson).toBeNull();
    expect(costLine([kosten, people], { kosten: [position(100)] }).perPerson).toBeNull();
  });

  it('reads an empty form as zero', () => {
    expect(costLine([], {})).toEqual({ total: 0, requested: 0, perPerson: null });
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
