/**
 * The content that a long press may select, copy and open a menu on: text fields, the
 * values of a detail, the Markdown and chat texts, and every `.selectable` element. It
 * matches the selectable content of the touch rule in the kit (`base.scss`) and in
 * `styles.scss`.
 */
export const TOUCH_SELECTABLE =
  "input, textarea, [contenteditable]:not([contenteditable='false']), .selectable, .kv dd, .fld__value, .lfld__value, .mdv, .chat__text";

/**
 * Stops the menu of the browser after a long press on the interface of a touch screen.
 * A list row is a link, and Chrome on Android opens its link menu (copy the address,
 * download, share) on a long press; `-webkit-touch-callout` does nothing there. The
 * handler cancels a `contextmenu` that a touch pointer started, except on the content of
 * {@link TOUCH_SELECTABLE}. A mouse keeps its right click everywhere.
 *
 * It listens in the capture phase and does not stop the event, so the long press of the
 * kit (`appLongPress`, `appPressSelect`) still gets it and runs its own action.
 * Returns the function that removes the listeners.
 */
export function guardTouchContextMenu(doc: Document): () => void {
  let touch = false;
  const down = (e: PointerEvent): void => {
    touch = e.pointerType === 'touch';
  };
  const menu = (e: Event): void => {
    if (!touch) return;
    const target = e.target;
    if (target instanceof Element && target.closest(TOUCH_SELECTABLE)) return;
    e.preventDefault();
  };
  doc.addEventListener('pointerdown', down, { capture: true, passive: true });
  doc.addEventListener('contextmenu', menu, { capture: true });
  return () => {
    doc.removeEventListener('pointerdown', down, { capture: true });
    doc.removeEventListener('contextmenu', menu, { capture: true });
  };
}
