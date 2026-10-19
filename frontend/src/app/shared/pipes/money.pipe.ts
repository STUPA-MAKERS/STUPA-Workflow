import { Pipe, type PipeTransform, inject } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { formatMoney, type MoneyOptions } from '../format-money';

/**
 * An amount as money in the active format locale: `{{ total | money }}`,
 * `{{ v | money: { currency: c, whole: true } }}`. The pipe is impure, because the locale is
 * a signal and a pure pipe would keep the text of the old language. No number gives `''`.
 */
@Pipe({ name: 'money', standalone: true, pure: false })
export class MoneyPipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(value: unknown, options: MoneyOptions = {}): string {
    return formatMoney(value, this.i18n.formatLocale(), options);
  }
}
