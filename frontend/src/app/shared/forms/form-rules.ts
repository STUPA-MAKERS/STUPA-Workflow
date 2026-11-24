/**
 * The checks of a form across fields: the rules of a form version (specs 001670,
 * 001671) and the cost line under the Kostenaufstellung (specs 001630-001632).
 *
 * The functions mirror the backend `forms/validation.py` (`rule_context`, `rule_met`,
 * `broken_rules`, `cost_total`, `extract_promoted`). The shared fixture
 * `form-rules.fixture.json` runs in both test suites, so both sides give the same
 * broken rules. The server checks the rules again and stays the authority.
 */
import type { FieldType, FormFieldDef, FormRule } from '@core/api/models';
import { JsonLogicError, evalJsonLogic } from './jsonlogic';

/** A field as the checks read it: its key, its type and the settings they use. */
type RuleField = Pick<FormFieldDef, 'key' | 'type' | 'isPromoted' | 'promoteTarget' | 'validation'>;

const NUMERIC: ReadonlySet<FieldType> = new Set<FieldType>(['number', 'currency']);

/** A `computed` field that is the amount of the Antrag (spec 002840). */
export function isComputedAmount(f: Pick<FormFieldDef, 'type' | 'isPromoted' | 'promoteTarget'>): boolean {
  return f.type === 'computed' && !!f.isPromoted && f.promoteTarget === 'amount';
}

/** An amount rounded half up to whole cents, as the server rounds it (spec 002841). */
export function toCents(value: number): number {
  return Math.round(Number(`${value}e2`)) / 100;
}

/** A finite number from an answer, or null: a number, or a text that is one. */
export function finiteNumber(raw: unknown): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  if (typeof raw !== 'string' || raw.trim() === '') return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** The value of the first preferred offer of a position, or null. */
function preferredValue(position: unknown): number | null {
  if (!isRecord(position) || !Array.isArray(position['offers'])) return null;
  const preferred = (position['offers'] as unknown[]).find(
    (o) => isRecord(o) && o['preferred'] === true,
  );
  return isRecord(preferred) && typeof preferred['value'] !== 'boolean'
    ? finiteNumber(preferred['value'])
    : null;
}

/** The sum of the preferred offers of one `positions` answer, or null without one. */
export function positionsAnswerTotal(value: unknown): number | null {
  if (!Array.isArray(value)) return null;
  const found = value.map(preferredValue).filter((n): n is number => n !== null);
  return found.length ? found.reduce((sum, n) => sum + n, 0) : null;
}

/** The sum of the preferred offers of every `positions` field, or null without one. */
export function costTotal(
  fields: readonly RuleField[],
  data: Readonly<Record<string, unknown>>,
): number | null {
  const totals = fields
    .filter((f) => f.type === 'positions')
    .map((f) => positionsAnswerTotal(data[f.key]))
    .filter((n): n is number => n !== null);
  return totals.length ? totals.reduce((sum, n) => sum + n, 0) : null;
}

/**
 * The amount of the Antrag as the server makes it (`extract_promoted`): a filled-in
 * `funding` field wins; else the cost total of the positions, which a promoted numeric
 * field after them replaces. A computed amount field gives its value in whole cents from 0.
 */
export function promotedAmount(
  fields: readonly RuleField[],
  data: Readonly<Record<string, unknown>>,
): number | null {
  const promoted = fields.reduce<number | null>((amount, f) => {
    if (f.type === 'funding') return amount;
    if (f.type === 'positions') {
      const total = positionsAnswerTotal(data[f.key]);
      return total === null ? amount : (amount ?? 0) + total;
    }
    if (isComputedAmount(f)) {
      const raw = data[f.key];
      return typeof raw === 'number' && Number.isFinite(raw) && raw >= 0 ? toCents(raw) : amount;
    }
    const flagged = !!f.isPromoted && f.promoteTarget === 'amount' && NUMERIC.has(f.type);
    const value = flagged ? finiteNumber(data[f.key]) : null;
    return value === null ? amount : value;
  }, null);
  const fundings = fields
    .filter((f) => f.type === 'funding')
    .map((f) => (typeof data[f.key] === 'boolean' ? null : finiteNumber(data[f.key])));
  const funding = fundings.length ? fundings[fundings.length - 1] : null;
  return funding ?? promoted;
}

