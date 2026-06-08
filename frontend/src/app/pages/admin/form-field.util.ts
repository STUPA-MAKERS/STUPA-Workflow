/**
 * Form-Builder-Helfer (T-34). Client-Validierung + Round-Trip eines
 * `FormFieldDef`, gespiegelt an `config_schemas.FormFieldDef` (model_validator):
 * gültiger Key, Pflicht-`options` für select/multiselect, Pflicht-`compute` für
 * `computed`, `promoteTarget` wenn `isPromoted`, sowie struktureller JsonLogic-
 * Check für `visibleIf`/`compute`. Der Server validiert beim Speichern erneut
 * autoritativ.
 */
import type { FieldType, FormFieldDef } from '@core/api/models';

export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * Gültige Ziel-Kennzahlen für »In Kennzahl übernehmen« (`promoteTarget`).
 * Backend wertet derzeit ausschließlich `amount` aus (→ `application.amount`,
 * Budget-Reservierung/-Buchung + Statistik). Daher Dropdown statt Freitext.
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
] as const;

/** Operatoren-Whitelist — Spiegel von `shared/forms/jsonlogic.ts` OPERATORS. */
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

/** Strukturelle JsonLogic-Prüfung: jeder Knoten genau ein bekannter Operator. */
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

/** Doppelte Feld-Keys über die ganze Form finden (UI-Hinweis). */
export function duplicateKeys(fields: FormFieldDef[]): string[] {
  const keys = fields.map((f) => f.key).filter(Boolean);
  return [...new Set(keys.filter((k) => keys.indexOf(k) !== keys.lastIndexOf(k)))].sort();
}

/** Kanonische Form: leere Optionals weglassen (= gespeicherte Definition). */
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
  if (field.isPromoted) {
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

/** Leeres Feld eines Typs erzeugen (mit den vom Typ geforderten Pflichtteilen). */
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

/** Default-Werte für eine neue Option (Form-Builder). */
export function blankOption(): { value: string; label: { de: string; en: string } } {
  return { value: '', label: { de: '', en: '' } };
}
