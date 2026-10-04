import type { AgendaItem, HandoverMode, KeeperPeriod, Meeting } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import { clockTime } from './meetings-display.util';

/** The translate function of the I18nService. */
type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

/** The name of a keeper, or a dash when the server sent none. */
function nameOf(p: KeeperPeriod): string {
  return p.name?.trim() || '—';
}

/**
 * The span of one period: the TOP numbers, else the times (Z3, O2).
 *
 * An ended period reads "TOP 1–3" (one TOP: "TOP 3"). The running period reads
 * "ab TOP 3"; a later period (a handover) also names its start time, "ab TOP 3, 18:55".
 * A period without a TOP number uses the times, "18:04–18:55". `timed` is false for a
 * planned start whose time is not known yet.
 */
function span(
  p: KeeperPeriod,
  later: boolean,
  timed: boolean,
  t: Translate,
  locale: string,
): string {
  const fromTime = clockTime(p.fromAt, locale);
  const toTime = clockTime(p.toAt, locale);
  const running = p.toAt === null;
  if (running) {
    if (p.fromPosition !== null) {
      const top = t('meetings.agenda.top', { n: p.fromPosition });
      return later && timed && fromTime
        ? t('meetings.keeper.fromTopAt', { top, time: fromTime })
        : t('meetings.keeper.from', { start: top });
    }
    if (!timed) return t('meetings.keeper.nextTop');
    return fromTime ? t('meetings.keeper.from', { start: fromTime }) : '';
  }
  if (p.fromPosition !== null && p.toPosition !== null) {
    return p.fromPosition === p.toPosition
      ? t('meetings.agenda.top', { n: p.fromPosition })
      : t('meetings.keeper.topRange', { from: p.fromPosition, to: p.toPosition });
  }
  const start = p.fromPosition !== null ? t('meetings.agenda.top', { n: p.fromPosition }) : fromTime;
  const end = p.toPosition !== null ? t('meetings.agenda.top', { n: p.toPosition }) : toTime;
  if (start && end) return `${start}–${end}`;
  return start ? t('meetings.keeper.from', { start }) : '';
}

/**
 * The keeper line of the protocol head: one name, or every period with its span,
 * "Mara Keller (TOP 1–3), Lea Hoffmann (ab TOP 3, 18:55)". A planned handover is not
 * part of it. The PDF head of the render service writes the same line.
 */
export function keeperLine(periods: readonly KeeperPeriod[], t: Translate, locale: string): string {
  return line(periods.filter((p) => p.fromAt !== null), t, locale, false);
}

/** The keeper line of started periods. `lastUntimed`: the last start has no time yet. */
function line(
  started: readonly KeeperPeriod[],
  t: Translate,
  locale: string,
  lastUntimed: boolean,
): string {
  if (started.length === 0) return '';
  if (started.length === 1) return nameOf(started[0]);
  return started
    .map((p, i) => {
      const timed = !(lastUntimed && i === started.length - 1);
      const s = span(p, i > 0, timed, t, locale);
      return s ? `${nameOf(p)} (${s})` : nameOf(p);
    })
    .join(', ');
}

/** Every keeper of the meeting once, in the order of the periods: "Mara Keller, Lea Hoffmann". */
export function keeperNames(m: Meeting): string {
  const names = m.keeperPeriods.filter((p) => p.fromAt !== null).map(nameOf);
  const unique = [...new Set(names)];
  if (unique.length) return unique.join(', ');
  return m.protokollantName ?? '';
}

/** The keeper line of a meeting, with the current minute-taker for a meeting without periods. */
export function meetingKeeperLine(m: Meeting, t: Translate, locale: string): string {
  return keeperLine(m.keeperPeriods, t, locale) || (m.protokollantName ?? '');
}

/** The 1-based number of the agenda item that the room handles now, or `null`. */
export function currentPosition(m: Meeting, agenda: readonly AgendaItem[]): number | null {
  if (!m.currentAgendaItemId) return null;
  const index = agenda.findIndex((a) => a.id === m.currentAgendaItemId);
  return index >= 0 ? index + 1 : null;
}

/**
 * The keeper line after a handover, for the preview of the handover dialog.
 *
 * `now` ends the running period with the current TOP and starts the new one in the same
 * TOP at this time. `next_item` lets the old keeper finish the current TOP and starts the
 * new period with the next one; its time is not known yet.
 */
export function handoverPreview(
  m: Meeting,
  agenda: readonly AgendaItem[],
  next: { principalId: string; name: string },
  mode: HandoverMode,
  now: Date,
  t: Translate,
  locale: string,
): string {
  const pos = currentPosition(m, agenda);
  const nowIso = now.toISOString();
  const started = m.keeperPeriods.filter((p) => p.fromAt !== null);
  // A meeting from before the periods existed: the current minute-taker since the start.
  const periods: KeeperPeriod[] = started.length
    ? started.map((p) => ({ ...p }))
    : m.protokollantId
      ? [
          {
            principalId: m.protokollantId,
            name: m.protokollantName,
            fromAt: m.startedAt ?? nowIso,
            toAt: null,
            fromAgendaItemId: null,
            toAgendaItemId: null,
            fromPosition: null,
            toPosition: null,
          },
        ]
      : [];
  const running = periods.find((p) => p.toAt === null);
  if (running) {
    running.toAt = nowIso;
    running.toPosition = pos;
  }
  periods.push({
    principalId: next.principalId,
    name: next.name,
    fromAt: nowIso,
    toAt: null,
    fromAgendaItemId: null,
    toAgendaItemId: null,
    fromPosition: mode === 'now' ? pos : pos !== null ? pos + 1 : null,
    toPosition: null,
  });
  return line(periods, t, locale, mode === 'next_item');
}
