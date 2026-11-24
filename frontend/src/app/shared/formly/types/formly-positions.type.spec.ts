import { FormControl } from '@angular/forms';
import { render } from '@testing-library/angular';
import { Component, input } from '@angular/core';
import type { Provider } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { POSITION_FILES } from '@shared/forms/position-files';
import type { FormFieldDef } from '@core/api/models';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import { FormlyPositionsType } from './formly-positions.type';

interface Offer {
  label: string;
  value: number | null;
  preferred: boolean;
}
interface Position {
  label: string;
  offers: Offer[];
}

/**
 * Render the standalone type with a stubbed Formly `field` so methods are callable.
 * FormlyPositionsType overrides showError to read invalid and touched or dirty, so the
 * `options.showError` hook stays unused; it remains for FieldType compatibility. When requested,
 * the setup forces invalid and touched for the overridden showError.
 */
async function setup(opts: {
  value?: unknown;
  props?: Record<string, unknown>;
  showError?: boolean;
  model?: Record<string, unknown>;
  key?: string;
  providers?: Provider[];
} = {}): Promise<{
  cmp: FormlyPositionsType;
  control: FormControl;
  detect: () => void;
  host: HTMLElement;
}> {
  localStorage.setItem('ap.locale', 'de');
  const control = new FormControl(opts.value ?? null);
  const field = {
    formControl: control,
    props: opts.props ?? {},
    options: { showError: () => false },
    ...(opts.model ? { model: opts.model } : {}),
    ...(opts.key ? { key: opts.key } : {}),
  };
  const { fixture } = await render(FormlyPositionsType, {
    componentInputs: { field: field as never },
    providers: opts.providers ?? [],
  });
  const cmp = fixture.componentInstance;
  if (opts.showError) {
    control.setErrors({ positions: true });
    control.markAsTouched();
  }
  return {
    cmp,
    control,
    detect: () => fixture.detectChanges(),
    host: fixture.nativeElement as HTMLElement,
  };
}

