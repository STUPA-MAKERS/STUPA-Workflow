import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';

/** Formly-Feldtyp `display` — nicht-editierbarer Inhalt: Info-Text (`markdown`)
 * oder abgeleiteter Wert (`computed`). Liefert keinen Antragsteller-Input. */
@Component({
  selector: 'app-formly-display',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (isHeading) {
      <div class="display__heading">
        <h3 class="display__headingTitle">{{ props.label || text }}</h3>
        @if (props.description) {
          <p class="display__headingSub">{{ props.description }}</p>
        }
      </div>
    } @else {
      <div class="display" [class.display--computed]="isComputed">
        @if (props.label) {
          <span class="display__label">{{ props.label }}</span>
        }
        <p class="display__value">{{ text }}</p>
      </div>
    }
  `,
  styles: [
    `
      .display__heading {
        margin-top: var(--space-2);
        padding-bottom: var(--space-2);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .display__headingTitle {
        margin: 0;
        font-size: var(--fs-md);
      }
      .display__headingSub {
        margin: var(--space-1) 0 0;
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
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

  /** Abschnitts-/Gruppen-Überschrift (statt Wert-Anzeige). */
  get isHeading(): boolean {
    return Boolean(this.props['heading']);
  }

  get text(): string {
    if (this.isComputed) {
      const v = this.formControl.value;
      return v === null || v === undefined || v === '' ? '—' : String(v);
    }
    return (this.props['text'] as string | undefined) ?? '';
  }
}
