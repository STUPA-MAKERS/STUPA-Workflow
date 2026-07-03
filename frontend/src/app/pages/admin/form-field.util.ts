/**
 * Form-builder helper. Client-side validation + round-trip of a `FormFieldDef`,
 * mirroring `config_schemas.FormFieldDef` (model_validator): valid key, required
 * `options` for select/multiselect, required `compute` for `computed`,
 * `promoteTarget` when `isPromoted`, plus a structural JsonLogic check for
 * `visibleIf`/`compute`. The server re-validates authoritatively on save.
 */
import type { FieldType, FormFieldDef } from '@core/api/models';

export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * Valid promote targets (`promoteTarget`). The backend currently only evaluates
 * `amount` (→ `application.amount`, budget reservation/booking + statistics),
 * hence a dropdown instead of free text.
 */
export const PROMOTE_TARGETS = ['amount'] as const;
export type PromoteTarget = (typeof PROMOTE_TARGETS)[number];

export const FIELD_TYPES: readonly FieldType[] = [
  'text',
  'textarea',
  'number',
  'currency',
  'date',
  'select',
  'multiselect',
  'checkbox',
  'file',
  'table',
  'markdown',
  'computed',
  'positions',
  'section',
] as const;

/** Operator whitelist — mirror of `shared/forms/jsonlogic.ts` OPERATORS. */
const JSONLOGIC_OPERATORS = new Set([
  '==',
  '!=',
  '>',
  '>=',
  '<',
  '<=',
  'and',
  'or',
  'not',
  'var',
  '+',
  '-',
  '*',
  '/',
  'in',
]);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Structural JsonLogic check: each node is exactly one known operator. */
export function validateJsonLogic(expr: unknown): boolean {
  if (!isRecord(expr)) return true; // Literal
  const keys = Object.keys(expr);
  if (keys.length !== 1) return false;
  const op = keys[0];
  if (!JSONLOGIC_OPERATORS.has(op)) return false;
  if (op === 'var') return true;
  const raw = expr[op];
  const args = Array.isArray(raw) ? raw : [raw];
  return args.every((a) => validateJsonLogic(a));
}

export interface FieldValidationResult {
  valid: boolean;
  errors: string[];
}

export function validateFormField(field: FormFieldDef): FieldValidationResult {
  const errors: string[] = [];

  if (!KEY_PATTERN.test(field.key)) {
    errors.push(`invalid field key: ${JSON.stringify(field.key)}`);
  }
  if (!FIELD_TYPES.includes(field.type)) {
    errors.push(`unknown field type: ${JSON.stringify(field.type)}`);
  }
  if (!field.label || !field.label['de']?.trim()) {
    errors.push('label (de) is required');
  }
  if ((field.type === 'select' || field.type === 'multiselect') && !field.options?.length) {
    errors.push(`options are required for type '${field.type}'`);
  }
  if (field.type === 'computed' && !field.compute) {
    errors.push("compute is required for type 'computed'");
  }
  if (field.isPromoted && !field.promoteTarget) {
    errors.push('promoteTarget is required when isPromoted is true');
  }
  if (field.visibleIf && !validateJsonLogic(field.visibleIf)) {
    errors.push('visibleIf is not a valid JsonLogic expression');
  }
  if (field.compute && !validateJsonLogic(field.compute)) {
    errors.push('compute is not a valid JsonLogic expression');
  }

  return { valid: errors.length === 0, errors };
}

/** Find duplicate field keys across the whole form (UI hint). */
export function duplicateKeys(fields: FormFieldDef[]): string[] {
  const keys = fields.map((f) => f.key).filter(Boolean);
  return [...new Set(keys.filter((k) => keys.indexOf(k) !== keys.lastIndexOf(k)))].sort();
}

