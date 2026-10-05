import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { DatepickerComponent } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** Value of the `daterange` form-definition field: two ISO date strings. */
interface DateRange {
  from?: string;
  to?: string;
}

/**
 * Formly field type `daterange` that builds a {from, to} range from two date fields.
 *
 * Each end is the UI-kit datepicker: the filled field of the other form fields, the
 * date in the format of the app language (DE: TT.MM.JJJJ) and the calendar button. The
 * field label is the legend of the group; the two boxes carry "Von" and "Bis". The end
 * cannot lie before the start in the calendar (`min`/`max` coupling).
 *
 * The form definition calls this field `daterange`. The stored value is an object. The
 * backend checks `from <= to`. An empty shell becomes `null`, so `required` applies.
 */
@Component({
  selector: 'app-formly-daterange',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DatepickerComponent, TranslatePipe],
  template: `
    <fieldset
      class="dr"
      [attr.aria-describedby]="props.description && !showError ? controlId + '-hint' : null"
      (focusout)="formControl.markAsTouched()"
    >
      <legend class="dr__legend">
        {{ props.label }}
        @if (props.required) {
          <span class="dr__req" aria-hidden="true">*</span>
        }
      </legend>
      <div class="dr__row">
        <app-datepicker
          class="dr__field"
          [id]="controlId + '-from'"
          [label]="props['fromLabel'] ?? ('formly.daterange.from' | t)"
          [required]="!!props.required"
          [max]="range.to ?? ''"
          [error]="showError && !range.from ? errorText : ''"
          [ngModel]="range.from ?? ''"
          [ngModelOptions]="{ standalone: true }"
          (ngModelChange)="patch('from', $event)"
        />
        <app-datepicker
          class="dr__field"
          [id]="controlId + '-to'"
          [label]="props['toLabel'] ?? ('formly.daterange.to' | t)"
          [required]="!!props.required"
          [min]="range.from ?? ''"
          [error]="showError && (range.from || !range.to) ? errorText : ''"
          [ngModel]="range.to ?? ''"
          [ngModelOptions]="{ standalone: true }"
          (ngModelChange)="patch('to', $event)"
        />
      </div>
      @if (props.description && !showError) {
        <p class="dr__hint" [id]="controlId + '-hint'">{{ props.description }}</p>
      }
    </fieldset>
  `,
  styles: [
    `
      .dr {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        min-width: 0;
        margin: 0;
        padding: 0;
        border: 0;
      }
      .dr__legend {
        padding: 0 var(--space-1);
        margin-bottom: var(--space-2);
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .dr__req {
        color: var(--color-danger);
      }
      /* Two boxes side by side; on a narrow column they stack. */
      .dr__row {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-3);
      }
      .dr__field {
        flex: 1 1 12rem;
      }
      .dr__hint {
        margin: 0;
        padding-inline: var(--space-4);
        font-size: var(--fs-small);
        line-height: var(--lh-small);
        color: var(--color-text-muted);
      }
    `,
  ],
})
export class FormlyDateRangeType extends FieldType<FieldTypeConfig> {
  private readonly i18n = inject(I18nService);

  get controlId(): string {
    return `${this.field.id ?? 'app-daterange'}`;
  }

  get range(): DateRange {
    const v = this.formControl.value as DateRange | null;
    return v && typeof v === 'object' ? v : {};
  }

  /**
   * The error text of the range. An empty end shows it in its box; a range with both
   * ends shows it in the "Bis" box. `props.errorText` wins (a 422 of the server).
   */
  get errorText(): string {
    const own = this.props['errorText'] as string | undefined;
    if (own) return own;
    return this.i18n.translate(
      this.formControl.hasError('required') ? 'formly.validation.required' : 'formly.daterange.error',
    );
  }

  patch(key: 'from' | 'to', value: string): void {
    const next: DateRange = { ...this.range, [key]: value || undefined };
    const empty = !next.from && !next.to;
    this.formControl.setValue(empty ? null : next);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
  }
}
