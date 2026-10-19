/**
 * The display label of a person: the name, else the e-mail, else a fallback text.
 *
 * Each page keeps its own fallback ("Ohne Namen", "Unbekanntes Mitglied", "—", …), so the
 * fallback is an option. The label of an actor of a change (system, applicant, Gremium)
 * is `actorLabel` in `actor-label.util.ts`.
 */
import type { PersonRef } from '@core/api/models';
import type { Translate, TranslationKey } from '@core/i18n/translations';

/** The fields a person label reads. Every API person shape has them, some without `email`. */
export interface PersonLike {
  displayName?: string | null;
  email?: string | null;
}

/** The translate function, or the `I18nService` (anything with its `translate`). */
export type Translator = Translate | { translate: Translate };

export interface PersonLabelOptions {
  /** The text for a person without name and e-mail. Default "Ohne Namen" (`common.unnamed`). */
  fallback?: TranslationKey;
  /** A literal fallback instead of a key, for example "—" or an id the page already shows. */
  fallbackText?: string;
}

/** The name, else the e-mail, else the fallback. An empty name or e-mail counts as none. */
export function personLabel(
  person: PersonLike | null | undefined,
  t: Translator,
  options: PersonLabelOptions = {},
): string {
  const known = person?.displayName || person?.email;
  if (known) return known;
  if (options.fallbackText !== undefined) return options.fallbackText;
  const key = options.fallback ?? 'common.unnamed';
  return typeof t === 'function' ? t(key) : t.translate(key);
}

/** A person reference of the server; a deleted or anonymized one is "Gelöschte Person". */
export function personName(ref: PersonRef | null | undefined, t: Translator): string {
  return personLabel(ref, t, { fallback: 'chat.deletedPerson' });
}
