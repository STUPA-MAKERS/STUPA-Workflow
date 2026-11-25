import {
  type AmountChange,
  FORCE_REASONS,
  type OutsideDecision,
  type TimelineOrderEvent,
} from '@core/api/models';
import type { Translate } from '@core/i18n/translations';
import { dayMonthYear } from '@shared/date-format';
import { formatMoney } from '@shared/format-money';

/**
 * The lines of a decision made outside the platform (spec 001602): the result, the date
 * and the Gremium, and, when they were given, the counts. The link to the meeting is
 * not a line; the caller makes it from `meetingId`.
 */
export function outsideDecisionLines(o: OutsideDecision, locale: string, t: Translate): readonly string[] {
  const result = t(o.result === 'passed' ? 'outsideDecision.passed' : 'outsideDecision.failed');
  const date = dayMonthYear(o.meetingDate, locale);
  const counts = [
    ...(o.yes !== null && o.yes !== undefined ? [t('outsideDecision.countYes', { n: o.yes })] : []),
    ...(o.no !== null && o.no !== undefined ? [t('outsideDecision.countNo', { n: o.no })] : []),
    ...(o.abstain !== null && o.abstain !== undefined
      ? [t('outsideDecision.countAbstain', { n: o.abstain })]
      : []),
  ];
  return [
    t('outsideDecision.historyResult', { result }),
    o.gremiumName
      ? t('outsideDecision.historyMeeting', { date, gremium: o.gremiumName })
      : t('outsideDecision.historyDate', { date }),
    ...(counts.length ? [counts.join(' · ')] : []),
  ];
}

/**
 * The lines of a change of the approved amount (spec 001621): the old and the new
 * amount, the reason (left out in the applicant view) and the decision behind it.
 */
export function amountChangeLines(
  c: AmountChange,
  locale: string,
  currency: string | null,
  t: Translate,
): readonly string[] {
  const money = (v: string | null | undefined) => formatMoney(v, locale, { currency }) || '—';
  const date = c.decisionDate ? dayMonthYear(c.decisionDate, locale) : '';
  const basis =
    date && c.gremiumName
      ? [t('amendAmount.historyBasis', { date, gremium: c.gremiumName })]
      : date
        ? [t('outsideDecision.historyDate', { date })]
        : [];
  return [
    t('amendAmount.historyAmounts', {
      previous: money(c.previousAmount),
      approved: money(c.approvedAmount),
    }),
    ...(c.reason ? [c.reason] : []),
    ...basis,
  ];
}

/** "Status erzwungen · Korrektur eines Fehlers" (spec 001650); an old one has no reason. */
export function forcedLine(reason: string | null | undefined, t: Translate): string {
  const known: readonly string[] = FORCE_REASONS;
  const label =
    reason && known.includes(reason)
      ? t(`applications.forceReason.${reason}` as Parameters<Translate>[0])
      : t('applications.forceReason.none');
  return t('applications.history.forced', { reason: label });
}

/**
 * The title and the line of an event of a Bestellung in the timeline of its Antrag: what
 * happened, then the Bezeichnung with the number. The event holds no price, so the
 * applicant reads the same text. `statusName` gives the name of a status key of the list
 * of the Bestellungen (spec 003035).
 */
export function orderEventText(
  e: TimelineOrderEvent,
  t: Translate,
  statusName: (key: string) => string,
): { readonly title: string; readonly body: string } {
  const title =
    e.change === 'created'
      ? t('orders.history.created')
      : e.change === 'deleted'
        ? t('orders.history.deleted')
        : t('orders.history.status', { status: statusName(e.toStatus ?? '') });
  return { title, body: [e.title, e.number].filter((part) => !!part).join(' · ') };
}
