import type { FormlyFieldConfig } from '@ngx-formly/core';
import type { FormFieldDef } from '@core/api/models';
import { toFormlyFields } from './formly-mapper';

function callExpr(
  config: FormlyFieldConfig,
  key: string,
  model: Record<string, unknown>,
): unknown {
  const expr = config.expressions?.[key];
  expect(typeof expr).toBe('function');
  return (expr as (field: FormlyFieldConfig) => unknown)({ model } as FormlyFieldConfig);
}

describe('toFormlyFields', () => {
  it('maps a text field to the input type with resolved label and required', () => {
    const fields: FormFieldDef[] = [
      { key: 'title', type: 'text', label: { de: 'Titel', en: 'Title' }, required: true },
    ];
    const [cfg] = toFormlyFields(fields, 'en');
    expect(cfg.key).toBe('title');
    expect(cfg.type).toBe('input');
    expect(cfg.props?.label).toBe('Title');
    expect(cfg.props?.type).toBe('text');
    expect(cfg.props?.required).toBe(true);
  });

  it('maps currency to a numeric input and copies validation bounds', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'amount',
        type: 'currency',
        label: { de: 'Betrag' },
        validation: { min: 0, max: 100, minLen: 1, maxLen: 5, pattern: '\\d+' },
      },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.props?.type).toBe('number');
    expect(cfg.props?.min).toBe(0);
    expect(cfg.props?.max).toBe(100);
    expect(cfg.props?.['minLength']).toBe(1);
    expect(cfg.props?.['maxLength']).toBe(5);
    expect(cfg.props?.['pattern']).toBe('\\d+');
  });

  it('maps select/multiselect with resolved option labels', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'cat',
        type: 'select',
        label: { de: 'Kategorie' },
        options: [{ value: 'e', label: { de: 'Event', en: 'Event' } }],
      },
      {
        key: 'tags',
        type: 'multiselect',
        label: { de: 'Tags' },
        options: [{ value: 't', label: { de: 'Tag' } }],
      },
    ];
    const [sel, multi] = toFormlyFields(fields, 'de');
    expect(sel.type).toBe('select');
    expect(sel.props?.['options']).toEqual([{ value: 'e', label: 'Event' }]);
    expect(multi.type).toBe('multicheckbox');
  });

  it('maps markdown/checkbox/computed and wires the computed expression', () => {
    const fields: FormFieldDef[] = [
      { key: 'info', type: 'markdown', label: { de: 'Info' }, help: { de: 'Hinweistext' } },
      { key: 'agree', type: 'checkbox', label: { de: 'OK' } },
      {
        key: 'total',
        type: 'computed',
        label: { de: 'Summe' },
        compute: { '+': [{ var: 'amount' }, { var: 'cofunding' }] },
      },
    ];
    const [info, agree, total] = toFormlyFields(fields, 'de');
    expect(info.type).toBe('display');
    expect(info.props?.['text']).toBe('Hinweistext');
    expect(agree.type).toBe('checkbox');
    expect(total.props?.['computed']).toBe(true);
    expect(callExpr(total, 'model.total', { amount: 100, cofunding: 50 })).toBe(150);
  });

  it('returns null from a computed expression when evaluation errors', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'total',
        type: 'computed',
        label: { de: 'Summe' },
        compute: { '+': [{ var: 'amount' }, { var: 'cofunding' }] },
      },
    ];
    const [total] = toFormlyFields(fields, 'de');
    // cofunding missing → null var → arithmetic throws → caught → null.
    expect(callExpr(total, 'model.total', { amount: 100 })).toBeNull();
  });

  it('wires visibleIf to a negated hide expression', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'detail',
        type: 'textarea',
        label: { de: 'Details' },
        visibleIf: { '==': [{ var: 'needs' }, true] },
      },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(callExpr(cfg, 'hide', { needs: true })).toBe(false);
    expect(callExpr(cfg, 'hide', { needs: false })).toBe(true);
  });
});
