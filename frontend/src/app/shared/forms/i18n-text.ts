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

/**
 * The display name of a configured object with an `*_i18n` label (a role, a gremium
 * role): the requested language, then `de`, then `fallback` (the key). Unlike
 * `resolveI18n` it never shows a third language, so a role with only an `en` label reads
 * as its key in German, and an empty label counts as missing.
 */
export function i18nLabel(map: I18nMap | null | undefined, lang: Lang | string, fallback: string): string {
  return map?.[lang] || map?.['de'] || fallback;
}
