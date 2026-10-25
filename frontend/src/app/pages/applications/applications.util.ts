import type { Transition } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { flowColorKind } from '@shared/status-kind.util';
import { formatBytes as formatBytesIn } from '@stupa-makers/ui-kit';

/**
 * Derive the display title of an application from the free `data` fields.
 *
 * A form has no guaranteed `title` field. The function takes the first non-empty
 * string from the usual keys. It returns the fallback when no key matches. The
 * caller passes the i18n "untitled" text as that fallback.
 */
export function applicationTitle(
  data: Record<string, unknown> | null | undefined,
  fallback: string,
): string {
  if (!data) return fallback;
  for (const key of ['title', 'name', 'subject', 'titel']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return fallback;
}

/**
 * Human-readable bytes in the UI locale ("1,5 MB"), binary base, one decimal from KB up.
 * An invalid size gives "—".
 *
 * @deprecated Call `formatBytes(bytes, formatLocale, 'fixed')` from `@shared/format-bytes`.
 * Only the attachments panel still uses this wrapper.
 */
export function formatBytes(bytes: number, locale: string): string {
  return formatBytesIn(bytes, toFormatLocale(locale), 'fixed');
}

/** The look of a transition button in the detail header. */
export type TransitionLook = 'fill' | 'tonal' | 'danger';

/**
 * The look of each transition button: a transition in a red colour (a rejection) is a
 * destructive action and gets the outlined red look. The first other transition is the
 * main action (filled), the rest are tonal. The order of the server stays.
 */
export function transitionLooks(transitions: readonly Transition[]): Map<string, TransitionLook> {
  const looks = new Map<string, TransitionLook>();
  let main = false;
  for (const t of transitions) {
    if (isRejection(t)) {
      looks.set(t.id, 'danger');
    } else {
      looks.set(t.id, main ? 'tonal' : 'fill');
      main = true;
    }
  }
  return looks;
}

/** A transition whose colour reads as an error (red): a rejection or a cancel. */
export function isRejection(t: Pick<Transition, 'color'>): boolean {
  return flowColorKind(t.color) === 'error';
}
