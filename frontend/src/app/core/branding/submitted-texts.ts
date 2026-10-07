import type { I18nMap } from '@core/api/models';
import { CATALOG, DEFAULT_LOCALE, type Locale } from '@core/i18n/translations';

/**
 * The texts on the page after the submission of an application.
 *
 * - `internal`: a signed-in applicant. The application is submitted at once.
 * - `external`: a guest. The link in the e-mail confirms the application.
 *
 * `/admin/branding` sets each text per language as Markdown (`freetexts.submittedInternal`
 * and `freetexts.submittedExternal` of the site config). An empty text of a language
 * falls back to the built-in text of that language, so a new installation shows the
 * same words as before.
 */
export type SubmittedKind = 'internal' | 'external';

/** The free-text key of the site config for each kind. */
export const SUBMITTED_FREETEXT = {
  internal: 'submittedInternal',
  external: 'submittedExternal',
} as const satisfies Record<SubmittedKind, string>;

/** The built-in text of each kind: the i18n key the page used before. */
const DEFAULT_KEY = {
  internal: 'apply.submitted.body',
  external: 'apply.confirm.body',
} as const satisfies Record<SubmittedKind, string>;

/** The built-in text of a kind in a language. */
export function defaultSubmittedText(kind: SubmittedKind, lang: Locale): string {
  const key = DEFAULT_KEY[kind];
  return CATALOG[lang][key] ?? CATALOG[DEFAULT_LOCALE][key] ?? '';
}

/**
 * The Markdown that the page shows for a kind in a language: the configured text of
 * exactly that language, or the built-in text when it is empty or missing.
 */
export function submittedMarkdown(
  map: I18nMap | null | undefined,
  kind: SubmittedKind,
  lang: Locale,
): string {
  const custom = (map?.[lang] ?? '').trim();
  return custom || defaultSubmittedText(kind, lang);
}
