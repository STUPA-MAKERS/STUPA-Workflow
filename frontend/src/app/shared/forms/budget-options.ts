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
export function budgetOptionTree(options: readonly FieldOption[], lang: Lang): BudgetTreeNode[] {
  const byId = new Map<string, BudgetTreeNode>();
  for (const o of options) {
    const label = resolveI18n(o.label, lang);
    const parts = LABEL.exec(label);
    const key = o.key ?? '';
    byId.set(o.value, {
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
    });
  }
  const roots: BudgetTreeNode[] = [];
  for (const n of byId.values()) {
    const parent = n.parentId ? byId.get(n.parentId) : undefined;
    if (parent) {
      parent.children.push(n);
    } else {
      n.parentId = null;
      roots.push(n);
    }
  }
  return roots;
}
