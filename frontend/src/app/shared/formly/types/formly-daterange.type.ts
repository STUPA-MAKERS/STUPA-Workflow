import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';

/** Value of the `daterange` form-definition field: two ISO date strings. */
interface DateRange {
  from?: string;
  to?: string;
}

/**
 * Formly field type `daterange` — a {from, to} range built from two date inputs
 * (form definition `daterange`). The stored value is an object; the backend checks
 * `from <= to`. An empty shell ⇒ `null`, so `required` applies.
 */
@Component({
  selector: 'app-formly-daterange',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dr">
      <span class="dr__label">
        {{ props.label }}
        @if (props.required) {
          <span class="dr__req" aria-hidden="true">*</span>
        }
      </span>
      <div class="dr__row">
        <label class="dr__field">
          <span class="dr__cap">{{ props['fromLabel'] ?? 'Von' }}</span>
          <input
            type="date"
            [value]="range.from ?? ''"
            (input)="patch('from', $event)"
            [attr.aria-invalid]="showError ? 'true' : null"
          />
        </label>
        <label class="dr__field">
          <span class="dr__cap">{{ props['toLabel'] ?? 'Bis' }}</span>
          <input
            type="date"
            [value]="range.to ?? ''"
            (input)="patch('to', $event)"
            [attr.aria-invalid]="showError ? 'true' : null"
          />
        </label>
      </div>
      @if (props.description && !showError) {
        <p class="dr__hint">{{ props.description }}</p>
      }
      @if (showError) {
        <p class="dr__error" role="alert">{{ props['errorText'] ?? 'Ungültiger Zeitraum.' }}</p>
      }
    </div>
  `,
  styles: [
    `
      .dr {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .dr__row {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-3);
      }
      .dr__field {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        flex: 1 1 8rem;
      }
      .dr__label {
        font-size: var(--fs-md);
        color: var(--color-text);
      }
      .dr__cap {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .dr__req {
        color: var(--color-danger);
      }
      .dr__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .dr__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class FormlyDateRangeType extends FieldType<FieldTypeConfig> {
  get range(): DateRange {
    const v = this.formControl.value as DateRange | null;
    return v && typeof v === 'object' ? v : {};
  }

  patch(key: 'from' | 'to', ev: Event): void {
    const value = (ev.target as HTMLInputElement).value;
    const next: DateRange = { ...this.range, [key]: value || undefined };
    const empty = !next.from && !next.to;
    this.formControl.setValue(empty ? null : next);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
  }
}
