/** What the viewport of the installed app adds: no pinch zoom and no zoom on focus. */
export const NO_ZOOM = 'maximum-scale=1, user-scalable=no';

/**
 * Stops the page zoom in the installed app (PWA), because a native app does not zoom as
 * a whole page and a pinch moved the bars out of the screen. A browser tab keeps the zoom
 * (WCAG 1.4.4). The function adds {@link NO_ZOOM} to the viewport tag, which Chrome on
 * Android obeys, and cancels the `gesturestart` of iOS, because WebKit ignores
 * `user-scalable=no`. The double-tap zoom stops with `touch-action: manipulation` on the
 * page (`styles.scss`). Does nothing in a browser tab.
 * Returns the function that removes the listener and restores the viewport tag.
 */
export function lockInstalledAppZoom(doc: Document, installed: boolean): () => void {
  if (!installed) return () => undefined;
  const meta = doc.querySelector<HTMLMetaElement>('meta[name="viewport"]');
  const before = meta?.content;
  if (meta && before !== undefined && !before.includes('user-scalable')) {
    meta.content = `${before}, ${NO_ZOOM}`;
  }
  const gesture = (e: Event): void => e.preventDefault();
  doc.addEventListener('gesturestart', gesture, { passive: false });
  return () => {
    doc.removeEventListener('gesturestart', gesture);
    if (meta && before !== undefined) meta.content = before;
  };
}
