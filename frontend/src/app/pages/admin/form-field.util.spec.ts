import type { FormFieldDef } from '@core/api/models';
import {
  blankField,
  blankOption,
  duplicateKeys,
  groupsFromFields,
  groupsToFields,
  normalizeFormField,
  parseFields,
  type QuestionGroup,
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

  it('rejects an unknown field type', () => {
    expect(
      validateFormField(field({ type: 'wat' as never })).errors,
    ).toContain('unknown field type: "wat"');
  });

  it('rejects a blank/whitespace German label', () => {
    expect(validateFormField(field({ label: { de: '   ' } })).errors).toContain(
      'label (de) is required',
    );
    expect(validateFormField(field({ label: {} })).errors).toContain('label (de) is required');
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

  it('wraps a non-array operand into a single-element arg list', () => {
    // raw is not an array → validated as [raw]
    expect(validateJsonLogic({ not: { var: 'x' } })).toBe(true);
    expect(validateJsonLogic({ not: { bogus: 1 } })).toBe(false);
  });

  it('treats a string literal and arrays of literals as valid', () => {
    expect(validateJsonLogic('hello')).toBe(true);
    expect(validateJsonLogic([1, 2, 3])).toBe(true);
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

  it('isPromoted on a numeric field with no promoteTarget keeps the flag only', () => {
    const out = normalizeFormField(field({ key: 'n', type: 'number', isPromoted: true }));
    expect(out.isPromoted).toBe(true);
    expect(out.promoteTarget).toBeUndefined();
  });

  it('retains non-empty help, validation, options, visibleIf, compute and isPII', () => {
    const out = normalizeFormField(
      field({
        type: 'select',
        help: { de: 'Hilfe' },
        validation: { max: 10 },
        options: [{ value: 'a', label: { de: 'A' } }],
        visibleIf: { var: 'x' },
        compute: { var: 'y' },
        isPII: true,
        required: true,
      }),
    );
    expect(out.help).toEqual({ de: 'Hilfe' });
    expect(out.validation).toEqual({ max: 10 });
    expect(out.options).toHaveLength(1);
    expect(out.visibleIf).toEqual({ var: 'x' });
    expect(out.compute).toEqual({ var: 'y' });
    expect(out.isPII).toBe(true);
    expect(out.required).toBe(true);
  });

  it('drops validation whose values are all empty/null', () => {
    const out = normalizeFormField(
      field({ validation: { pattern: '', min: undefined as never, max: null as never } }),
    );
    expect(out.validation).toBeUndefined();
  });

  it('drops an empty options array', () => {
    const out = normalizeFormField(field({ options: [] }));
    expect(out.options).toBeUndefined();
  });
});

describe('duplicateKeys edge cases', () => {
  it('returns [] for unique keys and ignores empty keys', () => {
    expect(duplicateKeys([field({ key: 'a' }), field({ key: 'b' })])).toEqual([]);
    // empty keys are filtered out and never reported
    expect(duplicateKeys([field({ key: '' }), field({ key: '' })])).toEqual([]);
  });

  it('sorts and de-duplicates the reported keys', () => {
    expect(
      duplicateKeys([
        field({ key: 'z' }),
        field({ key: 'z' }),
        field({ key: 'a' }),
        field({ key: 'a' }),
      ]),
    ).toEqual(['a', 'z']);
  });
});

describe('blankField', () => {
  it('seeds required parts per type', () => {
    expect(blankField('text').label).toEqual({ de: '', en: '' });
    expect(blankField('select').options).toHaveLength(1);
    expect(blankField('multiselect').options).toHaveLength(1);
    expect(blankField('computed').compute).toEqual({ var: '' });
  });

  it('defaults to a text field with an empty key', () => {
    const f = blankField();
    expect(f.type).toBe('text');
    expect(f.key).toBe('');
    expect(f.options).toBeUndefined();
    expect(f.compute).toBeUndefined();
  });

  it('uses the provided key', () => {
    expect(blankField('text', 'mykey').key).toBe('mykey');
  });
});

describe('blankOption', () => {
  it('returns an empty option scaffold', () => {
    expect(blankOption()).toEqual({ value: '', label: { de: '', en: '' } });
  });
});

describe('groupsFromFields / groupsToFields (section round-trip)', () => {
  function q(key: string): FormFieldDef {
    return { key, type: 'text', label: { de: key } };
  }
  function section(key: string, de: string, en = ''): FormFieldDef {
    return { key, type: 'section', label: { de, en } };
  }

  it('markerless fields collapse to a single untitled group', () => {
    const groups = groupsFromFields([q('a'), q('b')]);
    expect(groups).toHaveLength(1);
    expect(groups[0]).toEqual({ titleDe: '', titleEn: '', fields: [q('a'), q('b')] });
  });

  it('empty input yields one empty untitled group', () => {
    expect(groupsFromFields([])).toEqual([{ titleDe: '', titleEn: '', fields: [] }]);
  });

  it('splits at each section marker, keeping pre-marker fields as the implicit first group', () => {
    const groups = groupsFromFields([
      q('intro'),
      section('section_1', 'Block A', 'Block A en'),
      q('a1'),
      section('section_2', 'Block B'),
      q('b1'),
      q('b2'),
    ]);
    expect(groups).toHaveLength(3);
    expect(groups[0]).toEqual({ titleDe: '', titleEn: '', fields: [q('intro')] });
    expect(groups[1]).toEqual({ titleDe: 'Block A', titleEn: 'Block A en', fields: [q('a1')] });
    expect(groups[2]).toEqual({ titleDe: 'Block B', titleEn: '', fields: [q('b1'), q('b2')] });
  });

  it('a leading section marker opens a titled first group (no empty implicit group)', () => {
    const groups = groupsFromFields([section('section_1', 'First'), q('a')]);
    expect(groups).toHaveLength(1);
    expect(groups[0]).toEqual({ titleDe: 'First', titleEn: '', fields: [q('a')] });
  });

  it('a section marker with missing label falls back to empty titles', () => {
    const groups = groupsFromFields([{ key: 's', type: 'section' } as FormFieldDef, q('a')]);
    expect(groups[0]).toEqual({ titleDe: '', titleEn: '', fields: [q('a')] });
  });

  it('consecutive markers produce an empty group between them', () => {
    const groups = groupsFromFields([
      section('s1', 'A'),
      section('s2', 'B'),
      q('x'),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toEqual({ titleDe: 'A', titleEn: '', fields: [] });
    expect(groups[1]).toEqual({ titleDe: 'B', titleEn: '', fields: [q('x')] });
  });

  it('serializes an untitled first group without a marker (implicit main)', () => {
    const groups: QuestionGroup[] = [{ titleDe: '', titleEn: '', fields: [q('a'), q('b')] }];
    expect(groupsToFields(groups)).toEqual([q('a'), q('b')]);
  });

  it('emits a marker for a titled first group and auto-numbers sections', () => {
    const groups: QuestionGroup[] = [
      { titleDe: 'One', titleEn: 'Eins', fields: [q('a')] },
      { titleDe: 'Two', titleEn: '', fields: [q('b')] },
    ];
    const out = groupsToFields(groups);
    expect(out).toEqual([
      { key: 'section_1', type: 'section', label: { de: 'One', en: 'Eins' } },
      q('a'),
      { key: 'section_2', type: 'section', label: { de: 'Two', en: '' } },
      q('b'),
    ]);
  });

  it('an untitled non-first group still gets a marker', () => {
    const groups: QuestionGroup[] = [
      { titleDe: '', titleEn: '', fields: [q('a')] },
      { titleDe: '', titleEn: '', fields: [q('b')] },
    ];
    const out = groupsToFields(groups);
    expect(out[0]).toEqual(q('a'));
    expect(out[1]).toEqual({ key: 'section_1', type: 'section', label: { de: '', en: '' } });
    expect(out[2]).toEqual(q('b'));
  });

  it('an empty titled group serializes to just its marker', () => {
    const groups: QuestionGroup[] = [
      { titleDe: '', titleEn: '', fields: [q('a')] },
      { titleDe: 'Empty', titleEn: '', fields: [] },
    ];
    const out = groupsToFields(groups);
    expect(out).toEqual([
      q('a'),
      { key: 'section_1', type: 'section', label: { de: 'Empty', en: '' } },
    ]);
  });

  it('round-trips: fields → groups → fields preserves a titled layout', () => {
    const fields: FormFieldDef[] = [
      q('intro'),
      section('section_1', 'Block A', 'A'),
      q('a1'),
    ];
    expect(groupsToFields(groupsFromFields(fields))).toEqual(fields);
  });
});
