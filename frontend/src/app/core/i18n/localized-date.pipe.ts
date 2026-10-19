import { Pipe, type PipeTransform, inject } from '@angular/core';
import { weekdayDate } from '@shared/date-format';
import { I18nService } from './i18n.service';

/** Format presets for the localized date output. */
export type LocalDateFormat =
  | 'short'
  | 'medium'
  | 'mediumDate'
  | 'long'
  | 'time'
  | 'weekdayDate'
  | 'weekdayShort';

const OPTIONS: Record<Exclude<LocalDateFormat, 'weekdayDate' | 'weekdayShort'>, Intl.DateTimeFormatOptions> = {
  short: { dateStyle: 'short', timeStyle: 'short' },
  medium: { dateStyle: 'medium', timeStyle: 'short' },
  mediumDate: { dateStyle: 'medium' },
  long: { dateStyle: 'long', timeStyle: 'short' },
  time: { timeStyle: 'short' },
};

/**
 * The localized text of a moment, as the `ldate` pipe shows it: `''` for no value or an
 * invalid one. For TS that builds a string (a tooltip, a translated sentence); a template
 * uses the pipe. `locale` is `I18nService.formatLocale()`.
 */
export function formatMoment(
  value: string | number | Date | null | undefined,
  locale: string,
  format: LocalDateFormat = 'medium',
): string {
  if (value === null || value === undefined || value === '') return '';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  // "Di, 13.10.2026" and "Di, 13.10.2026, 17:00" (24 h): the weekday without its dot.
  if (format === 'weekdayDate') return weekdayDate(date, locale);
  if (format === 'weekdayShort') return weekdayDate(date, locale, { time: true });
  return new Intl.DateTimeFormat(locale, OPTIONS[format]).format(date);
}

/**
 * Localized date and time output through `Intl.DateTimeFormat`.
 *
 * The pipe follows the active UI language (`I18nService.formatLocale()`), not the
 * fixed Angular `LOCALE_ID`, which would always give `en-US`. EN thus reads as
 * `en-GB` (day first, 24 h). The pipe is impure, so a language switch updates the
 * output without a reload. Date formatting is cheap.
 */
@Pipe({ name: 'ldate', standalone: true, pure: false })
export class LocalizedDatePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(
    value: string | number | Date | null | undefined,
    format: LocalDateFormat = 'medium',
  ): string {
    return formatMoment(value, this.i18n.formatLocale(), format);
  }
}
