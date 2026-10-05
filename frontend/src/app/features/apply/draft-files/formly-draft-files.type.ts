import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { I18nService } from '@core/i18n/i18n.service';
import { DraftFilesComponent } from './draft-files.component';

/**
 * Formly field of a `file` field in the apply wizard: the draft uploads of that field
 * (Z4). The value is the list of the attachment ids, which the server checks against
 * `attachmentIds` on the submit. The wizard sets this type on its `file` fields; every
 * other form keeps the plain reference field.
 */
@Component({
  selector: 'app-formly-draft-files',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DraftFilesComponent],
  template: `
    <app-draft-files
      [fieldKey]="fieldKey"
      [heading]="props.label ?? ''"
      [required]="!!props.required"
      [error]="showError ? errorText : null"
      (changed)="onChanged($event)"
    />
  `,
})
export class FormlyDraftFilesType extends FieldType<FieldTypeConfig> {
  private readonly i18n = inject(I18nService);

  get fieldKey(): string {
    return String(this.key ?? '');
  }

  get errorText(): string {
    return this.i18n.translate('apply.files.required');
  }

  onChanged(ids: string[]): void {
    this.formControl.setValue(ids.length ? ids : null);
    this.formControl.markAsTouched();
  }
}
