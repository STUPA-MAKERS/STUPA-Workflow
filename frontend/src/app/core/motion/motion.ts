import type { ActivatedRouteSnapshot, ViewTransitionInfo } from '@angular/router';
import { MEDIA, matchesMedia } from '@stupa-makers/ui-kit';

/** True when the person asks the system for reduced motion. */
export function reducedMotion(): boolean {
  return matchesMedia(MEDIA.reducedMotion);
}

type TransitionDocument = Document & { startViewTransition?: (update: () => void) => unknown };

/**
 * Run a change of the whole page (for example the theme) as one cross-fade, so the
 * surfaces do not change colour one by one. Without the View Transitions API or with
 * reduced motion the change happens at once.
 */
export function withViewTransition(update: () => void): void {
  const doc = document as TransitionDocument;
  if (typeof doc.startViewTransition !== 'function' || reducedMotion()) {
    update();
    return;
  }
  doc.startViewTransition(update);
}

/**
 * The motion of a navigation.
 * - `section`: to another top-level section. The content fades through, the frame stays.
 * - `push` / `pop`: on a phone, one level deeper or back in the same section. The new
 *   page slides in from the end, or the old one slides out to it.
 * - `none`: everything else (a row on a desktop list, a filter in the query). No
 *   transition, so a list does not blink when a row opens.
 */
export type RouteMotion = 'section' | 'push' | 'pop' | 'none';

/** The path segments of a route tree, from the root to the leaf. */
export function routePath(snapshot: ActivatedRouteSnapshot | null): string[] {
  const out: string[] = [];
  for (let s = snapshot; s; s = s.firstChild) out.push(...s.url.map((u) => u.path));
  return out;
}

function startsWith(long: readonly string[], short: readonly string[]): boolean {
  return long.length > short.length && short.every((p, i) => long[i] === p);
}

export function routeMotion(
  from: readonly string[],
  to: readonly string[],
  phone: boolean,
): RouteMotion {
  if ((from[0] ?? '') !== (to[0] ?? '')) return 'section';
  if (!phone) return 'none';
  if (startsWith(to, from)) return 'push';
  if (startsWith(from, to)) return 'pop';
  return 'none';
}

/**
 * The `onViewTransitionCreated` hook of the router. It skips the transitions that must
 * not show, and names the kind on `<html data-motion>` for the styles in `styles.scss`.
 */
export function onRouteViewTransition({ transition, from, to }: ViewTransitionInfo): void {
  const phone = matchesMedia(MEDIA.phone);
  const kind = reducedMotion() ? 'none' : routeMotion(routePath(from), routePath(to), phone);
  if (kind === 'none') {
    transition.skipTransition();
    return;
  }
  const root = document.documentElement;
  root.dataset['motion'] = kind;
  void transition.finished.finally(() => {
    if (root.dataset['motion'] === kind) delete root.dataset['motion'];
  });
}
