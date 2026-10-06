import type { Router, UrlTree } from '@angular/router';

/** The query parameter that tells the beamer which page opened it. */
export const BEAMER_FROM_PARAM = 'from';

/**
 * The beamer of a meeting, with the current page as the place to go back to. The beamer
 * reads `?from=` (see `beamerOrigin`) for its exit control and for Escape.
 */
export function beamerUrl(router: Router, meetingId: string): UrlTree {
  return router.createUrlTree(['/voting/beamer', meetingId], {
    queryParams: { [BEAMER_FROM_PARAM]: router.url },
  });
}

/**
 * A `?from=` value that is safe to go back to: an app path (`/…`), never a URL of
 * another origin (`//host`, `https:`, `/\\host`) and never the beamer itself. Anything
 * else is `null`, and the beamer uses its own default.
 */
export function beamerOrigin(from: string | null): string | null {
  if (!from || !from.startsWith('/')) return null;
  if (from.startsWith('//') || from.startsWith('/\\')) return null;
  if (from.startsWith('/voting/beamer')) return null;
  return from;
}
