import { Pipe, type PipeTransform, inject } from '@angular/core';
import { I18nService } from './i18n.service';

/** Format-Presets der lokalisierten Datumsausgabe. */
export type LocalDateFormat = 'short' | 'medium' | 'mediumDate' | 'long' | 'time';

const OPTIONS: Record<LocalDateFormat, Intl.DateTimeFormatOptions> = {
  short: { dateStyle: 'short', timeStyle: 'short' },
  medium: { dateStyle: 'medium', timeStyle: 'short' },
  mediumDate: { dateStyle: 'medium' },
  long: { dateStyle: 'long', timeStyle: 'short' },
  time: { timeStyle: 'short' },
};

/**
 * Lokalisierte Datums-/Zeitausgabe über `Intl.DateTimeFormat` auf Basis der **aktiven
 * UI-Sprache** (`I18nService.locale()`), nicht des fixen Angular-`LOCALE_ID` (das
 * sonst immer `en-US` liefert). Impure, damit ein Sprachwechsel die Ausgabe ohne
 * Reload aktualisiert (Datumsformatierung ist günstig).
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
