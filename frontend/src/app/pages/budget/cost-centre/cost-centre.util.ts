import type { TranslationKey } from '@core/i18n/translations';
import type { BudgetTreeNode } from '../budget-tree.api';

/** The messages of the problem codes of a Kostenstelle write. */
const ERRORS: Readonly<Record<string, TranslationKey>> = {
  budget_key_exists: 'budget.cc.error.keyExists',
  plan_side_missing: 'budget.cc.error.sideMissing',
  side_in_plan: 'budget.cc.error.sideInPlan',
  plan_version_locked: 'budget.plan.error.locked',
  budget_has_children: 'budget.cc.error.hasChildren',
  budget_has_bookings: 'budget.cc.error.hasBookings',
  budget_has_applications: 'budget.cc.error.hasApplications',
  budget_in_plan: 'budget.cc.error.inPlan',
  allocation_from_plan: 'budget.cc.error.allocationFromPlan',
  side_not_settable: 'budget.cc.error.sideNotSettable',
  children_allocation_exceeds_parent: 'budget.cc.error.aboveParent',
  parent_allocation_below_children: 'budget.cc.error.belowChildren',
  plan_amount_too_large: 'budget.plan.error.amountTooLarge',
  fiscal_year_closed: 'budget.fy.closedError',
};

/** The largest length of the name of a Kostenstelle. */
export const NAME_MAX = 200;
const KEY_MAX = 64;
const KEY_PATTERN = /^[A-Za-z0-9]+$/;

/** A key that is not empty holds something other than letters and digits, or is too long. */
export function keyProblem(key: string): boolean {
  return !!key && (key.length > KEY_MAX || !KEY_PATTERN.test(key));
}

/** The message of a failed Kostenstelle write: the one of its problem code, else `fallback`. */
export function costCentreError(code: string, fallback: TranslationKey = 'budget.cc.error.failed'): TranslationKey {
  return ERRORS[code] ?? fallback;
}

/**
 * The name of the level of a node: the top level is a Haushalt, a node directly below it is
 * a Titel, and a node below a Titel is a Kostenstelle.
 */
export function levelKey(node: Pick<BudgetTreeNode, 'id' | 'parentId'>, top: Pick<BudgetTreeNode, 'id'> | null): TranslationKey {
  if (!node.parentId) return 'budget.cc.budget';
  return node.parentId === top?.id ? 'budget.cc.headingTitle' : 'budget.cc.heading';
}

/** The label of the action that creates a node below `parentId`: a Titel directly below the Haushalt. */
export function createKey(parentId: string, top: Pick<BudgetTreeNode, 'id'> | null): TranslationKey {
  return !parentId || parentId === top?.id ? 'budget.cc.createTitle' : 'budget.cc.create';
}

/** A Kostenstelle is a direct child of a budget that has the plan switch on, so it has a side. */
export function hasSide(node: Pick<BudgetTreeNode, 'parentId'>, top: BudgetTreeNode | null): boolean {
  return !!top?.planEnabled && node.parentId === top.id;
}

/** The node and each node below it, in tree order. */
export function withDescendants(node: BudgetTreeNode): readonly BudgetTreeNode[] {
  return [node, ...node.children.flatMap(withDescendants)];
}

/** The node with this id in a forest, or `null`. */
export function findNode(forest: readonly BudgetTreeNode[], id: string): BudgetTreeNode | null {
  return forest.flatMap(withDescendants).find((n) => n.id === id) ?? null;
}

/** The forest without each inactive node and the nodes below it. */
export function activeOnly(forest: readonly BudgetTreeNode[]): readonly BudgetTreeNode[] {
  return forest.filter((n) => n.active).map((n) => ({ ...n, children: activeOnly(n.children) }));
}

/** The Kostenstelle has a booking or an Antrag in the fiscal year. */
export function usedIn(node: BudgetTreeNode, fiscalYearId: string): boolean {
  const view = node.byFiscalYear.find((a) => a.fiscalYearId === fiscalYearId);
  return !!view && [view.bound, view.requested, view.expended, view.income].some((v) => Number(v) !== 0);
}

/**
 * The Kostenstellen that a picker offers: no inactive one and none below it. For a fiscal
 * year with a plan version in force a budget offers only a Kostenstelle that the plan holds
 * or that has a booking or an Antrag in that year. `yearsOf` names the fiscal years the
 * picker works in, by budget; the first with a plan in force counts.
 */
export function pickable(
  forest: readonly BudgetTreeNode[],
  yearsOf: (top: BudgetTreeNode) => readonly string[],
): readonly BudgetTreeNode[] {
  const members = (nodes: readonly BudgetTreeNode[], fy: string): readonly BudgetTreeNode[] =>
    nodes
      .filter((n) => !!n.plannedIn?.includes(fy) || usedIn(n, fy))
      .map((n) => ({ ...n, children: members(n.children, fy) }));
  return activeOnly(forest).map((top) => {
    const fy = yearsOf(top).find((id) => !!id && !!top.plannedIn?.includes(id));
    return fy ? { ...top, children: members(top.children, fy) } : top;
  });
}