/** Cast to any to reach protected helpers under test. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const prot = (cmp: FormlyPositionsType): any => cmp as any;

describe('FormlyPositionsType — config getters', () => {
  it('minOffers defaults to 3 and minPositions to 1', async () => {
    const { cmp } = await setup();
    expect(cmp.minOffers).toBe(3);
    expect(cmp.minPositions).toBe(1);
  });

  it('minOffers/minPositions read numeric props', async () => {
    const { cmp } = await setup({ props: { minOffers: 2, minPositions: 4 } });
    expect(cmp.minOffers).toBe(2);
    expect(cmp.minPositions).toBe(4);
  });

  it('minOffers falls back to 3 for a non-numeric/zero prop', async () => {
    const { cmp } = await setup({ props: { minOffers: 0 } });
    expect(cmp.minOffers).toBe(3);
  });

  it('positions returns [] when the control value is not an array', async () => {
    const { cmp } = await setup({ value: 'oops' });
    expect(cmp.positions).toEqual([]);
  });

  it('errorText resolves the i18n key', async () => {
    const { cmp } = await setup();
    expect(cmp.errorText).toContain('Jede Position braucht eine Bezeichnung');
  });
});

describe('FormlyPositionsType — add/remove/edit mutations', () => {
  it('addPosition creates a position with minOffers offers, first preferred', async () => {
    const { cmp, control } = await setup({ props: { minOffers: 2 } });
    cmp.addPosition();
    const v = control.value as Position[];
    expect(v).toHaveLength(1);
    expect(v[0].offers).toHaveLength(2);
    expect(v[0].offers[0].preferred).toBe(true);
    expect(v[0].offers[1].preferred).toBe(false);
    expect(control.dirty).toBe(true);
    expect(control.touched).toBe(true);
  });

  it('removePosition drops the position at the index', async () => {
    const { cmp, control } = await setup({ props: { minOffers: 1 } });
    cmp.addPosition();
    cmp.addPosition();
    expect((control.value as Position[]).length).toBe(2);
    cmp.removePosition(0);
    expect((control.value as Position[]).length).toBe(1);
  });

  it('addOffer appends an offer; first offer of an empty list becomes preferred', async () => {
    const { cmp, control } = await setup({
      value: [{ label: 'P', offers: [] }],
      props: { minOffers: 1 },
    });
    cmp.addOffer(0);
    let v = control.value as Position[];
    expect(v[0].offers).toHaveLength(1);
    expect(v[0].offers[0].preferred).toBe(true);
    cmp.addOffer(0);
    v = control.value as Position[];
    expect(v[0].offers[1].preferred).toBe(false);
  });

  it('removeOffer drops the offer at index for the right position', async () => {
    const { cmp, control } = await setup({
      value: [
        {
          label: 'P',
          offers: [
            { label: 'A', value: 1, preferred: true },
            { label: 'B', value: 2, preferred: false },
          ],
        },
      ],
      props: { minOffers: 1 },
    });
    cmp.removeOffer(0, 1);
    const v = control.value as Position[];
    expect(v[0].offers.map((o) => o.label)).toEqual(['A']);
  });

  it('setPositionLabel updates only the targeted position', async () => {
    const { cmp, control } = await setup({
      value: [
        { label: '', offers: [] },
        { label: 'keep', offers: [] },
      ],
    });
    cmp.setPositionLabel(0, 'Catering');
    const v = control.value as Position[];
    expect(v[0].label).toBe('Catering');
    expect(v[1].label).toBe('keep');
  });

  it('setOfferLabel updates only the targeted offer', async () => {
    const { cmp, control } = await setup({
      value: [
        {
          label: 'P',
          offers: [
            { label: '', value: null, preferred: true },
            { label: 'x', value: null, preferred: false },
          ],
        },
      ],
    });
    cmp.setOfferLabel(0, 0, 'Anbieter A');
    const v = control.value as Position[];
    expect(v[0].offers[0].label).toBe('Anbieter A');
    expect(v[0].offers[1].label).toBe('x');
  });

  it('setOfferValue parses the raw input into a number', async () => {
    const { cmp, control } = await setup({
      value: [{ label: 'P', offers: [{ label: 'A', value: null, preferred: true }] }],
    });
    cmp.setOfferValue(0, 0, '1.234,56');
    const v = control.value as Position[];
    expect(v[0].offers[0].value).toBeCloseTo(1234.56);
  });

  /** The test targets offer index 0, so the inner map also takes the k !== oi branch. */
  it('offer mutations leave sibling positions untouched (else branch of map)', async () => {
    const sibling: Position = {
      label: 'Other',
      offers: [{ label: 'Z', value: 9, preferred: true }],
    };
    const { cmp, control } = await setup({
      props: { minOffers: 1 },
      value: [
        {
          label: 'P',
          offers: [
            { label: 'A', value: 1, preferred: true },
            { label: 'B', value: 2, preferred: false },
          ],
        },
        sibling,
      ],
    });
    cmp.addOffer(0);
    cmp.removeOffer(0, 2);
    cmp.setOfferLabel(0, 0, 'renamed');
    cmp.setOfferValue(0, 0, '7');
    cmp.setPreferred(0, 0);
    const v = control.value as Position[];
    expect(v[0].offers[1].label).toBe('B');
    expect(v[0].offers[1].value).toBe(2);
    expect(v[0].offers[1].preferred).toBe(false);
    expect(v[1]).toEqual(sibling);
  });

  it('setPreferred makes exactly one offer preferred', async () => {
    const { cmp, control } = await setup({
      value: [
        {
          label: 'P',
          offers: [
            { label: 'A', value: 1, preferred: true },
            { label: 'B', value: 2, preferred: false },
          ],
        },
      ],
    });
    cmp.setPreferred(0, 1);
    const v = control.value as Position[];
    expect(v[0].offers[0].preferred).toBe(false);
    expect(v[0].offers[1].preferred).toBe(true);
  });
});

describe('FormlyPositionsType — totals & formatting', () => {
  it('positionValue returns the preferred offer value, or 0 when none preferred', async () => {
    const { cmp } = await setup();
    expect(
      prot(cmp).positionValue({
        label: 'P',
        offers: [
          { label: 'A', value: 10, preferred: false },
          { label: 'B', value: 20, preferred: true },
        ],
      }),
    ).toBe(20);
    expect(
      prot(cmp).positionValue({
        label: 'P',
        offers: [{ label: 'A', value: 10, preferred: false }],
      }),
    ).toBe(0);
  });

  it('total sums preferred values across positions', async () => {
    const { cmp } = await setup({
      value: [
        { label: 'P1', offers: [{ label: 'A', value: 100, preferred: true }] },
        { label: 'P2', offers: [{ label: 'B', value: 50, preferred: true }] },
      ],
    });
    expect(prot(cmp).total()).toBe(150);
  });

  it('fmt formats a number as EUR currency', async () => {
    const { cmp } = await setup();
    expect(prot(cmp).fmt(1234.5)).toContain('1.234,50');
    expect(prot(cmp).fmt(1234.5)).toContain('€');
  });
});

