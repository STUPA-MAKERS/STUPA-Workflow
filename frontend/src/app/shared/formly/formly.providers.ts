import type { Provider } from '@angular/core';
import { provideFormlyCore } from '@ngx-formly/core';
import { FormlyInputType } from './formly-input.type';

/**
 * Formly-Grundkonfiguration. Registriert die UI-Kit-gebundenen Feldtypen.
 * Weitere Typen (select, textarea, file, repeat …) kommen mit den Formularen
 * der Feature-Tasks (T-11/T-30) hinzu.
 */
export function provideFormly(): Provider {
  return provideFormlyCore({
    types: [{ name: 'input', component: FormlyInputType }],
    validationMessages: [{ name: 'required', message: 'Dieses Feld ist erforderlich.' }],
  });
}
