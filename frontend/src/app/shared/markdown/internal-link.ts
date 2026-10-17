import type { Router } from '@angular/router';

/**
 * Route a click on an internal link of rendered Markdown through the Angular router, so
 * the app does not reload. An internal link has no `target` and an `href` that is an app
 * path (`/…`) or an anchor (`#…`). A click with a modifier key or another button, or an
 * event that is already handled, stays with the browser (new tab, new window).
 */
export function routeInternalLink(event: MouseEvent, router: Router | null): void {
  if (!router || event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = (event.target as Element | null)?.closest?.('a');
  const href = link?.getAttribute('href') ?? '';
  if (!link || link.hasAttribute('target') || !/^(\/(?!\/)|#)/.test(href)) return;
  event.preventDefault();
  // An anchor stays on the current page: the path of the router URL plus the fragment.
  void router.navigateByUrl(href.startsWith('#') ? router.url.split('#')[0] + href : href);
}