describe('FormlyPositionsType — value text & parsing', () => {
  it('offerValueText: null value → empty string', async () => {
    const { cmp } = await setup({
      value: [{ label: 'P', offers: [{ label: 'A', value: null, preferred: true }] }],
    });
    expect(prot(cmp).offerValueText(0, 0)).toBe('');
  });

  /** DE uses the decimal separator of the locale, with no grouping. */
  it('offerValueText: returns the raw value while editing that exact cell', async () => {
    const { cmp } = await setup({
      value: [{ label: 'P', offers: [{ label: 'A', value: 12.5, preferred: true }] }],
    });
    prot(cmp).beginEditValue(0, 0);
    expect(prot(cmp).editing).toEqual({ pi: 0, oi: 0 });
    expect(prot(cmp).offerValueText(0, 0)).toBe('12,5');
    prot(cmp).endEditValue();
    expect(prot(cmp).editing).toBeNull();
  });

  it('offerValueText: formats with 2 decimals when not editing that cell', async () => {
    const { cmp } = await setup({
      value: [
        {
          label: 'P',
          offers: [
            { label: 'A', value: 1234.5, preferred: true },
            { label: 'B', value: 9, preferred: false },
          ],
        },
      ],
    });
    prot(cmp).beginEditValue(0, 1);
    expect(prot(cmp).offerValueText(0, 0)).toBe('1.234,50');
  });

  it('offerValueText: missing position/offer → empty string', async () => {
    const { cmp } = await setup({ value: [] });
    expect(prot(cmp).offerValueText(5, 0)).toBe('');
  });

  /**
   * Invalid text is never 0. In DE one dot with at most 2 digits after it is a decimal; 3 decimals
   * are too many.
   */
  it('parseNum reads amounts in the UI locale and gives null for invalid text', async () => {
    const { cmp } = await setup();
    const parse = (s: string): number | null => prot(cmp).parseNum(s);
    expect(parse('')).toBeNull();
    expect(parse('   ')).toBeNull();
    expect(parse('abc')).toBeNull();
    expect(parse('1234,56')).toBeCloseTo(1234.56);
    expect(parse('1.234,56')).toBeCloseTo(1234.56);
    expect(parse('1.234')).toBe(1234);
    expect(parse('12,')).toBe(12);
    expect(parse('€ 50')).toBe(50);
    expect(parse('-5')).toBe(-5);
    expect(parse('1234.56')).toBeCloseTo(1234.56);
    expect(parse('12.50')).toBeCloseTo(12.5);
    expect(parse('1.2345')).toBeNull();
    expect(parse('12,345')).toBeNull();
    expect(parse('1.2.3')).toBeNull();
    expect(parse('--5')).toBeNull();
  });

  it('parseNum follows the EN locale', async () => {
    const { cmp } = await setup();
    const i18n = prot(cmp).i18n as I18nService;
    i18n.setLocale('en');
    const parse = (s: string): number | null => prot(cmp).parseNum(s);
    expect(parse('12,345')).toBe(12345);
    expect(parse('1,234.56')).toBeCloseTo(1234.56);
    expect(parse('12.345')).toBeNull();
    i18n.setLocale('de');
  });
});

