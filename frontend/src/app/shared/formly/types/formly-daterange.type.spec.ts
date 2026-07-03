import { FormControl } from '@angular/forms';
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
