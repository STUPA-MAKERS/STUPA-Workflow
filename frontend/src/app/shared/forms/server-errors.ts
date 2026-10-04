import type { FormlyFieldConfig } from '@ngx-formly/core';
import type { TranslationKey } from '@core/i18n/translations';

/** One entry of `errors` in a 422 problem+json answer. */
export interface ServerFieldError {
  field: string;
  msg: string;
}

/** The answer key of an error path: `positions[1].offers[0]` gives `positions`. */
export function errorRootKey(path: string): string {
  return path.replace(/[.[].*$/, '');
}

/** The position of an error path of a `positions` field: `positions[1]…` gives 1. */
export function errorPositionIndex(path: string): number | null {
  const m = /^[^[.]+\[(\d+)\]/.exec(path);
  return m ? Number(m[1]) : null;
}

/**
 * The message for one error of a cost position, by the text of the server
 * (forms/validation.py `_validate_positions`). The texts of the server are English and
 * technical, so the view names the rule in the UI language.
 */
export function positionErrorKey(error: ServerFieldError): TranslationKey {
  const msg = error.msg.toLowerCase();
  if (/\.offers\[\d+\]/.test(error.field)) return 'apply.positions.errOffers';
  if (msg.includes('needs a reason')) return 'apply.positions.errNoOffersReason';
  if (msg.includes('not allowed here')) return 'forms.positions.errNoWaiver';
  if (msg.includes('comparison offer')) {
    if (msg.includes('has more than')) return 'forms.positions.errTooManyOffers';
    if (msg.includes('needs at least')) return 'forms.positions.errOffersServer';
    return 'forms.errors.server';
  }
  if (msg.includes('preferred')) return 'apply.positions.errPreferred';
  if (msg.includes('label')) return 'apply.positions.errLabel';
  return 'forms.errors.server';
}

/** Find the field config of an answer key, also inside field groups. */
export function findFieldByKey(
  fields: readonly FormlyFieldConfig[],
  key: string,
): FormlyFieldConfig | undefined {
  for (const f of fields) {
    if (f.key === key) return f;
    const inner = f.fieldGroup ? findFieldByKey(f.fieldGroup, key) : undefined;
    if (inner) return inner;
  }
  return undefined;
}

/**
 * Show the field errors of a 422 answer on the fields of a Formly form.
 *
 * A plain field gets the message under it and counts as invalid until the next change of
 * its value. A `positions` field gets the message on the position the path names (props
 * `serverErrors`, index → text); the positions editor opens that position. The function
 * returns the number of errors it could place; the caller shows a toast for the rest.
 */
export function applyServerErrors(
  fields: readonly FormlyFieldConfig[],
  errors: readonly ServerFieldError[],
  translate: (key: TranslationKey) => string,
): number {
  let placed = 0;
  const byPosition = new Map<FormlyFieldConfig, Record<number, string>>();
  for (const error of errors) {
    const field = findFieldByKey(fields, errorRootKey(error.field));
    const control = field?.formControl;
    if (!field || !control) continue;
    placed++;
    if (field.type === 'positions') {
      const index = errorPositionIndex(error.field);
      const map = byPosition.get(field) ?? {};
      const at = index ?? -1;
      // The first error of a position wins: it is the one the editor shows.
      map[at] ??= translate(index === null ? 'forms.errors.server' : positionErrorKey(error));
      byPosition.set(field, map);
      continue;
    }
    field.props ??= {};
    field.props['errorText'] = translate('forms.errors.server');
    control.setErrors({ ...(control.errors ?? {}), server: true });
    control.markAsTouched();
    // The server text holds until the next change of the value.
    const sub = control.valueChanges.subscribe(() => {
      sub.unsubscribe();
      if (field.props) delete field.props['errorText'];
    });
    field.options?.detectChanges?.(field);
  }
  for (const [field, map] of byPosition) {
    field.props ??= {};
    field.props['serverErrors'] = map;
    field.formControl?.setErrors({ ...(field.formControl.errors ?? {}), server: true });
    field.formControl?.markAsTouched();
    field.options?.detectChanges?.(field);
  }
  return placed;
}

/** Remove the server messages of an earlier save from every field. */
export function clearServerErrors(fields: readonly FormlyFieldConfig[]): void {
  for (const f of fields) {
    if (f.props) {
      delete f.props['serverErrors'];
      delete f.props['errorText'];
    }
    if (f.fieldGroup) clearServerErrors(f.fieldGroup);
  }
}
