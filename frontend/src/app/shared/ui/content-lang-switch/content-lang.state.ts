import { Injectable, inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * The content language of one editor: the language that its text fields show. The editor
 * provides it (`providers: [ContentLangState]`), `app-content-lang-switch` sets it with
 * `[(value)]="contentLang.lang"`, and every `app-i18n-input` inside reads it. It starts with
 * the language of the page.
 */
@Injectable()
export class ContentLangState {
  /** `de`, `en` or the code of an extra language. */
  readonly lang = signal(inject(I18nService).uiLocale());
}
