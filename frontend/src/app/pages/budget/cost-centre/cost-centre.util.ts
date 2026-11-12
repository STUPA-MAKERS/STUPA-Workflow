import type { SelectOption } from '@stupa-makers/ui-kit';
import type { TranslationKey } from '@core/i18n/translations';
import type { BudgetTreeNode } from '../budget-tree.api';

/** The messages of the problem codes of a Kostenstelle write. */
const ERRORS: Readonly<Record<string, TranslationKey>> = {
  budget_key_exists: 'budget.cc.error.keyExists',
  plan_side_missing: 'budget.cc.error.sideMissing',
  side_in_plan: 'budget.cc.error.sideInPlan',
  plan_version_not_draft: 'budget.plan.error.locked',
  budget_has_children: 'budget.cc.error.hasChildren',
  budget_has_bookings: 'budget.cc.error.hasBookings',
  budget_has_applications: 'budget.cc.error.hasApplications',
  budget_in_plan: 'budget.cc.error.inPlan',
  fiscal_year_closed: 'budget.fy.closedError',
};

/** The message of a failed Kostenstelle write: the one of its problem code, else `fallback`. */
export function costCentreError(code: string, fallback: TranslationKey = 'budget.cc.error.failed'): TranslationKey {
  return ERRORS[code] ?? fallback;
}

/** A Kostenstelle is a direct child of a budget that has the plan switch on, so it has a side. */
export function hasSide(node: Pick<BudgetTreeNode, 'parentId'>, top: BudgetTreeNode | null): boolean {
  return !!top?.planEnabled && node.parentId === top.id;
}

/** The parents a new Kostenstelle can have: the budget, then each Kostenstelle of `nodes`. */
export function parentOptions(
  top: BudgetTreeNode,
  nodes: readonly Pick<BudgetTreeNode, 'id' | 'name' | 'pathKey'>[],
  budgetLabel: string,
): SelectOption[] {
  return [
    { value: top.id, label: `${top.name} (${budgetLabel})` },
    ...nodes.map((n) => ({ value: n.id, label: `${n.name} (${n.pathKey})` })),
  ];
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
