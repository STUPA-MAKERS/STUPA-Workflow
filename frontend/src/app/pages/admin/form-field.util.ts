/**
 * Form-builder helper: client-side validation and round-trip of a `FormFieldDef`.
 *
 * The rules mirror `config_schemas.FormFieldDef` (model_validator). A field needs a valid
 * key. A select or multiselect field needs `options`. A `computed` field needs `compute`.
 * A field with `isPromoted` needs `promoteTarget`. The helper also checks the structure of
 * the `visibleIf` and `compute` JsonLogic. The server validates again on save and stays
 * authoritative.
 */
import type { FieldType, FormFieldDef } from '@core/api/models';

export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * Valid values for `promoteTarget`. The backend evaluates `amount` only. That value feeds
 * `application.amount`, the budget reservation, the booking, and the statistics. For that
 * reason the UI shows a dropdown and not free text.
 */
export const PROMOTE_TARGETS = ['amount'] as const;
export type PromoteTarget = (typeof PROMOTE_TARGETS)[number];

export const FIELD_TYPES: readonly FieldType[] = [
  'text',
  'textarea',
  'number',
  'currency',
  'date',
  'daterange',
  'email',
  'iban',
  'select',
  'multiselect',
  'gremium_select',
  'budget_select',
  'checkbox',
  'file',
  'table',
  'markdown',
  'computed',
  'positions',
  'section',
] as const;

/** Operator whitelist. Mirrors `OPERATORS` in `shared/forms/jsonlogic.ts`. */
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
  if (!isRecord(expr)) return true; // a literal is always valid
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

/** Canonical form: drop empty optionals. This is the stored definition. */
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
  // Only a numeric field may carry `isPromoted`. The backend sends 422 for other types.
  // A `positions` field promotes into `amount` automatically, without a flag.
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

export function blankOption(): { value: string; label: { de: string; en: string } } {
  return { value: '', label: { de: '', en: '' } };
}

/**
 * Question group in the editor: a titled container that maps to exactly one wizard step,
 * which is one section of the effective form. The title is the step heading. `fields`
 * holds question fields **only**. A `section` marker is the serialization primitive. The
 * pack and unpack steps produce and consume such markers.
 */
export interface QuestionGroup {
  titleDe: string;
  titleEn: string;
  fields: FormFieldDef[];
}

/**
 * Split the flat `fields[]` backend format into groups at every `section` marker.
 *
 * Fields **before** the first marker form an implicit first group with an empty title. A
 * form without markers gives exactly one group with an empty title. This mirrors
 * `validation._split_sections` in the backend, so the editor and the effective form use
 * the same step split.
 */
export function groupsFromFields(fields: FormFieldDef[]): QuestionGroup[] {
  const groups: QuestionGroup[] = [];
  let current: QuestionGroup = { titleDe: '', titleEn: '', fields: [] };
  let opened = false;
  for (const f of fields) {
    if (f.type === 'section') {
      // A marker closes the running group when that group has content or a marker
      // already. The marker then opens a new group with its own title.
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
 * Pack groups into the flat `fields[]` backend format.
 *
 * Each group becomes a leading `section` marker with the auto-key `section_N`, followed
 * by its question fields. An **implicit first group without a title** gets **no** marker,
 * because it is the default `main` section. A form without markers therefore round-trips
 * exactly. Every further group gets a marker, and so does a first group **with** a title.
 * An empty group with a title only serializes to its marker alone.
 */
export function groupsToFields(groups: QuestionGroup[]): FormFieldDef[] {
  const out: FormFieldDef[] = [];
  let n = 0;
  groups.forEach((g, gi) => {
    const hasTitle = !!(g.titleDe || g.titleEn);
    // A first group without a title gets no marker. It is the implicit main section.
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
