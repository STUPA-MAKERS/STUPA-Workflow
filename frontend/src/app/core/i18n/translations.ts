/** UI string catalog. DE is the reference. A missing EN key falls back to DE. */

import type deCatalog from './catalog/de.json';

export type Locale = 'de' | 'en';

export const SUPPORTED_LOCALES: readonly Locale[] = ['de', 'en'] as const;
export const DEFAULT_LOCALE: Locale = 'de';

export type TranslationKey = keyof typeof deCatalog;

/** The shape of `I18nService.translate`, for pure helpers that take the translator as an argument. */
export type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

/**
 * The DE catalog, the reference for every key. It starts empty: `loadCatalog('de')` fills
 * this same object from its lazy chunk (`translations.de.ts`), so a module that holds it
 * reads the texts once the app initializer is done.
 *
 * The texts live in `catalog/de.json` and `catalog/en.json`, the only copy of them. The
 * api container mounts the same directory, because the server refuses an override with an
 * unknown key or with other placeholders and serves the built-in texts to a translator.
 *
 * Notes on some keys:
 * - The `ui.*` keys name controls only; a page passes its own visible text.
 * - The `formly.*` texts apply when the form definition sets no explicit label,
 *   placeholder or error text.
 * - The `actor.system.*` keys hold one key for each system actor that the backend writes
 *   (`system:<key>`).
 * - `apply.confirm.heading` uses U+2011 (non-breaking hyphen): a narrow screen must not
 *   break "E-Mail".
 * - `apply.submitted.heading` is for a signed-in submitter: the backend confirms the
 *   address at creation time.
 * - The prefill of `meetings.vote.questionPrefillDecision` follows the decision proposal.
 * - `election.candidate.erased` names a candidate whose name the DSGVO erasure removed.
 * - The `budget.tree.fyBlocked.*` keys are 409 reasons: the server names exactly one of
 *   these causes.
 * - `admin.webhook.delivery.*` is the delivery diagnosis: the server keeps only the newest
 *   attempt per webhook.
 * - `admin.form.groupStep` names a question group. One group container is one wizard step.
 */
export const de = {} as Record<TranslationKey, string>;

/**
 * The catalog of every locale. DE is the reference and the fallback of every other locale;
 * the app loads it before the first paint. Both start empty and `loadCatalog` fills them.
 */
export const CATALOG: Record<Locale, Partial<Record<TranslationKey, string>>> = { de, en: {} };

const LOADED = new Set<Locale>();

/** True when the strings of `locale` are in {@link CATALOG}. */
export function isCatalogLoaded(locale: Locale): boolean {
  return LOADED.has(locale);
}

/**
 * Put the strings of `locale` into {@link CATALOG}. DE goes into {@link de} itself, because
 * other modules hold that object.
 */
export function registerCatalog(locale: Locale, table: Partial<Record<TranslationKey, string>>): void {
  if (locale === 'de') Object.assign(de, table);
  else CATALOG[locale] = table;
  LOADED.add(locale);
}

/**
 * Load the strings of `locale` from their lazy chunk. A loaded locale resolves at once. A
 * failed load rejects and leaves the catalog as it was, so the app shows DE.
 */
export async function loadCatalog(locale: Locale): Promise<void> {
  if (LOADED.has(locale)) return;
  if (locale === 'de') {
    const { deTable } = await import('./translations.de');
    registerCatalog('de', deTable);
    return;
  }
  const { en } = await import('./translations.en');
  registerCatalog('en', en);
}
