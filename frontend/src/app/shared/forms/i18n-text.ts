import type { I18nMap, Lang } from '@core/api/models';

/**
 * Resolve configurable `*_i18n` text (backend `app/shared/i18n.py`).
 * The order is: requested language → fallback `de` → first present value → `''`.
 * This covers DB-configured form labels and help texts, not the UI string catalog.
 */
export function resolveI18n(map: I18nMap | null | undefined, lang: Lang | string): string {
  if (!map) return '';
  if (lang in map) return map[lang] ?? '';
  if ('de' in map) return map['de'] ?? '';
  const first = Object.values(map)[0];
  return first ?? '';
}
