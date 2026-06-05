import type { I18nMap, Lang } from '@core/api/models';

/**
 * Konfigurierbaren `*_i18n`-Text auflösen (Backend `app/shared/i18n.py`):
 * angeforderte Sprache → Fallback `de` → erster vorhandener Wert → `''`.
 * Für DB-konfigurierte Form-Labels/Hilfetexte (nicht den UI-String-Katalog).
 */
export function resolveI18n(map: I18nMap | null | undefined, lang: Lang | string): string {
  if (!map) return '';
  if (lang in map) return map[lang] ?? '';
  if ('de' in map) return map['de'] ?? '';
  const first = Object.values(map)[0];
  return first ?? '';
}