describe('FormlyPositionsType — typing into an amount cell', () => {
  const one = (): Position[] => [
    {
      label: 'P',
      offers: [
        { label: 'A', value: null, preferred: true },
        { label: 'B', value: 5, preferred: false },
      ],
    },
  ];
  const value = (control: FormControl, oi = 0): number | null =>
    (control.value as Position[])[0].offers[oi].value;

  /** On blur the cell shows the formatted value. */
  it.each([
    ['12,', 12],
    ['1,5', 1.5],
    ['1.234,56', 1234.56],
    ['12.50', 12.5],
    ['-5', -5],
  ])('keeps the typed text %p while editing and stores %p', async (raw, expected) => {
    const { cmp, control } = await setup({ value: one() });
    prot(cmp).beginEditValue(0, 0);
    cmp.setOfferValue(0, 0, raw);
    expect(prot(cmp).offerValueText(0, 0)).toBe(raw);
    expect(value(control)).toBeCloseTo(expected);
    expect(prot(cmp).amountInvalid(0, 0)).toBe(false);
    prot(cmp).endEditValue();
    expect(prot(cmp).offerValueText(0, 0)).toBe(
      new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2 }).format(expected),
    );
  });

  /** On the next focus the invalid text stays for correction. */
  it.each([['abc'], ['12,345'], ['1.2345']])(
    'keeps invalid text %p after blur, stores null and shows the error',
    async (raw) => {
      const { cmp, control } = await setup({ value: one() });
      prot(cmp).beginEditValue(0, 0);
      cmp.setOfferValue(0, 0, raw);
      prot(cmp).endEditValue();
      expect(value(control)).toBeNull();
      expect(prot(cmp).offerValueText(0, 0)).toBe(raw);
      expect(prot(cmp).amountInvalid(0, 0)).toBe(true);
      const o = (control.value as Position[])[0].offers[0];
      expect(prot(cmp).offerValueInvalid(o, 0, 0)).toBe(true);
      expect(prot(cmp).cardError((control.value as Position[])[0], 0)).toContain(
        'Kein gültiger Betrag',
      );
      expect(control.invalid).toBe(true);
      prot(cmp).beginEditValue(0, 0);
      expect(prot(cmp).offerValueText(0, 0)).toBe(raw);
      cmp.setOfferValue(0, 0, '12,5');
      prot(cmp).endEditValue();
      expect(value(control)).toBe(12.5);
      expect(prot(cmp).offerValueText(0, 0)).toBe('12,50');
      expect(prot(cmp).amountInvalid(0, 0)).toBe(false);
    },
  );

  /** A second blur without a cell under edit does nothing. */
  it('an empty cell shows nothing on focus and clears its entry on blur', async () => {
    const { cmp } = await setup({ value: one() });
    prot(cmp).beginEditValue(0, 0);
    expect(prot(cmp).offerValueText(0, 0)).toBe('');
    prot(cmp).endEditValue();
    expect(prot(cmp).rawValues().size).toBe(0);
    prot(cmp).endEditValue();
    expect(prot(cmp).editing).toBeNull();
  });

  it('shows the EN editable text with a dot', async () => {
    const { cmp } = await setup({
      value: [{ label: 'P', offers: [{ label: 'A', value: 12.5, preferred: true }] }],
    });
    const i18n = prot(cmp).i18n as I18nService;
    i18n.setLocale('en');
    prot(cmp).beginEditValue(0, 0);
    expect(prot(cmp).offerValueText(0, 0)).toBe('12.5');
    i18n.setLocale('de');
  });

  it('moves the invalid text when a position or an offer is removed', async () => {
    const { cmp } = await setup({
      props: { minOffers: 1 },
      value: [
        { label: 'P0', offers: [{ label: 'A', value: 1, preferred: true }] },
        {
          label: 'P1',
          offers: [
            { label: 'B', value: 2, preferred: true },
            { label: 'C', value: null, preferred: false },
          ],
        },
      ],
    });
    cmp.setOfferValue(1, 1, 'abc');
    cmp.setOfferValue(0, 0, 'xyz');
    cmp.removePosition(0);
    expect(prot(cmp).offerValueText(0, 1)).toBe('abc');
    expect(prot(cmp).amountInvalid(0, 1)).toBe(true);
    cmp.setOfferValue(0, 0, 'q');
    cmp.removeOffer(0, 0);
    expect(prot(cmp).offerValueText(0, 0)).toBe('abc');
    expect(prot(cmp).rawValues().size).toBe(1);
    cmp.removeOffer(0, 0);
    expect(prot(cmp).rawValues().size).toBe(0);
  });

  it('keeps the entries before the removed position or offer in place', async () => {
    const { cmp } = await setup({
      props: { minOffers: 1 },
      value: [
        {
          label: 'P0',
          offers: [
            { label: 'A', value: null, preferred: true },
            { label: 'B', value: null, preferred: false },
          ],
        },
        { label: 'P1', offers: [{ label: 'C', value: null, preferred: true }] },
      ],
    });
    cmp.setOfferValue(0, 0, 'a');
    cmp.setOfferValue(1, 0, 'c');
    cmp.removePosition(1);
    expect(prot(cmp).offerValueText(0, 0)).toBe('a');
    cmp.addPosition();
    cmp.setOfferValue(1, 0, 'd');
    cmp.removeOffer(0, 1);
    expect(prot(cmp).offerValueText(0, 0)).toBe('a');
    expect(prot(cmp).offerValueText(1, 0)).toBe('d');
  });

  it('setNoOffers keeps an offer that holds only invalid amount text', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 3 },
      value: [
        {
          label: 'P',
          offers: [
            { label: '', value: null, preferred: true },
            { label: '', value: null, preferred: false },
            { label: 'X', value: 3, preferred: false },
          ],
        },
        { label: 'Q', offers: [{ label: '', value: null, preferred: true }] },
      ],
    });
    cmp.setOfferValue(0, 1, 'abc');
    cmp.setOfferValue(1, 0, 'zz');
    cmp.setNoOffers(0, true);
    const offers = (control.value as Position[])[0].offers;
    expect(offers.map((o) => o.label)).toEqual(['', 'X']);
    expect(prot(cmp).offerValueText(0, 0)).toBe('abc');
    expect(prot(cmp).offerValueText(1, 0)).toBe('zz');
  });
});

