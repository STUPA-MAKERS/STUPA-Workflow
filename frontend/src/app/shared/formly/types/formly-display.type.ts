import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';

/** Formly-Feldtyp `display` — nicht-editierbarer Inhalt: Info-Text (`markdown`)
 * oder abgeleiteter Wert (`computed`). Liefert keinen Antragsteller-Input. */
@Component({
  selector: 'app-formly-display',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="display" [class.display--computed]="isComputed">
      @if (props.label) {
        <span class="display__label">{{ props.label }}</span>
      }
      <p class="display__value">{{ text }}</p>
    </div>
  `,
  styles: [
    `
      .display {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .display--computed {
        padding: var(--space-3) var(--space-4);
        background: var(--color-surface-sunken);
        border-radius: var(--radius-md);
      }
      .display__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .display__value {
        font-size: var(--fs-md);
        color: var(--color-text-muted);
        white-space: pre-line;
      }
    `,
  ],
})
export class FormlyDisplayType extends FieldType<FieldTypeConfig> {
  get isComputed(): boolean {
    return Boolean(this.props['computed']);
  }

  get text(): string {
    if (this.isComputed) {
      const v = this.formControl.value;
      return v === null || v === undefined || v === '' ? '—' : String(v);
    }
    return (this.props['text'] as string | undefined) ?? '';
  }
}
