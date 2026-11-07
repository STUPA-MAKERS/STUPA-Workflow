import type { FieldOption, Lang } from '@core/api/models';
import type { BudgetTreeNode } from '../../pages/budget/budget-tree.api';
import { resolveI18n } from './i18n-text';

/** "Kultur (VS-1)": the name, then the path key in parentheses at the end. */
const LABEL = /^(.*) \(([^()]*)\)$/;

/**
 * The options of a `budget_select` field as the cost-centre tree of the tree picker.
 *
 * The server sends the cost centres as flat options in the order of their path keys, each
 * with its parent, its key and its own colour. The label is `name (path key)`; a label in
 * another shape is the name, and the key is the path key then. A parent without an option
 * makes its child a root. The nodes carry no figures, so the picker shows no free amounts.
 */
export function budgetOptionTree(
  options: readonly FieldOption[],
  lang: Lang,
): readonly BudgetTreeNode[] {
  const byId = new Map(options.map((o) => [o.value, optionNode(o, lang)] as const));
  const nodes = [...byId.values()];
  const isRoot = (n: BudgetTreeNode): boolean => !(n.parentId && byId.has(n.parentId));
  const withChildren = (n: BudgetTreeNode): BudgetTreeNode => ({
    ...n,
    children: nodes.filter((c) => !isRoot(c) && c.parentId === n.id).map(withChildren),
  });
  return nodes.filter(isRoot).map((n) => withChildren({ ...n, parentId: null }));
}

/** One option as a tree node without children. */
function optionNode(o: FieldOption, lang: Lang): BudgetTreeNode {
  const label = resolveI18n(o.label, lang);
  const parts = LABEL.exec(label);
  const key = o.key ?? '';
  return {
    id: o.value,
    parentId: o.parentId ?? null,
    gremiumId: null,
    key,
    pathKey: parts ? parts[2] : key,
    name: parts ? parts[1] : label,
    currency: 'EUR',
    active: true,
    color: o.color ?? null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
  };
}
