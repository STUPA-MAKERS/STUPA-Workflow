import { type EnvironmentProviders, inject } from '@angular/core';
import {
  provideUiKit,
  type UiKitIntl,
  type UiKitTextKey,
  uiKitIntlFromLang,
} from '@stupa-makers/ui-kit';
import { I18nService } from './i18n.service';
import type { TranslationKey } from './translations';

/**
 * The texts of the kit that STUPA has in its own catalog: the frame (shell, rail, bottom bar),
 * the account menu, the search palette, the update and offline notices and the load bar. The kit reads
 * them through the app, so the wording of the app, the admin overrides and the extra UI
 * languages apply to them as before. Every other kit text comes from the kit catalog.
 */
export const UI_KIT_APP_KEYS: Partial<Record<UiKitTextKey, TranslationKey>> = {
  loading: 'common.loading',
  'pwa.updateReady': 'pwa.updateReady',
  'pwa.reload': 'pwa.reload',
  'pwa.offline': 'pwa.offline',
  'shell.skip': 'app.skipToContent',
  'shell.mainNav': 'nav.main',
  'shell.more': 'shell.nav.more',
  'shell.search': 'search.title',
  'shell.brand': 'shell.nav.brand',
  'account.signedInAs': 'auth.signedInAs',
  'account.language': 'shell.account.language',
  'account.darkMode': 'shell.account.darkMode',
  'account.logout': 'action.logout',
  'account.open': 'shell.account.open',
  'account.region': 'shell.account.region',
  'palette.title': 'search.title',
  'palette.placeholder': 'search.placeholder',
  'palette.close': 'search.close',
  'palette.empty': 'search.empty',
  'palette.truncated': 'search.truncated',
  'palette.keysSelect': 'search.keys.select',
  'palette.keysOpen': 'search.keys.open',
  'palette.archived': 'search.archived',
};

/**
 * The `UI_KIT_INTL` of the app: the language and the number and date format follow
 * {@link I18nService}, and the keys of {@link UI_KIT_APP_KEYS} translate through it.
 */
export function appUiKitIntl(i18n: I18nService): UiKitIntl {
  const kit = uiKitIntlFromLang(i18n.locale, undefined, i18n.formatLocale);
  return {
    lang: kit.lang,
    formatLocale: kit.formatLocale,
    translate: (key, params) => {
      const own = UI_KIT_APP_KEYS[key];
      return own ? i18n.translate(own, params) : kit.translate(key, params);
    },
  };
}

/**
 * The kit settings of the app: the texts through {@link appUiKitIntl} and the theme
 * preference under the storage key `ap.theme`, which the app used before the theme moved
 * into the kit. The manifest and the page background of each theme are the kit defaults.
 */
export function provideAppUiKit(): EnvironmentProviders {
  return provideUiKit({
    intl: () => appUiKitIntl(inject(I18nService)),
    theme: { storageKey: 'ap.theme' },
  });
}
