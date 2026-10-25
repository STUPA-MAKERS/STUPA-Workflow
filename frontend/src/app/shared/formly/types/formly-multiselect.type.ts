import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import {
  CheckboxComponent,
  IconComponent,
  matchesMedia,
  MEDIA,
  type SheetSide,
  SideSheetComponent,
} from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

interface MultiOption {
  value: string;
  label: string;
}

/**
 * Formly field type `multiselect`: several choices in one field box, as a dropdown
 * (board Anträge-Bearbeiten, "Kategorie: Party, Erstsemester").
 *
 * The box looks like the `select` field and shows the chosen labels, joined by a comma.
 * A click anywhere on the box opens the choices in the shared sheet, as the "Status"
 * filter of the applications list does: from the end on a wide screen, from the bottom
 * on a phone. Each click on a choice applies at once. The model value is a string array
 * of the chosen option values; the order of the options is kept.
 *
 * The edit form of the detail uses it, so the field takes half a row
 * (`toFormlySections`). The apply wizard keeps the checkbox list (`multicheckbox`).
 */
@Component({
  selector: 'app-formly-multiselect',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, CheckboxComponent, IconComponent, SideSheetComponent, TranslatePipe],
  template: `
    <div class="field">
      <div class="field__box" [class.field__box--invalid]="showError">
        <span class="field__label" [id]="controlId + '-label'">
          {{ props.label }}
          @if (props.required) {
            <span class="field__req" aria-hidden="true">*</span>
          }
        </span>
        <button
          type="button"
          class="field__control msel__trigger"
          [id]="controlId"
          aria-haspopup="dialog"
          [attr.aria-expanded]="open()"
          [attr.aria-labelledby]="controlId + '-label ' + controlId + '-value'"
          [attr.aria-invalid]="showError ? 'true' : null"
          [attr.aria-describedby]="describedBy"
          (click)="show()"
        >
          <span class="msel__value" [class.msel__value--empty]="!summary" [id]="controlId + '-value'">
            {{ summary || props.placeholder || ('formly.select.placeholder' | t) }}
          </span>
        </button>
        <app-icon class="field__chevron" name="down" [size]="18" />
      </div>
      @if (props.description && !showError) {
        <p class="field__hint" [id]="controlId + '-hint'">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="field__error" [id]="controlId + '-error'" role="alert">
          {{ props['errorText'] ?? ('formly.multicheckbox.error' | t) }}
        </p>
      }
    </div>

    <app-side-sheet
      [side]="side()"
      [heading]="props.label ?? ''"
      [open]="open()"
      (openChange)="open.set($event)"
      (closed)="formControl.markAsTouched()"
    >
      <div class="rowgroup rowgroup--bg3" role="group" [attr.aria-label]="props.label">
        @for (opt of optionList; track opt.value) {
          <div class="msel__check">
            <app-checkbox
              [ngModel]="isChecked(opt.value)"
              [ngModelOptions]="{ standalone: true }"
              (ngModelChange)="toggle(opt.value, $event)"
              >{{ opt.label }}</app-checkbox
            >
          </div>
        }
      </div>
    </app-side-sheet>
  `,
  styleUrls: ['./formly-select.type.scss', './formly-multiselect.type.scss'],
})
export class FormlyMultiSelectType extends FieldType<FieldTypeConfig> {
  protected readonly open = signal(false);
  protected readonly side = signal<SheetSide>('end');

  get controlId(): string {
    return `${this.field.id ?? 'app-multiselect'}`;
  }

  get optionList(): MultiOption[] {
    return (this.props.options as MultiOption[] | undefined) ?? [];
  }

  get describedBy(): string | null {
    if (this.showError) return `${this.controlId}-error`;
    if (this.props.description) return `${this.controlId}-hint`;
    return null;
  }

  /** The chosen labels in the order of the options, joined by a comma. */
  get summary(): string {
    const chosen = new Set(this.current());
    return this.optionList
      .filter((o) => chosen.has(o.value))
      .map((o) => o.label)
      .join(', ');
  }

  protected show(): void {
    const phone = matchesMedia(MEDIA.phone);
    this.side.set(phone ? 'bottom' : 'end');
    this.open.set(true);
  }

  private current(): string[] {
    const v: unknown = this.formControl.value;
    return Array.isArray(v) ? (v as string[]) : [];
  }

  isChecked(value: string): boolean {
    return this.current().includes(value);
  }

  /** The order of the options stays, so the summary and the stored answer stay stable. */
  toggle(value: string, checked: boolean): void {
    const set = new Set(this.current());
    if (checked) set.add(value);
    else set.delete(value);
    const order = this.optionList.map((o) => o.value);
    const next = [...set].sort((a, b) => order.indexOf(a) - order.indexOf(b));
    this.formControl.setValue(next);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
  }
}
