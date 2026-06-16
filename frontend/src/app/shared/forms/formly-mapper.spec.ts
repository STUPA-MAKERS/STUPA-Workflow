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

  it('maps currency to a currency input and copies validation bounds', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'amount',
        type: 'currency',
        label: { de: 'Betrag' },
        validation: { min: 0, max: 100, minLen: 1, maxLen: 5, pattern: '\\d+' },
      },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.props?.type).toBe('currency');
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

  it('renders section markers as group headings (not editable fields)', () => {
    const fields: FormFieldDef[] = [
      { key: 'section_1', type: 'section', label: { de: 'Schritt 1' } },
      { key: 'name', type: 'text', label: { de: 'Name' } },
    ];
    const out = toFormlyFields(fields, 'de');
    expect(out).toHaveLength(2);
    // Abschnitts-Marker → keyless display-Überschrift; echtes Feld unverändert.
    expect(out[0].type).toBe('display');
    expect(out[0].props?.['heading']).toBe(true);
    expect(out[0].props?.['label']).toBe('Schritt 1');
    expect(out[0].key).toBeUndefined();
    expect(out[1].key).toBe('name');
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

  it('hide expression reads extraContext (non-field variables)', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'reason',
        type: 'textarea',
        label: { de: 'Begründung' },
        visibleIf: { '==': [{ var: 'has_budget' }, true] },
      },
    ];
    const [cfg] = toFormlyFields(fields, 'de', { has_budget: true });
    // No model on the field → extraContext supplies has_budget.
    const hide = cfg.expressions?.['hide'] as (f: FormlyFieldConfig) => unknown;
    expect(hide({} as FormlyFieldConfig)).toBe(false);
  });

  it('maps a section heading and includes the help description', () => {
    const fields: FormFieldDef[] = [
      { key: 's', type: 'section', label: { de: 'Block' }, help: { de: 'Erläuterung' } },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.type).toBe('display');
    expect(cfg.props?.['heading']).toBe(true);
    expect(cfg.props?.['label']).toBe('Block');
    expect(cfg.props?.['description']).toBe('Erläuterung');
  });

  it('maps a markdown field without help, falling back to label as text', () => {
    const fields: FormFieldDef[] = [{ key: 'note', type: 'markdown', label: { de: 'Nur Label' } }];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.type).toBe('display');
    expect(cfg.props?.['text']).toBe('Nur Label');
    // display fields never carry required even if flagged.
    expect(cfg.props?.['required']).toBeUndefined();
  });

  it('does not set required on display-style fields', () => {
    const fields: FormFieldDef[] = [
      { key: 'tbl', type: 'table', label: { de: 'Tabelle' }, required: true },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.type).toBe('display');
    expect(cfg.props?.['text']).toContain('Tabellen-Eingabe');
    expect(cfg.props?.['required']).toBeUndefined();
  });

  it('maps a file field to a text input', () => {
    const fields: FormFieldDef[] = [{ key: 'doc', type: 'file', label: { de: 'Datei' } }];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.type).toBe('input');
    expect(cfg.props?.type).toBe('text');
  });

  it('maps a date field to a date input', () => {
    const fields: FormFieldDef[] = [{ key: 'd', type: 'date', label: { de: 'Datum' } }];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.props?.type).toBe('date');
  });

  it('forwards minOffers/minPositions for positions fields', () => {
    const fields: FormFieldDef[] = [
      {
        key: 'costs',
        type: 'positions',
        label: { de: 'Kosten' },
        validation: { minOffers: 2, minPositions: 3 },
      },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.type).toBe('positions');
    expect(cfg.props?.['minOffers']).toBe(2);
    expect(cfg.props?.['minPositions']).toBe(3);
  });

  it('omits positions min props when validation does not set them', () => {
    const fields: FormFieldDef[] = [
      { key: 'costs', type: 'positions', label: { de: 'Kosten' }, validation: {} },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.props?.['minOffers']).toBeUndefined();
    expect(cfg.props?.['minPositions']).toBeUndefined();
  });

  it('produces no expressions when there is neither visibleIf nor compute', () => {
    const fields: FormFieldDef[] = [{ key: 'plain', type: 'text', label: { de: 'X' } }];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.expressions).toBeUndefined();
  });

  it('does not wire a compute expression for a computed field without compute', () => {
    const fields: FormFieldDef[] = [{ key: 'c', type: 'computed', label: { de: 'C' } }];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(cfg.props?.['computed']).toBe(true);
    expect(cfg.expressions).toBeUndefined();
  });

  it('rethrows non-JsonLogicError from a computed expression', () => {
    // compute is a proxy whose ownKeys trap throws a TypeError inside evalJsonLogic.
    const boom = new Proxy(
      {},
      {
        ownKeys() {
          throw new TypeError('boom');
        },
      },
    ) as unknown as Record<string, unknown>;
    const fields: FormFieldDef[] = [
      { key: 'total', type: 'computed', label: { de: 'Summe' }, compute: boom },
    ];
    const [cfg] = toFormlyFields(fields, 'de');
    expect(() => callExpr(cfg, 'model.total', {})).toThrow(TypeError);
  });

  it('resolves labels via the requested language with de/first fallbacks', () => {
    const fields: FormFieldDef[] = [
      { key: 'a', type: 'text', label: { de: 'DE', en: 'EN' } },
    ];
    expect(toFormlyFields(fields, 'en')[0].props?.label).toBe('EN');
    expect(toFormlyFields(fields, 'fr')[0].props?.label).toBe('DE');
  });
});
