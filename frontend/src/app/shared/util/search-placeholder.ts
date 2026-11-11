import type { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

/** The three texts of the search field of one list. */
export interface SearchTexts {
  /** Without a count ("Tickets durchsuchen"): while the list loads its first answer. */
  readonly plain: TranslationKey;
  /** One item ("1 Ticket durchsuchen"). */
  readonly one: TranslationKey;
  /** `{count}` items ("{count} Tickets durchsuchen"). */
  readonly many: TranslationKey;
}

/**
 * The placeholder of the search field of a list page (§ 000661): "N … durchsuchen" with the
 * number of items in the list and the singular for one item. While the first answer is out
 * (`pending`) the text has no count, so that it does not say "0 … durchsuchen" too early.
 */
export function searchPlaceholder(
  i18n: I18nService,
  texts: SearchTexts,
  count: number,
  pending = false,
): string {
  if (pending && count === 0) return i18n.translate(texts.plain);
  if (count === 1) return i18n.translate(texts.one);
  return i18n.translate(texts.many, { count });
}
