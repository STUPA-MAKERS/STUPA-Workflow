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
