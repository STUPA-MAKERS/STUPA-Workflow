import type { I18nMap, Lang } from '@core/api/models';
import { fallbackChain } from '@core/i18n/i18n.service';

/**
 * Resolve configurable `*_i18n` text (backend `app/shared/i18n.py`).
 * The order is: the fallback chain of the language (an extra language → `en` → `de`, `en` →
 * `de`) → first present value → `''`. This covers DB-configured form labels and help texts,
 * not the UI string catalog.
 */
export function resolveI18n(map: I18nMap | null | undefined, lang: Lang): string {
  if (!map) return '';
  for (const code of fallbackChain(lang)) {
    if (code in map) return map[code] ?? '';
  }
  const first = Object.values(map)[0];
  return first ?? '';
}

/**
 * The display name of a configured object with an `*_i18n` label (a role, a gremium
 * role): the first non-empty label of the fallback chain of the language, then `fallback`
 * (the key). Unlike `resolveI18n` it never shows a language outside the chain, so a role
 * with only an `en` label reads as its key in German, and an empty label counts as missing.
 */
export function i18nLabel(map: I18nMap | null | undefined, lang: Lang, fallback: string): string {
  for (const code of fallbackChain(lang)) {
    const text = map?.[code];
    if (text) return text;
  }
  return fallback;
}

/** The label of the field of one language: `Bezeichnung (DE)`, `Bezeichnung (PT-BR)`. */
export function langFieldLabel(label: string, lang: Lang): string {
  return `${label} (${lang.toUpperCase()})`;
}

/**
 * Set the text of one language in a map and return a new map. An empty text of an extra
 * language removes its entry, so the language falls back along its chain instead of showing
 * an empty text. DE and EN keep an empty entry, as the editors always wrote them.
 */
export function setI18n(map: I18nMap | null | undefined, lang: Lang, text: string): I18nMap {
  const next: I18nMap = { ...map, [lang]: text };
  if (text === '' && lang !== 'de' && lang !== 'en') delete next[lang];
  return next;
}

/** The two maps have the same text in every language. A missing entry equals an empty one. */
export function sameI18n(a: I18nMap | null | undefined, b: I18nMap | null | undefined): boolean {
  const codes = new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})]);
  return [...codes].every((code) => (a?.[code] ?? '') === (b?.[code] ?? ''));
}

/** The map with each text trimmed and without the empty ones. */
export function trimI18n(map: I18nMap | null | undefined): I18nMap {
  const out: I18nMap = {};
  for (const [code, text] of Object.entries(map ?? {})) {
    if (text.trim()) out[code] = text.trim();
  }
  return out;
}
