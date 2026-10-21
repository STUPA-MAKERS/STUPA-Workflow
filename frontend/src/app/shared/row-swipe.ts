import type { RowMenuSection, RowSwipeAction, ToastService } from '@stupa-makers/ui-kit';

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

/** What a delete with an undo needs from its page. */
export interface DeleteAfterUndo {
  /** The text of the toast, for example "Rechnung gelöscht.". */
  message: string;
  /** The label of the undo button. */
  undo: string;
  /** Send the delete request. */
  send: () => void;
  /** Put the row back into the list. */
  restore: () => void;
}

/**
 * A delete of a swipe: the page took the row out of the list already, and the request
 * goes only when the toast closes without the undo. The undo puts the row back and
 * sends nothing, so the server never sees a delete that the person took back.
 */
export function deleteAfterUndo(toast: ToastService, d: DeleteAfterUndo): void {
  toast.showAction({
    message: d.message,
    action: d.undo,
    variant: 'success',
    closed: (how) => (how === 'action' ? d.restore() : d.send()),
  });
}