describe('FormlyPositionsType — validation reflection', () => {
  it('marks an empty field invalid on init (queueMicrotask revalidate)', async () => {
    const { control } = await setup({ value: [], props: { minPositions: 1 } });
    await new Promise((r) => queueMicrotask(() => r(null)));
    expect(control.invalid).toBe(true);
    expect(control.errors).toEqual({ positions: true });
  });

  /** A no-op mutation triggers the revalidation. */
  it('accepts a fully valid positions array', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 1, minPositions: 1 },
      value: [
        {
          label: 'Catering',
          offers: [{ label: 'Anbieter A', value: 500, preferred: true }],
        },
      ],
    });
    cmp.setPositionLabel(0, 'Catering');
    expect(control.errors).toBeNull();
    expect(control.valid).toBe(true);
  });

  it('invalidates when a position label is blank', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 1, minPositions: 1 },
      value: [{ label: 'tmp', offers: [{ label: 'A', value: 5, preferred: true }] }],
    });
    cmp.setPositionLabel(0, '   ');
    expect(control.errors).toEqual({ positions: true });
  });

  it('invalidates when there are too few offers', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 2, minPositions: 1 },
      value: [{ label: 'P', offers: [{ label: 'A', value: 5, preferred: true }] }],
    });
    cmp.setPositionLabel(0, 'P');
    expect(control.errors).toEqual({ positions: true });
  });

  it('invalidates when not exactly one offer is preferred', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 1, minPositions: 1 },
      value: [
        {
          label: 'P',
          offers: [
            { label: 'A', value: 5, preferred: true },
            { label: 'B', value: 6, preferred: true },
          ],
        },
      ],
    });
    cmp.setPositionLabel(0, 'P');
    expect(control.errors).toEqual({ positions: true });
  });

  it('invalidates when an offer has a blank label or a non-positive value', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 1, minPositions: 1 },
      value: [{ label: 'P', offers: [{ label: '', value: 0, preferred: true }] }],
    });
    cmp.setPositionLabel(0, 'P');
    expect(control.errors).toEqual({ positions: true });
  });

  it('accepts an offer of 0 €', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 1, minPositions: 1 },
      value: [{ label: 'P', offers: [{ label: 'A', value: 0, preferred: true }] }],
    });
    cmp.setPositionLabel(0, 'P');
    expect(control.errors).toBeNull();
  });

  it('required + zero positions is invalid', async () => {
    const { cmp, control } = await setup({
      props: { required: true, minPositions: 1 },
      value: [{ label: 'P', offers: [{ label: 'A', value: 5, preferred: true }] }],
    });
    cmp.removePosition(0);
    expect(control.errors).toEqual({ positions: true });
  });
});

describe('FormlyPositionsType — inline error helpers', () => {
  const validPos: Position = {
    label: 'P',
    offers: [{ label: 'A', value: 5, preferred: true }],
  };

  it('showError requires invalid + (touched|dirty)', async () => {
    const { cmp, control } = await setup({ value: [] });
    control.setErrors({ positions: true });
    expect(cmp.showError).toBe(false);
    control.markAsTouched();
    expect(cmp.showError).toBe(true);
  });

  it('titleInvalid / offerLabelInvalid / offerValueInvalid are false when not showing errors', async () => {
    const { cmp } = await setup();
    expect(prot(cmp).titleInvalid({ label: '', offers: [] })).toBe(false);
    expect(prot(cmp).offerLabelInvalid({ label: '', value: 1, preferred: false })).toBe(false);
    expect(prot(cmp).offerValueInvalid({ label: 'a', value: null, preferred: false })).toBe(false);
  });

  it('inline invalid flags fire when showError is true', async () => {
    const { cmp, control } = await setup({ value: [], showError: true });
    control.setErrors({ positions: true });
    control.markAsTouched();
    expect(prot(cmp).titleInvalid({ label: '  ', offers: [] })).toBe(true);
    expect(prot(cmp).titleInvalid({ label: 'ok', offers: [] })).toBe(false);
    expect(prot(cmp).offerLabelInvalid({ label: '', value: 1, preferred: false })).toBe(true);
    expect(prot(cmp).offerValueInvalid({ label: 'a', value: null, preferred: false })).toBe(true);
    expect(prot(cmp).offerValueInvalid({ label: 'a', value: -1, preferred: false })).toBe(true);
    expect(prot(cmp).offerValueInvalid({ label: 'a', value: 5, preferred: false })).toBe(false);
    expect(prot(cmp).offerValueInvalid({ label: 'a', value: 0, preferred: false })).toBe(false);
  });

  it('cardError returns empty string while not showing errors', async () => {
    const { cmp } = await setup({ showError: false });
    expect(prot(cmp).cardError(validPos)).toBe('');
  });

  it('cardError reports too-few-offers first', async () => {
    const { cmp } = await setup({ props: { minOffers: 3 }, showError: true });
    expect(prot(cmp).cardError(validPos)).toBe('Zu wenige Vergleichsangebote für diese Position.');
  });

  it('cardError reports wrong preferred count', async () => {
    const { cmp } = await setup({ props: { minOffers: 1 }, showError: true });
    expect(
      prot(cmp).cardError({
        label: 'P',
        offers: [
          { label: 'A', value: 1, preferred: true },
          { label: 'B', value: 2, preferred: true },
        ],
      }),
    ).toBe('Genau ein Angebot muss als bevorzugt markiert sein.');
  });

  it('cardError reports a missing label', async () => {
    const { cmp } = await setup({ props: { minOffers: 1 }, showError: true });
    expect(
      prot(cmp).cardError({ label: '  ', offers: [{ label: 'A', value: 1, preferred: true }] }),
    ).toBe('Bezeichnung der Position fehlt.');
  });

  it('cardError reports invalid offers (missing label or value)', async () => {
    const { cmp } = await setup({ props: { minOffers: 1 }, showError: true });
    expect(
      prot(cmp).cardError({ label: 'P', offers: [{ label: '', value: 1, preferred: true }] }),
    ).toBe('Jedes Angebot braucht eine Bezeichnung und einen Wert ≥ 0.');
  });

  it('cardError returns empty string for a fully valid position while showing errors', async () => {
    const { cmp } = await setup({ props: { minOffers: 1 }, showError: true });
    expect(prot(cmp).cardError(validPos)).toBe('');
  });
});

