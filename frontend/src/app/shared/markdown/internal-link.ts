import type { Router } from '@angular/router';

/** The paths that the server answers and the app does not. The router has no route for
 *  them, so a click on one stays with the browser. */
const SERVER_PATH_RE = /^\/(?:api|s|\.well-known)(?:[/?#]|$)/;

/**
 * Route a click on an internal link of rendered Markdown through the Angular router, so
 * the app does not reload. An internal link has no `target` and an `href` that is an app
 * path (`/…`) or an anchor (`#…`). A click with a modifier key or another button, or an
 * event that is already handled, stays with the browser (new tab, new window).
 *
 * A server path (`/api/…`, a share link `/s/…`, `/.well-known/…`) also stays with the
 * browser, because the router has no route for it.
 */
export function routeInternalLink(event: MouseEvent, router: Router | null): void {
  if (!router || event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = (event.target as Element | null)?.closest?.('a');
  const href = link?.getAttribute('href') ?? '';
  if (!link || link.hasAttribute('target') || !/^(\/(?!\/)|#)/.test(href)) return;
  if (SERVER_PATH_RE.test(href)) return;
  event.preventDefault();
  // An anchor stays on the current page: the path of the router URL plus the fragment.
  void router.navigateByUrl(href.startsWith('#') ? router.url.split('#')[0] + href : href);
}
