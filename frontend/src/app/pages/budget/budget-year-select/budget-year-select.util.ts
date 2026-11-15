import type { BudgetYear } from '../budget-tree.api';

/**
 * The pair a form starts with: the current year of `preferBudgetId`, else of the budget
 * the person chose last, else of the first budget. A budget without a current year gives
 * its first year.
 */
export function defaultBudgetYear(
  pairs: readonly BudgetYear[],
  preferBudgetId: string,
  lastBudgetId: string,
): BudgetYear | null {
  const of = (budgetId: string): BudgetYear | null => {
    const own = pairs.filter((p) => p.budgetId === budgetId);
    return own.find((p) => p.current) ?? own[0] ?? null;
  };
  return (
    of(preferBudgetId) ?? of(lastBudgetId) ?? pairs.find((p) => p.current) ?? pairs[0] ?? null
  );
}

/** "VS-Mittel 2026/27": the text of a pair. */
export function budgetYearLabel(pair: BudgetYear): string {
  return `${pair.budgetName} ${pair.display}`;
}

/**
 * A past year takes a booking only with a date in the year, any other year takes every
 * date and none. `date` is ISO (`YYYY-MM-DD`) or ''.
 */
export function dateFitsBudgetYear(pair: BudgetYear | null, date: string): boolean {
  return !pair?.past || (!!date && pair.startDate <= date && date <= pair.endDate);
}