describe('FormlyPositionsType — comparison-offer opt-out (noOffers)', () => {
  it('allowNoOffers defaults to true', async () => {
    const { cmp } = await setup();
    expect(cmp.allowNoOffers).toBe(true);
  });

  it('allowNoOffers honours a false prop', async () => {
    const { cmp } = await setup({ props: { allowNoOffers: false } });
    expect(cmp.allowNoOffers).toBe(false);
  });

  it('requiredOffers is 1 for an opted-out position, minOffers otherwise', async () => {
    const { cmp } = await setup({ props: { minOffers: 3 } });
    expect(prot(cmp).requiredOffers({ label: 'P', offers: [] })).toBe(3);
    expect(prot(cmp).requiredOffers({ label: 'P', offers: [], noOffers: true })).toBe(1);
  });

  it('requiredOffers ignores noOffers when the opt-out is disallowed', async () => {
    const { cmp } = await setup({ props: { minOffers: 3, allowNoOffers: false } });
    expect(prot(cmp).requiredOffers({ label: 'P', offers: [], noOffers: true })).toBe(3);
  });

  it('setNoOffers(true) drops blank offers, keeps content and a preferred flag', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 3 },
      value: [
        {
          label: 'P',
          offers: [
            { label: '', value: null, preferred: true },
            { label: 'Einziger Anbieter', value: 500, preferred: false },
            { label: '', value: null, preferred: false },
          ],
        },
      ],
    });
    cmp.setNoOffers(0, true);
    const pos = (control.value as { offers: Offer[]; noOffers?: boolean }[])[0];
    expect(pos.noOffers).toBe(true);
    expect(pos.offers).toEqual([{ label: 'Einziger Anbieter', value: 500, preferred: true }]);
  });

  it('setNoOffers(true) on an all-blank position leaves one blank preferred offer', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 3 },
      value: [
        {
          label: 'P',
          offers: [
            { label: '', value: null, preferred: true },
            { label: '', value: null, preferred: false },
          ],
        },
      ],
    });
    cmp.setNoOffers(0, true);
    const pos = (control.value as { offers: Offer[] }[])[0];
    expect(pos.offers).toEqual([{ label: '', value: null, preferred: true }]);
  });

  it('setNoOffers(false) clears the reason and pads offers back to minOffers', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 3 },
      value: [
        {
          label: 'P',
          offers: [{ label: 'A', value: 500, preferred: true }],
          noOffers: true,
          noOffersReason: 'Einziger Anbieter',
        },
      ],
    });
    cmp.setNoOffers(0, false);
    const pos = (control.value as { offers: Offer[]; noOffers?: boolean; noOffersReason?: string }[])[0];
    expect(pos.noOffers).toBe(false);
    expect(pos.noOffersReason).toBe('');
    expect(pos.offers).toHaveLength(3);
  });

  it('an opted-out position with one offer and a reason validates', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 3, minPositions: 1 },
      value: [
        {
          label: 'P',
          offers: [{ label: 'A', value: 500, preferred: true }],
          noOffers: true,
          noOffersReason: 'tmp',
        },
      ],
    });
    cmp.setNoOffersReason(0, 'Einziger Anbieter in der Region.');
    expect(control.errors).toBeNull();
  });

  it('an opted-out position without a reason is invalid', async () => {
    const { cmp, control } = await setup({
      props: { minOffers: 3, minPositions: 1 },
      value: [
        {
          label: 'P',
          offers: [{ label: 'A', value: 500, preferred: true }],
          noOffers: true,
          noOffersReason: 'tmp',
        },
      ],
    });
    cmp.setNoOffersReason(0, '   ');
    expect(control.errors).toEqual({ positions: true });
  });

  it('reasonInvalid and the cardError message fire under showError', async () => {
    const { cmp, control } = await setup({ props: { minOffers: 1 }, showError: true });
    control.setErrors({ positions: true });
    control.markAsTouched();
    const p = {
      label: 'P',
      offers: [{ label: 'A', value: 5, preferred: true }],
      noOffers: true,
      noOffersReason: '',
    };
    expect(prot(cmp).reasonInvalid(p)).toBe(true);
    expect(prot(cmp).cardError(p)).toBe(
      'Bitte begründe, warum keine Vergleichsangebote möglich sind.',
    );
    expect(prot(cmp).reasonInvalid({ ...p, noOffersReason: 'Grund' })).toBe(false);
  });
});

