import type { Signal } from '@angular/core';
import type { Meeting } from '@core/api/models';
import { nowSignal } from '@stupa-makers/ui-kit';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { clockTime } from './meetings-display.util';

/**
 * Where "now" is in the open window of a planned meeting.
 *
 * - `tooEarly`: before `opensAt`. The server refuses the open (409 `meeting_too_early`).
 * - `early`: before `confirmUntil`. The open needs the extra confirmation (`confirmEarly`).
 * - `ok`: no window (no date, not planned), or late enough.
 */
export type OpenWindowState = 'tooEarly' | 'early' | 'ok';

/** The state of the open window at `now` (epoch milliseconds). */
export function openWindowState(
  m: Pick<Meeting, 'opensAt' | 'confirmUntil'>,
  now: number,
): OpenWindowState {
  const opensAt = m.opensAt ? Date.parse(m.opensAt) : Number.NaN;
  if (!Number.isNaN(opensAt) && now < opensAt) return 'tooEarly';
  const confirmUntil = m.confirmUntil ? Date.parse(m.confirmUntil) : Number.NaN;
  if (!Number.isNaN(confirmUntil) && now < confirmUntil) return 'early';
  return 'ok';
}

/**
 * A clock for the open window: `Date.now()`, refreshed every `periodMs`. The open
 * button turns on by itself when the window opens. Call it in an injection context;
 * the timer stops with the caller.
 */
export function openWindowClock(periodMs = 15_000): Signal<number> {
  return nowSignal(periodMs);
}

/**
 * When the window opens, for the hint at the open button: `17:00` on the same day,
 * else `19.10., 17:00`. Local time of the browser.
 */
export function openWindowWhen(iso: string, now: number, i18nLocale: string): string {
  const at = new Date(iso);
  const time = clockTime(iso, i18nLocale);
  if (at.toDateString() === new Date(now).toDateString()) return time;
  const day = new Intl.DateTimeFormat(toFormatLocale(i18nLocale), {
    day: '2-digit',
    month: '2-digit',
  }).format(at);
  return `${day}, ${time}`;
}
