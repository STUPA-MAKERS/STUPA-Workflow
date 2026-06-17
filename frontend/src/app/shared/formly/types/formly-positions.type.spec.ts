import { FormControl } from '@angular/forms';
import { render } from '@testing-library/angular';
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
    // so this hook is unused — kept for FieldType compatibility.
    options: { showError: () => false },
  };
  const { fixture } = await render(FormlyPositionsType, {
    componentInputs: { field: field as never },
  });
  const cmp = fixture.componentInstance;
  // The overridden showError needs invalid + touched; force it when requested.
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
    // Offer index 1 was left untouched by the per-offer edits (else branch).
    expect(v[0].offers[1].label).toBe('B');
    expect(v[0].offers[1].value).toBe(2);
    expect(v[0].offers[1].preferred).toBe(false);
    // The second position is unchanged through every per-offer mutation.
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
    expect(prot(cmp).offerValueText(0, 0)).toBe('12.5');
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
    // editing a different cell → other cell stays formatted.
    prot(cmp).beginEditValue(0, 1);
    expect(prot(cmp).offerValueText(0, 0)).toBe('1.234,50');
  });

  it('offerValueText: missing position/offer → empty string', async () => {
    const { cmp } = await setup({ value: [] });
    expect(prot(cmp).offerValueText(5, 0)).toBe('');
  });

  it('parseNum handles the common numeric formats and edge cases', async () => {
    const { cmp } = await setup();
    const parse = (s: string): number | null => prot(cmp).parseNum(s);
    expect(parse('')).toBeNull();
    expect(parse('   ')).toBeNull();
    // Non-empty input whose chars are all stripped → cleaned '' → Number('') === 0.
    expect(parse('abc')).toBe(0);
    expect(parse('1234.56')).toBeCloseTo(1234.56);
    expect(parse('1234,56')).toBeCloseTo(1234.56);
    // German grouping: dot thousands, comma decimal.
    expect(parse('1.234,56')).toBeCloseTo(1234.56);
    // US grouping: comma thousands, dot decimal.
    expect(parse('1,234.56')).toBeCloseTo(1234.56);
    expect(parse('€ 50')).toBe(50);
    // Cleaned but still non-numeric → Number(...) is NaN → null branch.
    expect(parse('1.2.3')).toBeNull();
    expect(parse('--5')).toBeNull();
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
    // commit through a no-op mutation to trigger revalidate.
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
    expect(cmp.showError).toBe(false); // pristine & untouched
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
