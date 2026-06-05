import type { Provider } from '@angular/core';
import { provideFormlyCore } from '@ngx-formly/core';
import { FormlyInputType } from './formly-input.type';
import { FormlyTextareaType } from './types/formly-textarea.type';
import { FormlySelectType } from './types/formly-select.type';
import { FormlyCheckboxType } from './types/formly-checkbox.type';
import { FormlyMultiCheckboxType } from './types/formly-multicheckbox.type';
import { FormlyDisplayType } from './types/formly-display.type';

/**
 * Formly-Grundkonfiguration. Registriert die UI-Kit-gebundenen Feldtypen für die
 * Form-Definition (config_schemas §5.1): `input` deckt text/number/currency/date
 * (über `props.type`), dazu textarea/select/checkbox/multicheckbox sowie ein
 * read-only `display` für `markdown`/`computed`. Mapping in
 * `@shared/forms/formly-mapper`.
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
