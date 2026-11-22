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
 * the account menu, the search palette, the update and offline notices, the load bar and the
 * activity view. The kit reads
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
  'activity.loading': 'activity.loading',
  'activity.new': 'activity.new',
  'activity.more': 'activity.loadMore',
  'chat.attach': 'chat.attach',
  'chat.cancel': 'action.cancel',
  'chat.copy': 'chat.copy',
  'chat.delete': 'chat.delete',
  'chat.deleteConfirm': 'chat.deleteConfirm',
  'chat.deleteShort': 'chat.deleteShort',
  'chat.deleteTitle': 'chat.deleteTitle',
  'chat.deletedPerson': 'chat.deletedPerson',
  'chat.discard': 'chat.discard',
  'chat.download': 'chat.download',
  'chat.drop': 'chat.drop',
  'chat.edit': 'chat.edit',
  'chat.editShort': 'chat.editShort',
  'chat.edited': 'chat.edited',
  'chat.empty': 'chat.empty',
  'chat.error.delete': 'apply.files.error.delete',
  'chat.error.fileTooLarge': 'chat.error.fileTooLarge',
  'chat.error.fileType': 'chat.error.fileType',
  'chat.error.tooManyFiles': 'chat.error.tooManyFiles',
  'chat.error.upload': 'chat.error.upload',
  'chat.failed': 'chat.failed',
  'chat.fileLost': 'apply.files.lost',
  'chat.internal': 'chat.internal',
  'chat.loading': 'chat.loading',
  'chat.log': 'chat.log',
  'chat.mentions': 'chat.mentions',
  'chat.newCount': 'chat.newCount',
  'chat.newMessages.one': 'chat.newMessages.one',
  'chat.newMessages.other': 'chat.newMessages.other',
  'chat.ownMessage': 'chat.ownMessage',
  'chat.pastedImage': 'chat.pastedImage',
  'chat.placeholder': 'chat.placeholder',
  'chat.public': 'chat.public',
  'chat.removeFile': 'chat.removeFile',
  'chat.removeFileAction': 'apply.files.removeAction',
  'chat.removeFileConfirm': 'apply.files.removeConfirm',
  'chat.removeFileTitle': 'apply.files.removeTitle',
  'chat.retry': 'chat.retry',
  'chat.save': 'chat.save',
  'chat.scan.clean': 'applications.attachments.scan.clean',
  'chat.scan.quarantined': 'applications.attachments.scan.quarantined',
  'chat.scan.scanning': 'applications.attachments.scan.scanning',
  'chat.send': 'chat.send',
  'chat.sending': 'chat.sending',
  'chat.today': 'chat.today',
  'chat.uploading': 'chat.uploading',
  'chat.visibility': 'chat.visibility',
  'chat.yesterday': 'chat.yesterday',
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
