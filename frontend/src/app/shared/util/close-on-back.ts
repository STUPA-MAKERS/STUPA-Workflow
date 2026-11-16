import { DOCUMENT } from '@angular/common';
import { DestroyRef, effect, inject, signal, untracked, type Signal } from '@angular/core';

/**
 * Give an open dialog an entry in the history of the browser, so that "back" closes the
 * dialog and the page behind it stays (§ 000931). Call it in an injection context.
 *
 * The entry keeps the URL and the state of the page, so the router reads the step back as
 * a navigation to the URL that it already shows and does nothing. A close by a button
 * takes the entry away again, so the history does not grow with each dialog.
 */
export function closeOnBack(isOpen: Signal<boolean>, close: () => void): void {
  const view = inject(DOCUMENT).defaultView;
  if (!view) return;
  const pushed = signal(false);
  const onPop = (): void => {
    if (!pushed()) return;
    pushed.set(false);
    close();
  };
  view.addEventListener('popstate', onPop);
  inject(DestroyRef).onDestroy(() => view.removeEventListener('popstate', onPop));
  effect(() => {
    const open = isOpen();
    untracked(() => {
      if (open === pushed()) return;
      pushed.set(open);
      if (open) view.history.pushState(view.history.state, '');
      else view.history.back();
    });
  });
}
