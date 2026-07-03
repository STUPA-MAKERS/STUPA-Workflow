import type { BadgeVariant } from '@stupa-makers/ui-kit';
import type { ScanState } from '@core/api/models';

/**
 * Derive an application's display title from the free `data` fields. Forms have
 * no guaranteed `title` field; we take the first non-empty string from the usual
 * keys, otherwise the fallback (i18n "untitled").
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
 * Robustly stringify diff/data field values for display: scalars directly,
 * objects/arrays as compact JSON, `null`/`undefined` as an empty string.
 */
export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** Scan state → badge variant: scanning = warning, ready = green, finding = red. */
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

/** Human-readable bytes (binary, 1 decimal from KB up). `0` → "0 B". */
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
