import { Pipe, type PipeTransform, inject } from '@angular/core';
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

/** "Di., 13.10.2026": the date with a short weekday, as the meeting pages show it. */
const WEEKDAY_DATE: Intl.DateTimeFormatOptions = {
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
};

const OPTIONS: Record<LocalDateFormat, Intl.DateTimeFormatOptions> = {
  short: { dateStyle: 'short', timeStyle: 'short' },
  medium: { dateStyle: 'medium', timeStyle: 'short' },
  mediumDate: { dateStyle: 'medium' },
  long: { dateStyle: 'long', timeStyle: 'short' },
  time: { timeStyle: 'short' },
  weekdayDate: WEEKDAY_DATE,
  /** "Di., 13.10.2026, 17:00", always 24 h. */
  weekdayShort: { ...WEEKDAY_DATE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' },
};

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
    if (value === null || value === undefined || value === '') return '';
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), OPTIONS[format]).format(date);
  }
}
