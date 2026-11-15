import { MEETING_FORMS, MEETING_KINDS, type MeetingDefaults, type MeetingKind } from '@core/api/models';
import type { I18nService } from '@core/i18n/i18n.service';
import { daysUntil } from '@shared/date-format';
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
