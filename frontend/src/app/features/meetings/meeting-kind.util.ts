import { MEETING_FORMS, MEETING_KINDS } from '@core/api/models';
import type { I18nService } from '@core/i18n/i18n.service';
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
