import type { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import type { AuditVerification, AuditVerificationTrigger } from '../admin.models';

/** The trigger of a stored chain check as words ("nächtliche Prüfung"). */
const TRIGGER_KEYS: Record<AuditVerificationTrigger, TranslationKey> = {
  cron: 'admin.health.trigger.cron',
  manual: 'admin.health.trigger.manual',
  restore: 'admin.health.trigger.restore',
};

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  );
}

/**
 * A point in time for a status line: "heute, 04:30", "gestern, 17:45" or
 * "29.09.2026, 04:30". `now` is a parameter for the tests.
 */
export function formatWhen(at: string, i18n: I18nService, now: Date = new Date()): string {
  const date = new Date(at);
  const locale = i18n.formatLocale();
  const time = new Intl.DateTimeFormat(locale, { timeStyle: 'short' }).format(date);
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(date, now)) return i18n.translate('admin.health.todayAt', { time });
  if (sameDay(date, yesterday)) return i18n.translate('admin.health.yesterdayAt', { time });
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

/** A count with the group separator of the locale ("18.412"). */
export function formatCount(n: number, i18n: I18nService): string {
  return new Intl.NumberFormat(i18n.formatLocale()).format(n);
}

/** The words for the trigger of a stored check. */
export function triggerLabel(trigger: AuditVerificationTrigger, i18n: I18nService): string {
  return i18n.translate(TRIGGER_KEYS[trigger]);
}

/** The time a stored check ended, else the time it started. */
export function checkedAt(v: AuditVerification): string {
  return v.finishedAt ?? v.startedAt;
}

/**
 * File size for a status line ("413 MB", "4,2 GB"). Archives are megabytes to gigabytes,
 * so bytes help nobody. One decimal below 10, else whole numbers.
 */
export function formatBytes(bytes: number | null | undefined, i18n: I18nService): string {
  if (bytes == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit > 0 && value < 10 ? 1 : 0;
  const text = new Intl.NumberFormat(i18n.formatLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
  return `${text} ${units[unit]}`;
}