/** A files block that only shows its inputs. */
@Component({
  selector: 'app-files-stub',
  standalone: true,
  template: `<span class="stub">{{ fieldKey() }}/{{ positionId() }}/{{ heading() }}</span>`,
})
class FilesStubComponent {
  readonly fieldKey = input('');
  readonly positionId = input('');
  readonly heading = input('');
}

/** The text of the cost line, with plain spaces. */
function lineOf(host: HTMLElement): string | undefined {
  return host.querySelector('.pos__line')?.textContent?.replace(/\s+/g, ' ').trim();
}

describe('FormlyPositionsType — cost line (specs 001630, 001631)', () => {
  const fields = [
    { key: 'kosten', type: 'positions', label: { de: 'K' } },
    { key: 'foerderung', type: 'funding', label: { de: 'F' } },
    { key: 'n', type: 'number', label: { de: 'N' }, validation: { participants: true } },
  ];
  const kosten = [{ label: 'Bus', offers: [{ label: 'Reisen AG', value: 1200, preferred: true }] }];

  it('shows the total as the requested amount without a funding', async () => {
    const model: Record<string, unknown> = { kosten };
    const { host } = await setup({
      key: 'kosten',
      value: kosten,
      model,
      props: { costLine: true, costFields: fields },
    });
    expect(lineOf(host)).toBe(
      'Gesamtkosten 1.200,00 €, davon beantragt 1.200,00 €',
    );
  });

  it('shows the funding and the amount per person, and follows the form', async () => {
    const model: Record<string, unknown> = { kosten, foerderung: 800, n: 3 };
    const { host, control, detect } = await setup({
      key: 'kosten',
      value: kosten,
      model,
      props: { costLine: true, costFields: fields },
    });
    expect(lineOf(host)).toBe(
      'Gesamtkosten 1.200,00 €, davon beantragt 800,00 €, 266,67 € pro Person',
    );
    model['n'] = 0;
    control.setValue(kosten);
    detect();
    expect(lineOf(host)).toBe(
      'Gesamtkosten 1.200,00 €, davon beantragt 800,00 €',
    );
  });

  it('shows no line on a field without costLine', async () => {
    const { host } = await setup({ key: 'kosten', value: kosten, props: { costFields: fields } });
    expect(host.querySelector('.pos__line')).toBeNull();
  });
});

describe('FormlyPositionsType — cost line setting (spec 003000)', () => {
  it('cost line: shows no Gesamtkosten line with costLine false, and keeps the head sum', async () => {
    const fields: FormFieldDef[] = [
      { key: 'kosten', type: 'positions', label: { de: 'K' }, validation: { costLine: false } },
      { key: 'foerderung', type: 'funding', label: { de: 'F' } },
    ];
    const kosten = [{ label: 'Bus', offers: [{ label: 'Reisen AG', value: 1200, preferred: true }] }];
    const props = (toFormlyFields(fields, 'de')[0].props ?? {}) as Record<string, unknown>;
    const { host } = await setup({ key: 'kosten', value: kosten, model: { kosten }, props });
    expect(host.querySelector('.pos__line')).toBeNull();
    expect(host.textContent).not.toContain('Gesamtkosten');
    expect(host.querySelector('.pos__total')?.textContent).toContain('1.200,00');
  });
});

describe('FormlyPositionsType — sum row (spec 003008)', () => {
  it('sumRow: shows the sum as a row below the positions and none in the head', async () => {
    const kosten = [{ label: 'Bus', offers: [{ label: 'Reisen AG', value: 1200, preferred: true }] }];
    const { host } = await setup({ key: 'kosten', value: kosten, model: { kosten } });
    const row = host.querySelector('.pos__total');
    expect(row?.firstElementChild?.textContent?.trim()).toBe('Gesamt');
    expect(row?.lastElementChild?.textContent?.replace(/\s/g, ' ').trim()).toBe('1.200,00 €');
    const cards = host.querySelectorAll('.pos__card');
    expect(cards[cards.length - 1]?.nextElementSibling).toBe(row);
    expect(host.querySelector('.pos__legend')?.nextElementSibling).toBe(host.querySelector('.pos__inner'));
  });
});