/** Canonical form: drop empty optionals (= stored definition). */
export function normalizeFormField(field: FormFieldDef): FormFieldDef {
  const out: FormFieldDef = { key: field.key, type: field.type, label: field.label };
  if (field.help && Object.keys(field.help).length > 0) out.help = field.help;
  if (field.required) out.required = true;
  if (field.validation && Object.values(field.validation).some((v) => v != null && v !== '')) {
    out.validation = field.validation;
  }
  if (field.options && field.options.length > 0) out.options = field.options;
  if (field.visibleIf) out.visibleIf = field.visibleIf;
  if (field.compute) out.compute = field.compute;
  if (field.isPII) out.isPII = true;
  // Only numeric fields may carry `isPromoted` (backend rejects otherwise, 422).
  // `positions` promotes into `amount` automatically — without a flag.
  if (field.isPromoted && (field.type === 'number' || field.type === 'currency')) {
    out.isPromoted = true;
    if (field.promoteTarget) out.promoteTarget = field.promoteTarget;
  }
  return out;
}

export function serializeFields(fields: FormFieldDef[]): string {
  return JSON.stringify(fields.map(normalizeFormField), null, 2);
}

export function parseFields(json: string): FormFieldDef[] {
  const parsed = JSON.parse(json) as FormFieldDef[];
  return parsed.map(normalizeFormField);
}

/** Create an empty field of a type (with the parts the type requires). */
export function blankField(type: FieldType = 'text', key = ''): FormFieldDef {
  const field: FormFieldDef = { key, type, label: { de: '', en: '' } };
  if (type === 'select' || type === 'multiselect') {
    field.options = [{ value: '', label: { de: '', en: '' } }];
  }
  if (type === 'computed') {
    field.compute = { var: '' };
  }
  return field;
}

/** Default values for a new option (form builder). */
export function blankOption(): { value: string; label: { de: string; en: string } } {
  return { value: '', label: { de: '', en: '' } };
}

/**
 * Question group in the editor: a titled container mapping to exactly one wizard
 * step (= one effective form section). The title is the step heading. `fields`
 * holds **only** question fields (no `section` markers — those are the
 * serialization primitive, produced/consumed when packing/unpacking).
 */
export interface QuestionGroup {
  titleDe: string;
  titleEn: string;
  fields: FormFieldDef[];
}

/**
 * Flat `fields[]` (backend format) → groups, splitting at every `section` marker.
 * Fields **before** the first marker form an implicit first group (empty default
 * title). Without markers exactly one group with an empty title results. Mirrors
 * `validation._split_sections` (backend) so the editor and the effective form see
 * the same step split.
 */
export function groupsFromFields(fields: FormFieldDef[]): QuestionGroup[] {
  const groups: QuestionGroup[] = [];
  let current: QuestionGroup = { titleDe: '', titleEn: '', fields: [] };
  let opened = false;
  for (const f of fields) {
    if (f.type === 'section') {
      // Marker closes the running group (if it already had content/a marker)
      // and opens a new one with the marker title.
      if (opened || current.fields.length > 0) {
        groups.push(current);
      }
      current = {
        titleDe: f.label?.['de'] ?? '',
        titleEn: f.label?.['en'] ?? '',
        fields: [],
      };
      opened = true;
      continue;
    }
    current.fields.push(f);
  }
  groups.push(current);
  return groups;
}

/**
 * Groups → flat `fields[]` (backend format). Each group becomes a leading
 * `section` marker (auto-key `section_N`) followed by its question fields. An
 * **implicit first group without a title** is serialized **without** a marker (it
 * is the default `main` section) — so a marker-less form is preserved exactly
 * (round-trip). Every further group, and a first group **with** a title, gets a
 * marker. An empty group (title only) serializes to just its marker.
 */
export function groupsToFields(groups: QuestionGroup[]): FormFieldDef[] {
  const out: FormFieldDef[] = [];
  let n = 0;
  groups.forEach((g, gi) => {
    const hasTitle = !!(g.titleDe || g.titleEn);
    // First group without a title: no marker (implicit main section).
    const needsMarker = gi > 0 || hasTitle;
    if (needsMarker) {
      n += 1;
      out.push({
        key: `section_${n}`,
        type: 'section',
        label: { de: g.titleDe, en: g.titleEn },
      });
    }
    out.push(...g.fields);
  });
  return out;
}
