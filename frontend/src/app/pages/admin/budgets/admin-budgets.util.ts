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

/**
 * The reason why a fiscal year cannot be deleted. The server names exactly one of
 * `bookings`, `allocations` or `applications` in the detail of its 409.
 */
export function fyBlockerKey(detail: string | undefined): TranslationKey {
  if (detail?.includes('bookings')) return 'budget.tree.fyBlocked.bookings';
  if (detail?.includes('allocations')) return 'budget.tree.fyBlocked.allocations';
  if (detail?.includes('applications')) return 'budget.tree.fyBlocked.applications';
  return 'budget.tree.fyBlocked.generic';
}
