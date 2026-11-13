import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';

/** One step of the edit form: its name and its Gremium, '' for none. */
export interface StepDraft {
  readonly name: string;
  readonly gremiumId: string;
}

/** The start day must exist in every month (the server takes 1 to 28). */
const MAX_DAY = 28;

/** A part of the start of the fiscal year as a whole number in its range: month 1 to 12, day 1 to 28. */
export function clampCutoff(field: 'day' | 'month', value: string | number): number {
  const n = Math.trunc(Number(value)) || 1;
  return Math.min(field === 'month' ? 12 : MAX_DAY, Math.max(1, n));
}

/** "01.03.": the start of the fiscal year of a budget. */
export function cutoffLabel(budget: Pick<BudgetTreeNode, 'fiscalStartDay' | 'fiscalStartMonth'>): string {
  const two = (n: number): string => String(n).padStart(2, '0');
  return `${two(budget.fiscalStartDay)}.${two(budget.fiscalStartMonth)}.`;
}

/** The steps with the step at `index` moved one place up (`-1`) or down (`1`). */
export function movedStep(steps: readonly StepDraft[], index: number, by: -1 | 1): readonly StepDraft[] {
  const to = index + by;
  if (to < 0 || to >= steps.length) return steps;
  return steps.map((s, i) => (i === index ? steps[to] : i === to ? steps[index] : s));
}

/** The steps as the server takes them: trimmed names, and `null` for no Gremium. */
export function stepsToSave(steps: readonly StepDraft[]): readonly { readonly name: string; readonly gremiumId: Uuid | null }[] {
  return steps.map((s) => ({ name: s.name.trim(), gremiumId: (s.gremiumId || null) as Uuid | null }));
}

/** The messages of the problem codes of a refused fiscal-year write. */
const FY_BLOCKERS: Readonly<Record<string, TranslationKey>> = {
  fiscal_year_has_bookings: 'budget.tree.fyBlocked.bookings',
  fiscal_year_has_allocations: 'budget.tree.fyBlocked.allocations',
  fiscal_year_has_applications: 'budget.tree.fyBlocked.applications',
  fiscal_year_has_plan: 'budget.tree.fyBlocked.plan',
  fiscal_year_closed: 'budget.fy.closedError',
  plan_in_progress: 'budget.plan.error.inProgress',
};

/** The message of a refused fiscal-year write: the one of its problem code, else `fallback`. */
export function fyBlockerKey(code: string, fallback: TranslationKey): TranslationKey {
  return FY_BLOCKERS[code] ?? fallback;
}

const MIN_YEAR = 1900;
const MAX_YEAR = 2200;

/** The text of a year field is no whole year from 1900 to 2200. */
export function yearProblem(text: string): boolean {
  const year = Number(text);
  return !text.trim() || !Number.isInteger(year) || year < MIN_YEAR || year > MAX_YEAR;
}

/** The year a new fiscal year starts with: the year after the newest one, else `thisYear`. */
export function nextYear(years: readonly { readonly year: number }[], thisYear: number): number {
  return years.length ? Math.max(...years.map((y) => y.year)) + 1 : thisYear;
}