describe('FormlyPositionsType — placeholder warnings (specs 001640, 001641)', () => {
  const offers = [
    { label: 'x', value: 1, preferred: true },
    { label: 'Thomann', value: 50, preferred: false },
    { label: ' thomann', value: 60, preferred: false },
  ];

  it('names the reasons under the field they belong to', async () => {
    const { cmp, control } = await setup({ value: [{ label: 'P', offers }] });
    const p = (control.value as Position[])[0];
    expect(prot(cmp).offerWarning(p, 0, 'value')).toBe('Wie ein Platzhalter.');
    expect(prot(cmp).offerWarning(p, 0, 'label')).toBe('Weniger als 3 Zeichen.');
    expect(prot(cmp).offerWarning(p, 1, 'label')).toBe('Steht schon bei einem anderen Angebot.');
    expect(prot(cmp).offerWarning(p, 1, 'value')).toBe('');
    expect(prot(cmp).offerWarning({ ...p, offers: [offers[1]] }, 0, 'label')).toBe('');
  });

  it('marks the field and links the warning to its input', async () => {
    const { cmp, host, detect } = await setup({ value: [{ label: 'P', offers }] });
    prot(cmp).toggleOpen(0);
    detect();
    const warned = host.querySelectorAll('.pf--warn');
    expect(warned).toHaveLength(4);
    const input = warned[0].querySelector('input') as HTMLInputElement;
    const hint = host.querySelector(`#${input.getAttribute('aria-describedby')}`);
    expect(hint?.textContent?.trim()).toBe('Weniger als 3 Zeichen.');
  });

  it('names the switch for no comparison offers once below the offers', async () => {
    const { cmp, control, host, detect } = await setup({ value: [{ label: 'P', offers }] });
    prot(cmp).toggleOpen(0);
    detect();
    const p = (control.value as Position[])[0];
    expect(prot(cmp).switchHint(p)).toBe(
      'Gibt es keine Vergleichsangebote, schalte „Für diese Position sind keine Vergleichsangebote möglich“ ein.',
    );
    expect(host.querySelectorAll('.pos__warn')).toHaveLength(1);
    expect(prot(cmp).switchHint({ ...p, offers: [offers[1]] })).toBe('');
  });

  it('does not name the switch when the field does not offer it', async () => {
    const { cmp, control } = await setup({
      value: [{ label: 'P', offers }],
      props: { allowNoOffers: false },
    });
    const p = (control.value as Position[])[0];
    expect(prot(cmp).switchHint(p)).toBe('');
    expect(prot(cmp).switchHint({ ...p, noOffers: true })).toBe('');
  });

  it('placeholder: shows no warning and no switch hint with placeholderWarning false (spec 003001)', async () => {
    const { cmp, control, host, detect } = await setup({
      value: [{ label: 'P', offers }],
      props: { placeholderWarning: false },
    });
    prot(cmp).toggleOpen(0);
    detect();
    const p = (control.value as Position[])[0];
    expect(prot(cmp).offerWarning(p, 0, 'value')).toBe('');
    expect(prot(cmp).switchHint(p)).toBe('');
    expect(host.querySelectorAll('.pf--warn')).toHaveLength(0);
    expect(host.querySelectorAll('.pos__warn')).toHaveLength(0);
  });

  it('keeps a complete position with a warning valid', async () => {
    const { control } = await setup({
      value: [{ label: 'P', offers }],
      props: { minOffers: 3 },
    });
    await Promise.resolve();
    expect(control.errors).toBeNull();
  });
});

describe('FormlyPositionsType — files per position (spec 001730)', () => {
  it('gives a new position an id', async () => {
    const { cmp, control } = await setup({ props: { minOffers: 1 } });
    cmp.addPosition();
    expect((control.value as { id?: string }[])[0].id).toMatch(/^p-/);
  });

  it('shows the files block of the page and reports a removed position', async () => {
    const removed = jest.fn();
    const { cmp, control, host } = await setup({
      key: 'kosten',
      value: [{ label: '', offers: [] }],
      providers: [{ provide: POSITION_FILES, useValue: { component: FilesStubComponent, removed } }],
    });
    const id = (control.value as { id?: string }[])[0].id;
    expect(id).toMatch(/^p-/);
    expect(host.querySelector('.stub')?.textContent).toBe(`kosten/${id}/Dateien zur Position`);
    cmp.removePosition(0);
    expect(removed).toHaveBeenCalledWith('kosten', id);
  });

  it('position files: has no files block with positionFiles false (spec 003002)', async () => {
    const removed = jest.fn();
    const { host } = await setup({
      key: 'kosten',
      value: [{ id: 'p-1', label: '', offers: [] }],
      props: { positionFiles: false },
      providers: [{ provide: POSITION_FILES, useValue: { component: FilesStubComponent, removed } }],
    });
    expect(host.querySelector('.stub')).toBeNull();
  });

  it('has no files block without the page token', async () => {
    const { host } = await setup({ value: [{ id: 'p-1', label: '', offers: [] }] });
    expect(host.querySelector('.stub')).toBeNull();
  });
});
