import type { BadgeVariant } from '@stupa-makers/ui-kit';
import type { ScanState } from '@core/api/models';

/**
 * Derive the display title of an application from the free `data` fields.
 *
 * A form has no guaranteed `title` field. The function takes the first non-empty
 * string from the usual keys. It returns the fallback when no key matches. The
 * caller passes the i18n "untitled" text as that fallback.
 */
export function applicationTitle(
  data: Record<string, unknown> | null | undefined,
  fallback: string,
): string {
  if (!data) return fallback;
  for (const key of ['title', 'name', 'subject', 'titel']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return fallback;
}

/**
 * Stringify a diff or data field value for display.
 *
 * A scalar keeps its own text. An object or an array becomes compact JSON.
 * `null` and `undefined` become an empty string.
 */
export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** Map a scan state to a badge variant. An unknown state gives a neutral badge. */
export function scanBadgeVariant(state: ScanState): BadgeVariant {
  switch (state) {
    case 'clean':
      return 'success';
    case 'quarantined':
      return 'danger';
    case 'scanning':
      return 'warning';
    default:
      return 'neutral';
  }
}

/** Human-readable bytes, binary base, one decimal from KB up. An invalid size gives "—". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}
