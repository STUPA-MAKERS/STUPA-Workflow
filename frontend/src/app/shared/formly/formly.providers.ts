import { type Provider, inject } from '@angular/core';
import { type ConfigOption, FORMLY_CONFIG, provideFormlyCore } from '@ngx-formly/core';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { FormlyInputType } from './formly-input.type';
import { FormlyTextareaType } from './types/formly-textarea.type';
import { FormlySelectType } from './types/formly-select.type';
import { FormlyCheckboxType } from './types/formly-checkbox.type';
import { FormlyMultiCheckboxType } from './types/formly-multicheckbox.type';
import { FormlyDisplayType } from './types/formly-display.type';
import { FormlyPositionsType } from './types/formly-positions.type';
import { FormlyDateRangeType } from './types/formly-daterange.type';

/**
 * Formly base configuration.
 *
 * This provider registers the UI-kit-bound field types of the form definition. The
 * `input` type covers text, number, currency and date through `props.type`. The other
 * types are textarea, select, checkbox and multicheckbox, plus a read-only `display`
 * type for `markdown` and `computed`. The mapping lives in `@shared/forms/formly-mapper`.
 *
 * The validation messages come from the translation catalog. A second `FORMLY_CONFIG`
 * entry supplies them, because a message must read the active locale at render time. A
 * factory provider gives the injection context that the plain config object has not.
 */
export function provideFormly(): Provider {
  return [
    provideFormlyCore({
      types: [
        { name: 'input', component: FormlyInputType },
        { name: 'textarea', component: FormlyTextareaType },
        { name: 'select', component: FormlySelectType },
        { name: 'checkbox', component: FormlyCheckboxType },
        { name: 'multicheckbox', component: FormlyMultiCheckboxType },
        { name: 'display', component: FormlyDisplayType },
        { name: 'positions', component: FormlyPositionsType },
        { name: 'daterange', component: FormlyDateRangeType },
      ],
    }),
    {
      provide: FORMLY_CONFIG,
      multi: true,
      useFactory: (): ConfigOption => {
        const i18n = inject(I18nService);
        const message = (key: TranslationKey) => (): string => i18n.translate(key);
        return {
          validationMessages: [
            { name: 'required', message: message('formly.validation.required') },
            { name: 'min', message: message('formly.validation.min') },
            { name: 'max', message: message('formly.validation.max') },
            { name: 'minlength', message: message('formly.validation.minlength') },
            { name: 'maxlength', message: message('formly.validation.maxlength') },
            { name: 'pattern', message: message('formly.validation.pattern') },
            { name: 'email', message: message('formly.validation.email') },
          ],
        };
      },
    },
  ];
}
