import type { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

/**
 * The texts of an OAuth scope (`auth/oauth.py` SCOPES), shared by the consent page and the
 * API access page. The key `meetings:write` reads from `account.scope.meetings_write.*`.
 * A scope that the frontend does not know yet shows its key as the label and no
 * description, never a raw translation key.
 */
function lookup(i18n: I18nService, key: string, part: 'label' | 'desc', fallback: string): string {
  const id = `account.scope.${key.replace(/:/g, '_')}.${part}`;
  const text = i18n.translate(id as TranslationKey);
  return text === id ? fallback : text;
}

/** The label of a scope, for example "Sitzungen verwalten". */
export function scopeLabel(i18n: I18nService, key: string): string {
  return lookup(i18n, key, 'label', key);
}

/** The one-line description of a scope, or '' for an unknown scope. */
export function scopeDesc(i18n: I18nService, key: string): string {
  return lookup(i18n, key, 'desc', '');
}
