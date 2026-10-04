import { Injectable, inject } from '@angular/core';
import { LOCATION } from '@core/browser/location.token';
import { I18nService } from '@core/i18n/i18n.service';
import type { Locale } from '@core/i18n/translations';

/**
 * Switches the language of the app: the account menu and the public top bar use it.
 *
 * The server resolves its i18n values (state, type and transition labels, form fields) in
 * the language of the request and never updates them later. So a switch reloads the
 * current view, which gives one language on the whole page.
 */
@Injectable({ providedIn: 'root' })
export class LocaleSwitchService {
  private readonly i18n = inject(I18nService);
  private readonly location = inject(LOCATION);

  /** Set the language. An unchanged value does nothing (no reload). */
  switchTo(value: string): void {
    const locale = value as Locale;
    if (!this.i18n.locales.includes(locale) || locale === this.i18n.locale()) return;
    this.i18n.setLocale(locale);
    this.location.reload();
  }
}
