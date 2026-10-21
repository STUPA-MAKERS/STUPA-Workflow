import type { RowMenuSection, RowSwipeAction } from '@stupa-makers/ui-kit';

/**
 * The swipe action of a row from its row menu: the item with this id, with its label and
 * icon. Null when the menu has no such item (no permission, a state without it) or when
 * the item is disabled, so a swipe never offers what the menu does not.
 */
export function swipeFrom(
  sections: readonly RowMenuSection[],
  id: string,
  leaves = false,
): RowSwipeAction | null {
  for (const section of sections) {
    const item = section.items.find((i) => i.id === id);
    if (item?.icon && !item.disabledReason) return { id, label: item.label, icon: item.icon, leaves };
  }
  return null;
}
