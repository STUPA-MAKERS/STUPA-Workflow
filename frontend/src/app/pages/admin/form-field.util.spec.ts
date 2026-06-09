import type { FormFieldDef } from '@core/api/models';
import {
  blankField,
  duplicateKeys,
  normalizeFormField,
  parseFields,
  serializeFields,
  validateFormField,
  validateJsonLogic,
} from './form-field.util';

function field(overrides: Partial<FormFieldDef> = {}): FormFieldDef {
  return { key: 'title', type: 'text', label: { de: 'Titel', en: 'Title' }, ...overrides };
}

describe('validateFormField (mirror of config_schemas.FormFieldDef)', () => {
  it('accepts a valid text field', () => {
    expect(validateFormField(field())).toEqual({ valid: true, errors: [] });
  });

  it('rejects an invalid key', () => {
    expect(validateFormField(field({ key: 'Bad Key' })).valid).toBe(false);
  });

  it('requires a German label', () => {
    expect(validateFormField(field({ label: { en: 'x' } })).errors).toContain(
      'label (de) is required',
    );
  });

  it('requires options for select/multiselect', () => {
    expect(validateFormField(field({ type: 'select' })).errors).toContain(
      "options are required for type 'select'",
    );
    expect(
      validateFormField(
        field({ type: 'select', options: [{ value: 'a', label: { de: 'A' } }] }),
      ).valid,
    ).toBe(true);
  });

  it('requires compute for computed fields', () => {
    expect(validateFormField(field({ type: 'computed' })).errors).toContain(
      "compute is required for type 'computed'",
    );
    expect(validateFormField(field({ type: 'computed', compute: { var: 'amount' } })).valid).toBe(
      true,
    );
  });

  it('requires promoteTarget when isPromoted', () => {
    expect(validateFormField(field({ isPromoted: true })).errors).toContain(
      'promoteTarget is required when isPromoted is true',
    );
    expect(validateFormField(field({ isPromoted: true, promoteTarget: 'amount' })).valid).toBe(true);
  });

  it('validates visibleIf/compute JsonLogic structure', () => {
    expect(validateFormField(field({ visibleIf: { '==': [{ var: 'x' }, 1] } })).valid).toBe(true);
    expect(validateFormField(field({ visibleIf: { bogus: 1 } })).valid).toBe(false);
    expect(
      validateFormField(field({ type: 'computed', compute: { nope: 1 } })).errors,
    ).toContain('compute is not a valid JsonLogic expression');
  });
});

describe('validateJsonLogic', () => {
  it('accepts literals and known operators', () => {
    expect(validateJsonLogic(5)).toBe(true);
    expect(validateJsonLogic({ var: 'a' })).toBe(true);
    expect(validateJsonLogic({ and: [{ '>': [{ var: 'a' }, 1] }, { var: 'b' }] })).toBe(true);
  });

  it('rejects multi-key and unknown operators', () => {
    expect(validateJsonLogic({ a: 1, b: 2 })).toBe(false);
    expect(validateJsonLogic({ pwn: [1] })).toBe(false);
  });
});

describe('duplicateKeys', () => {
  it('finds repeated keys', () => {
    expect(duplicateKeys([field(), field({ key: 'title' }), field({ key: 'x' })])).toEqual([
      'title',
    ]);
  });
});

describe('round-trip', () => {
  it('normalize strips empty optionals', () => {
    expect(normalizeFormField(field({ help: {}, required: false }))).toEqual({
      key: 'title',
      type: 'text',
      label: { de: 'Titel', en: 'Title' },
    });
  });

  it('serialize → parse is idempotent', () => {
    const fields = [field(), field({ key: 'amount', type: 'currency', required: true })];
    const back = parseFields(serializeFields(fields));
    expect(back).toEqual(fields.map(normalizeFormField));
  });

  it('keeps isPromoted only for numeric types', () => {
    const num = normalizeFormField(
      field({ key: 'amount', type: 'currency', isPromoted: true, promoteTarget: 'amount' }),
    );
    expect(num.isPromoted).toBe(true);
    // positions auto-promotes without the flag → strip it (backend rejects it, 422).
    const pos = normalizeFormField(field({ key: 'positions', type: 'positions', isPromoted: true }));
    expect(pos.isPromoted).toBeUndefined();
    expect(pos.promoteTarget).toBeUndefined();
  });
});

describe('blankField', () => {
  it('seeds required parts per type', () => {
    expect(blankField('text').label).toEqual({ de: '', en: '' });
    expect(blankField('select').options).toHaveLength(1);
    expect(blankField('computed').compute).toEqual({ var: '' });
  });
});
