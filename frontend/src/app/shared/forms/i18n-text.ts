import type { I18nMap, Lang } from '@core/api/models';

/**
 * Resolve configurable `*_i18n` text (backend `app/shared/i18n.py`):
 * requested language → fallback `de` → first present value → `''`.
 * For DB-configured form labels/help texts (not the UI string catalogue).
 */
export function resolveI18n(map: I18nMap | null | undefined, lang: Lang | string): string {
  if (!map) return '';
  if (lang in map) return map[lang] ?? '';
  if ('de' in map) return map['de'] ?? '';
  const first = Object.values(map)[0];
  return first ?? '';
}
