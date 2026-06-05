import { Pipe, type PipeTransform, inject } from '@angular/core';
import { I18nService } from './i18n.service';
import type { TranslationKey } from './translations';

/**
 * `{{ 'nav.dashboard' | t }}` — impure, damit Locale-Wechsel sofort durchschlägt
 * (die aktive Locale ist ein Signal im Service).
 */
@Pipe({ name: 't', standalone: true, pure: false })
export class TranslatePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(key: TranslationKey, params?: Record<string, string | number>): string {
    return this.i18n.translate(key, params);
  }
}
