import { problemCode, problemDetail } from '@core/api/problem';
import type { Translate, TranslationKey } from '@core/i18n/translations';

/** The refusals of a poll or an Umlaufverfahren that have their own text. */
const REFUSAL_TEXT: Readonly<Record<string, TranslationKey>> = {
  circular_window_too_short: 'circular.toast.windowTooShort',
  closes_at_too_soon: 'poll.toast.endTooSoon',
};

/** The toast text of a refused start or save: the own text, else the server detail. */
export function pollRefusalMessage(err: unknown, translate: Translate): string {
  const own = REFUSAL_TEXT[problemCode(err)];
  if (own) return translate(own);
  const detail = problemDetail(err);
  const base = translate('meetings.toast.actionFailed');
  return detail ? `${base}: ${detail}` : base;
}
