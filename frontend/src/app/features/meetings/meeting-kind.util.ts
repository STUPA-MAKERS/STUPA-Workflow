import {
  MEETING_FORMS,
  MEETING_KINDS,
  type Meeting,
  type MeetingDefaults,
  type MeetingKind,
} from '@core/api/models';
import type { I18nService } from '@core/i18n/i18n.service';
import { dayMonthYear, daysUntil } from '@shared/date-format';
import type { SelectOption } from '@stupa-makers/ui-kit';

/** The longest place of a meeting that the server accepts. */
export const MEETING_LOCATION_MAX = 200;

/** The kinds of a meeting for a select (§ 000903). */
export function meetingKindOptions(i18n: I18nService) {
  return MEETING_KINDS.map((value): SelectOption => ({ value, label: i18n.translate(`meetings.kind.${value}`) }));
}

/** The forms of a meeting for a select (§ 000907). */
export function meetingFormOptions(i18n: I18nService) {
  return MEETING_FORMS.map((value): SelectOption => ({ value, label: i18n.translate(`meetings.form.${value}`) }));
}

/**
 * The invitation period in days that the date of a meeting misses, else `null` (§ 000918).
 *
 * An ordinary meeting has the period `inviteDaysOrdinary`, every other kind (a `repeat`
 * meeting too) `inviteDaysExtraordinary`. A date that is nearer than the period is late.
 */
export function lateInviteDays(
  date: string,
  kind: MeetingKind,
  defaults: Pick<MeetingDefaults, 'inviteDaysOrdinary' | 'inviteDaysExtraordinary'> | null,
  today: Date = new Date(),
): number | null {
  if (!defaults) return null;
  const left = daysUntil(date.trim(), today);
  const period = kind === 'ordinary' ? defaults.inviteDaysOrdinary : defaults.inviteDaysExtraordinary;
  return left !== null && left < period ? period : null;
}

/**
 * The meetings that a repeat meeting can name as its first meeting (§ 000940).
 *
 * These are the other meetings of the same Gremium that are not after `day`. A meeting
 * without a date stays in the list, because the server decides nothing from a missing date.
 */
export function firstMeetingOptions(
  meetings: readonly Pick<Meeting, 'id' | 'title' | 'date'>[],
  locale: string,
  day: string,
  selfId: string | null = null,
): readonly SelectOption[] {
  const limit = day.trim();
  return meetings
    .filter((m) => m.id !== selfId && (!limit || !m.date || m.date <= limit))
    .map((m) => ({
      value: m.id,
      label: m.date ? `${m.title} · ${dayMonthYear(m.date, locale)}` : m.title,
    }));
}

/** The link from a Wiederholungssitzung to its first meeting, else `null` (§ 000940). */
export function firstMeetingLink(
  meeting: Pick<Meeting, 'repeatOfId'>,
  i18n: I18nService,
): { readonly label: string; readonly to: string } | null {
  return meeting.repeatOfId
    ? { label: i18n.translate('meetings.repeatOf.label'), to: `/meetings/${meeting.repeatOfId}` }
    : null;
}
