import { FormControl } from '@angular/forms';
import type { FormlyFieldConfig } from '@ngx-formly/core';
import {
  applyServerErrors,
  clearServerErrors,
  errorPositionIndex,
  errorRootKey,
  findFieldByKey,
  positionErrorKey,
} from './server-errors';

const t = (key: string) => `T:${key}`;

function field(key: string, type = 'input'): FormlyFieldConfig {
  return { key, type, props: {}, formControl: new FormControl('x'), options: { detectChanges: jest.fn() } };
}

describe('server-errors', () => {
  it('reads the answer key and the position of an error path', () => {
    expect(errorRootKey('costs[1].offers[0]')).toBe('costs');
    expect(errorRootKey('title')).toBe('title');
    expect(errorRootKey('a.b')).toBe('a');
    expect(errorPositionIndex('costs[1].offers[0]')).toBe(1);
    expect(errorPositionIndex('costs')).toBeNull();
    expect(errorPositionIndex('costs.offers[2]')).toBeNull();
  });

  it.each([
    ['costs[0].offers[1]', 'offer value must be greater than 0', 'apply.positions.errOffers'],
    ['costs[0]', 'opting out of comparison offers needs a reason', 'apply.positions.errNoOffersReason'],
    ['costs[0]', 'needs at least 1 comparison offer(s)', 'forms.positions.errOffersServer'],
    ['costs[0]', 'exactly one offer must be marked preferred', 'apply.positions.errPreferred'],
    ['costs[0]', 'position needs a label', 'apply.positions.errLabel'],
    ['costs[0]', 'must be an object', 'forms.errors.server'],
  ])('names the rule of %s "%s"', (path, msg, key) => {
    expect(positionErrorKey({ field: path, msg })).toBe(key);
  });

  it('finds a field also inside a group', () => {
    const inner = field('b');
    const fields: FormlyFieldConfig[] = [field('a'), { fieldGroup: [{ fieldGroup: [inner] }] }];
    expect(findFieldByKey(fields, 'b')).toBe(inner);
    expect(findFieldByKey(fields, 'c')).toBeUndefined();
  });

  it('marks a plain field until its value changes', () => {
    const f = field('title');
    const placed = applyServerErrors([{ fieldGroup: [f] }], [{ field: 'title', msg: 'bad' }], t);
    expect(placed).toBe(1);
    expect(f.props?.['errorText']).toBe('T:forms.errors.server');
    expect(f.formControl?.errors).toEqual({ server: true });
    expect(f.formControl?.touched).toBe(true);
    expect(f.options?.detectChanges).toHaveBeenCalledWith(f);
    f.formControl?.setValue('y');
    expect(f.props?.['errorText']).toBeUndefined();
    // A second change leaves the props alone.
    f.props = { errorText: 'own' };
    f.formControl?.setValue('z');
    expect(f.props['errorText']).toBe('own');
  });

  it('puts the errors of a positions field on their positions, the first one wins', () => {
    const costs = field('costs', 'positions');
    costs.formControl?.setErrors({ positions: true });
    const placed = applyServerErrors(
      [costs],
      [
        { field: 'costs[1]', msg: 'needs at least 1 comparison offer(s)' },
        { field: 'costs[1].offers[0]', msg: 'offer needs a label' },
        { field: 'costs', msg: 'needs at least 2 position(s)' },
      ],
      t,
    );
    expect(placed).toBe(3);
    expect(costs.props?.['serverErrors']).toEqual({
      1: 'T:forms.positions.errOffersServer',
      [-1]: 'T:forms.errors.server',
    });
    expect(costs.formControl?.errors).toEqual({ positions: true, server: true });
  });

  it('skips an error without a field or a control', () => {
    const noControl: FormlyFieldConfig = { key: 'x' };
    expect(applyServerErrors([noControl], [{ field: 'x', msg: 'm' }, { field: 'y', msg: 'm' }], t)).toBe(0);
  });

  it('copes with fields without props and options', () => {
    const bare: FormlyFieldConfig = { key: 'a', formControl: new FormControl('') };
    const pos: FormlyFieldConfig = { key: 'p', type: 'positions', formControl: new FormControl([]) };
    expect(applyServerErrors([bare, pos], [{ field: 'a', msg: 'm' }, { field: 'p[0]', msg: 'm' }], t)).toBe(2);
    expect(bare.props?.['errorText']).toBe('T:forms.errors.server');
    expect(pos.props?.['serverErrors']).toEqual({ 0: 'T:forms.errors.server' });
    // The value change after the field lost its props clears nothing and does not throw.
    delete bare.props;
    bare.formControl?.setValue('b');
  });

  it('clears the messages of an earlier save everywhere', () => {
    const a = field('a');
    a.props = { errorText: 'x', label: 'A' };
    const p = field('p', 'positions');
    p.props = { serverErrors: { 0: 'y' } };
    const bare: FormlyFieldConfig = { key: 'b' };
    clearServerErrors([{ fieldGroup: [a, p, bare] }]);
    expect(a.props).toEqual({ label: 'A' });
    expect(p.props).toEqual({});
  });
});