const RULE_NUMBER: ReadonlySet<FieldType> = new Set<FieldType>(['number', 'currency', 'funding']);

/**
 * The values that a rule reads: the answers, `amount` and `costTotal`. A numeric answer
 * that the form holds as a text (`"5"`) is read as its number, because a rule over a text
 * can never be evaluated and so always passes.
 */
export function ruleContext(
  fields: readonly RuleField[],
  data: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  const numbers = Object.fromEntries(
    fields
      .filter((f) => RULE_NUMBER.has(f.type) && typeof data[f.key] === 'string')
      .map((f) => [f.key, finiteNumber(data[f.key])] as const)
      .filter(([, n]) => n !== null),
  );
  return {
    ...data,
    ...numbers,
    amount: promotedAmount(fields, data),
    costTotal: costTotal(fields, data),
  };
}

/**
 * The answers meet the rule when its expression gives exactly `true`. An expression that
 * cannot be evaluated, for example because a field is still empty, counts as met, as on
 * the server.
 */
export function ruleMet(rule: Pick<FormRule, 'logic'>, ctx: Record<string, unknown>): boolean {
  try {
    return evalJsonLogic(rule.logic, ctx) === true;
  } catch (err) {
    if (err instanceof JsonLogicError) return true;
    throw err;
  }
}

/** The indexes of the rules that the answers do not meet. */
export function brokenRules(
  rules: readonly Pick<FormRule, 'logic'>[],
  fields: readonly RuleField[],
  data: Readonly<Record<string, unknown>>,
): readonly number[] {
  const ctx = ruleContext(fields, data);
  return rules.flatMap((rule, i) => (ruleMet(rule, ctx) ? [] : [i]));
}

/** The figures of the line under the Kostenaufstellung (specs 001630, 001631). */
export interface CostLine {
  /** The sum of the preferred offers. */
  readonly total: number;
  /** The filled-in funding, else the total. */
  readonly requested: number;
  /** The requested amount per participant, rounded to the cent, or null. */
  readonly perPerson: number | null;
}

/**
 * The cost line of a form: the total cost, the requested amount and, when the form has
 * a field for the number of participants with a value above 0, the amount per person.
 */
export function costLine(
  fields: readonly RuleField[],
  data: Readonly<Record<string, unknown>>,
): CostLine {
  const total = costTotal(fields, data) ?? 0;
  const funding = fields.find((f) => f.type === 'funding');
  const fundingValue = funding ? finiteNumber(data[funding.key]) : null;
  const requested = fundingValue ?? total;
  const counter = fields.find((f) => f.type === 'number' && f.validation?.participants === true);
  const people = counter ? finiteNumber(data[counter.key]) : null;
  const perPerson =
    people !== null && people > 0 ? Math.round((requested / people) * 100) / 100 : null;
  return { total, requested, perPerson };
}

/** Why an offer looks like a placeholder (spec 001640). */
export type PlaceholderReason = 'value' | 'label' | 'duplicate';

/** An offer as the placeholder check reads it. */
interface CheckedOffer {
  readonly label: string;
  readonly value: number | null;
}

/**
 * The placeholder reasons of each offer of one position (spec 001640): a value of 0 € or
 * 1 €, a label with fewer than 3 characters after trimming, or a label that another offer
 * of the position has too (without case and outer spaces). An offer that is still empty
 * has no reason, because the required check reports it.
 */
export function placeholderReasons(
  offers: readonly CheckedOffer[],
): readonly (readonly PlaceholderReason[])[] {
  const names = offers.map((o) => o.label.trim().toLocaleLowerCase());
  return offers.map((o, i): readonly PlaceholderReason[] => [
    ...(o.value === 0 || o.value === 1 ? (['value'] as const) : []),
    ...(names[i] !== '' && names[i].length < 3 ? (['label'] as const) : []),
    ...(names[i] !== '' && names.some((n, k) => k !== i && n === names[i])
      ? (['duplicate'] as const)
      : []),
  ]);
}
