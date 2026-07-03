import type { Provider } from '@angular/core';
import { provideFormlyCore } from '@ngx-formly/core';
import { FormlyInputType } from './formly-input.type';
import { FormlyTextareaType } from './types/formly-textarea.type';
import { FormlySelectType } from './types/formly-select.type';
import { FormlyCheckboxType } from './types/formly-checkbox.type';
import { FormlyMultiCheckboxType } from './types/formly-multicheckbox.type';
import { FormlyDisplayType } from './types/formly-display.type';
import { FormlyPositionsType } from './types/formly-positions.type';
import { FormlyDateRangeType } from './types/formly-daterange.type';

/**
 * Formly base configuration. Registers the UI-kit-bound field types for the form
 * definition: `input` covers text/number/currency/date (via `props.type`), plus
 * textarea/select/checkbox/multicheckbox and a read-only `display` for
 * `markdown`/`computed`. Mapping in `@shared/forms/formly-mapper`.
 */
export function provideFormly(): Provider {
  return provideFormlyCore({
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
    validationMessages: [
      { name: 'required', message: 'Dieses Feld ist erforderlich.' },
      { name: 'min', message: 'Wert ist zu klein.' },
      { name: 'max', message: 'Wert ist zu groß.' },
      { name: 'minlength', message: 'Eingabe ist zu kurz.' },
      { name: 'maxlength', message: 'Eingabe ist zu lang.' },
      { name: 'pattern', message: 'Eingabe hat ein ungültiges Format.' },
      { name: 'email', message: 'Bitte eine gültige E-Mail-Adresse eingeben.' },
    ],
  });
}
