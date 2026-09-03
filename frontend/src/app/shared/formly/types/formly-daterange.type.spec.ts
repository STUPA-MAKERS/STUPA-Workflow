import { FormControl } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import { de } from '@core/i18n/translations';
import { FormlyDateRangeType } from './formly-daterange.type';

function makeType(
  value: unknown = null,
  props: Record<string, unknown> = {},
): { cmp: FormlyDateRangeType; control: FormControl } {
  const cmp = new FormlyDateRangeType();
  const control = new FormControl(value);
  cmp.field = {
    formControl: control,
    props,
    options: { showError: () => false },
  } as unknown as FormlyDateRangeType['field'];
  return { cmp, control };
}

function evt(value: string): Event {
  return { target: { value } } as unknown as Event;
}

describe('FormlyDateRangeType', () => {
  it('range returns {} for null/non-object, the object otherwise', () => {
    expect(makeType(null).cmp.range).toEqual({});
    expect(makeType('nope').cmp.range).toEqual({});
    expect(makeType({ from: '2026-01-01' }).cmp.range).toEqual({ from: '2026-01-01' });
  });

  it('patch sets from/to on the control and marks it dirty/touched', () => {
    const { cmp, control } = makeType({ from: '2026-01-01' });
    cmp.patch('to', evt('2026-01-03'));
    expect(control.value).toEqual({ from: '2026-01-01', to: '2026-01-03' });
    expect(control.dirty).toBe(true);
    expect(control.touched).toBe(true);
  });

  it('clears the control to null when both ends are emptied', () => {
    const { cmp, control } = makeType({ from: '2026-01-01' });
    cmp.patch('from', evt(''));
    expect(control.value).toBeNull();
  });
});

/** Render the type on its own so the untouched `props` fallbacks of the template fire. */
async function renderBare(props: Record<string, unknown>, showError = false): Promise<void> {
  await render(FormlyDateRangeType, {
    componentInputs: {
      field: {
        formControl: new FormControl(null),
        props,
        options: { showError: () => showError },
      } as never,
    },
  });
}

describe('FormlyDateRangeType (captions and error text)', () => {
  afterEach(() => localStorage.removeItem('ap.locale'));

  it('uses the German captions and error text by default', async () => {
    await renderBare({ label: 'Zeitraum' }, true);
    expect(screen.getByText(de['formly.daterange.from'])).toBeInTheDocument();
    expect(screen.getByText(de['formly.daterange.to'])).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(de['formly.daterange.error']);
  });

  it('renders the captions and the error text in English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await renderBare({ label: 'Period' }, true);
    expect(screen.getByText('From')).toBeInTheDocument();
    expect(screen.getByText('To')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid date range.');
  });

  it('lets explicit props win over the translated defaults', async () => {
    await renderBare({ fromLabel: 'Start', toLabel: 'Ende', errorText: 'Kaputt.' }, true);
    expect(screen.getByText('Start')).toBeInTheDocument();
    expect(screen.getByText('Ende')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Kaputt.');
  });
});
