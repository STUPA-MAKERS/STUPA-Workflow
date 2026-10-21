import { inject } from '@angular/core';
import { Router, type ActivatedRouteSnapshot, type ViewTransitionInfo } from '@angular/router';
import { MEDIA, matchesMedia, takeGestureNavigation } from '@stupa-makers/ui-kit';

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

type NavigateEvent = Event & { hasUAVisualTransition?: boolean };
type NavigationApi = EventTarget;

/** A back or forward gesture that the browser animated counts for this long, in ms. */
const UA_TRANSITION_MS = 1000;
let uaTransitionAt = -Infinity;

/**
 * Note each history navigation that the browser animated itself, for example the back
 * gesture of Android, which slides a screenshot of the whole page (bottom bar included)
 * and which no page can change. Our own transition must not run a second time on top,
 * so `onRouteViewTransition` skips the next one. Without the Navigation API nothing is
 * noted.
 */
export function watchUAVisualTransitions(win: Window = window): void {
  const nav = (win as Window & { navigation?: NavigationApi }).navigation;
  nav?.addEventListener('navigate', (e) => {
    if ((e as NavigateEvent).hasUAVisualTransition) uaTransitionAt = performance.now();
  });
}

/** True once after a navigation that the browser animated, see `watchUAVisualTransitions`. */
function takeUATransition(): boolean {
  const recent = performance.now() - uaTransitionAt < UA_TRANSITION_MS;
  uaTransitionAt = -Infinity;
  return recent;
}

/**
 * The motion of a navigation.
 * - `section`: to another top-level section. The content fades through, the frame stays.
 * - `push` / `pop`: on a phone, one level deeper or back in the same section. The new
 *   page slides in from the end, or the old one slides out to it.
 * - `none`: everything else (a row on a desktop list, a filter in the query). No
 *   transition, so a list does not blink when a row opens.
 *
 * A navigation that replaces the history entry (`replaceUrl`) is never a push or a pop:
 * it is no step forward or back, but the page that completes its own address, for
 * example `/todos` that opens the default board at `/todos/<id>`. A slide there would
 * follow the fade of the section entry and move the page a second time.
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
  replace = false,
): RouteMotion {
  if ((from[0] ?? '') !== (to[0] ?? '')) return 'section';
  if (!phone || replace) return 'none';
  if (startsWith(to, from)) return 'push';
  if (startsWith(from, to)) return 'pop';
  return 'none';
}

/**
 * The `onViewTransitionCreated` hook of the router, which runs it in an injection
 * context. It skips the transitions that must
 * not show, and names the kind on `<html data-motion>` for the styles in `styles.scss`.
 * A navigation that a gesture started (the swipe back of the list/detail layout) has no
 * transition, because the finger already moved the page out; a pop on top would slide
 * the list out a second time. The same holds for a back or forward that the browser
 * animated (`watchUAVisualTransitions`).
 */
export function onRouteViewTransition({ transition, from, to }: ViewTransitionInfo): void {
  const phone = matchesMedia(MEDIA.phone);
  const gesture = takeGestureNavigation() || takeUATransition();
  const replace = inject(Router).currentNavigation()?.extras.replaceUrl === true;
  const kind =
    reducedMotion() || gesture
      ? 'none'
      : routeMotion(routePath(from), routePath(to), phone, replace);
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
