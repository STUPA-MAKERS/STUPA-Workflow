import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { InputComponent } from '../ui/input/input.component';

/**
 * Formly-Feldtyp `input`, der das UI-Kit-Input nutzt — Brücke zwischen der
 * Form-Definition (forms-Engine, T-11) und dem Design-System.
 */
@Component({
  selector: 'app-formly-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, InputComponent],
  template: `
    <app-input
      [formControl]="formControl"
      [label]="props.label ?? ''"
      [type]="props.type ?? 'text'"
      [placeholder]="props.placeholder ?? ''"
      [required]="!!props.required"
      [hint]="props['hint'] ?? ''"
      [error]="showError && formControl.errors ? (props['errorText'] ?? 'Ungültige Eingabe') : ''"
    />
  `,
})
export class FormlyInputType extends FieldType<FieldTypeConfig> {}
