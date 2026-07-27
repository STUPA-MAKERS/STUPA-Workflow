import { Pipe, type PipeTransform, inject } from '@angular/core';
import { I18nService } from './i18n.service';

/** Format presets for the localized date output. */
export type LocalDateFormat = 'short' | 'medium' | 'mediumDate' | 'long' | 'time';

const OPTIONS: Record<LocalDateFormat, Intl.DateTimeFormatOptions> = {
  short: { dateStyle: 'short', timeStyle: 'short' },
  medium: { dateStyle: 'medium', timeStyle: 'short' },
  mediumDate: { dateStyle: 'medium' },
  long: { dateStyle: 'long', timeStyle: 'short' },
  time: { timeStyle: 'short' },
};

/**
 * Localized date and time output through `Intl.DateTimeFormat`.
 *
 * The pipe follows the active UI language (`I18nService.locale()`), not the fixed
 * Angular `LOCALE_ID`, which would always give `en-US`. The pipe is impure, so a
 * language switch updates the output without a reload. Date formatting is cheap.
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
    const locale = this.i18n.locale() === 'en' ? 'en-US' : 'de-DE';
    return new Intl.DateTimeFormat(locale, OPTIONS[format]).format(date);
  }
}
