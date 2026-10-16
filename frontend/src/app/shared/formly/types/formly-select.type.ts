import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  SelectFieldComponent,
  type SelectFieldOption,
} from '@shared/ui/select/select.component';

/**
 * Formly field type `select`: single choice (form definition `select`, `gremium_select`,
 * `budget_select`), in the apply wizard, the edit form of the detail and the status page.
 *
 * It renders the app's select field (`app-select`): the filled field with the app's option
 * list, a popover on a wide screen and the bottom sheet on a phone. The placeholder shows
 * while no option is chosen, but the list has no row for it: once chosen, a value cannot
 * go back to empty, as with the disabled placeholder option of a native select.
 */
@Component({
  selector: 'app-formly-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, SelectFieldComponent, TranslatePipe],
  template: `
    <app-select
      [id]="controlId"
      [formControl]="formControl"
      [label]="props.label ?? ''"
      [required]="!!props.required"
      [clearable]="false"
      [placeholder]="props.placeholder || ('formly.select.placeholder' | t)"
      [options]="optionList"
      [hint]="props.description ?? ''"
      [error]="showError ? (props['errorText'] ?? ('formly.select.error' | t)) : ''"
    />
  `,
})
export class FormlySelectType extends FieldType<FieldTypeConfig> {
  get controlId(): string {
    return `${this.field.id ?? 'app-select'}`;
  }
  get optionList(): SelectFieldOption[] {
    return (this.props.options as SelectFieldOption[] | undefined) ?? [];
  }
}
