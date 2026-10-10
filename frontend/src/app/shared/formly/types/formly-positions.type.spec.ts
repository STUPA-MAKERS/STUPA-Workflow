import { FormControl } from '@angular/forms';
import { render } from '@testing-library/angular';
import { I18nService } from '@core/i18n/i18n.service';
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

/** Render the standalone type with a stubbed Formly `field` so methods are callable. */
async function setup(opts: {
  value?: unknown;
  props?: Record<string, unknown>;
  showError?: boolean;
} = {}): Promise<{ cmp: FormlyPositionsType; control: FormControl; detect: () => void }> {
  localStorage.setItem('ap.locale', 'de');
  const control = new FormControl(opts.value ?? null);
  const field = {
    formControl: control,
    props: opts.props ?? {},
    // FormlyPositionsType overrides showError to read invalid + touched/dirty,
    // so this hook stays unused. It remains for FieldType compatibility.
    options: { showError: () => false },
  };
  const { fixture } = await render(FormlyPositionsType, {
    componentInputs: { field: field as never },
  });
  const cmp = fixture.componentInstance;
  // The overridden showError needs invalid + touched. Force both when requested.
  if (opts.showError) {
    control.setErrors({ positions: true });
    control.markAsTouched();
  }
  return { cmp, control, detect: () => fixture.detectChanges() };
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
    // Target offer index 0 so the inner map also exercises the k !== oi (else) branch.
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

  it('offerValueText: returns the raw value while editing that exact cell', async () => {
    const { cmp } = await setup({
      value: [{ label: 'P', offers: [{ label: 'A', value: 12.5, preferred: true }] }],
    });
    prot(cmp).beginEditValue(0, 0);
    expect(prot(cmp).editing).toEqual({ pi: 0, oi: 0 });
    // DE: the decimal separator of the locale, no grouping.
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

  it('parseNum reads amounts in the UI locale and gives null for invalid text', async () => {
    const { cmp } = await setup();
    const parse = (s: string): number | null => prot(cmp).parseNum(s);
    expect(parse('')).toBeNull();
    expect(parse('   ')).toBeNull();
    // Invalid text is never 0.
    expect(parse('abc')).toBeNull();
    expect(parse('1234,56')).toBeCloseTo(1234.56);
    expect(parse('1.234,56')).toBeCloseTo(1234.56);
    expect(parse('1.234')).toBe(1234);
    expect(parse('12,')).toBe(12);
    expect(parse('€ 50')).toBe(50);
    expect(parse('-5')).toBe(-5);
    // DE: "." is the thousands separator, and 3 decimals are too many.
    expect(parse('1234.56')).toBeNull();
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

  it.each([
    ['12,', 12],
    ['1,5', 1.5],
    ['1.234,56', 1234.56],
    ['-5', -5],
  ])('keeps the typed text %p while editing and stores %p', async (raw, expected) => {
    const { cmp, control } = await setup({ value: one() });
    prot(cmp).beginEditValue(0, 0);
    cmp.setOfferValue(0, 0, raw);
    expect(prot(cmp).offerValueText(0, 0)).toBe(raw);
    expect(value(control)).toBeCloseTo(expected);
    expect(prot(cmp).amountInvalid(0, 0)).toBe(false);
    prot(cmp).endEditValue();
    // On blur the cell shows the formatted value.
    expect(prot(cmp).offerValueText(0, 0)).toBe(
      new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2 }).format(expected),
    );
  });

  it.each([['abc'], ['12,345'], ['1234.5']])(
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
      // Focus again: the invalid text stays for correction.
      prot(cmp).beginEditValue(0, 0);
      expect(prot(cmp).offerValueText(0, 0)).toBe(raw);
      cmp.setOfferValue(0, 0, '12,5');
      prot(cmp).endEditValue();
      expect(value(control)).toBe(12.5);
      expect(prot(cmp).offerValueText(0, 0)).toBe('12,50');
      expect(prot(cmp).amountInvalid(0, 0)).toBe(false);
    },
  );

  it('an empty cell shows nothing on focus and clears its entry on blur', async () => {
    const { cmp } = await setup({ value: one() });
    prot(cmp).beginEditValue(0, 0);
    expect(prot(cmp).offerValueText(0, 0)).toBe('');
    prot(cmp).endEditValue();
    expect(prot(cmp).rawValues().size).toBe(0);
    // A second blur without a cell under edit does nothing.
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
    // Commit a no-op mutation to trigger revalidate.
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
    expect(cmp.showError).toBe(false); // pristine and untouched
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
    ).toBe('Jedes Angebot braucht eine Bezeichnung und einen Wert > 0.');
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
