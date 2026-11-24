import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { SectionComponent } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import type { ComputedFormat } from '@core/api/models';
import { formatComputed } from '@shared/forms/answer-format';

/**
 * Formly field type `display` for content that the applicant cannot edit.
 *
 * The content is an info text (`markdown`) or a derived value (`computed`). The field
 * collects no applicant input. A computed value shows in its `format` in the language of
 * the interface (specs 002842, 002964): `money` as EUR, `percent` as a percent.
 */
@Component({
  selector: 'app-formly-display',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SectionComponent],
  template: `
    @if (isHeading) {
      <app-section class="display__heading" [heading]="props.label || text" [headingLang]="props['textLang'] ?? null">
        @if (props.description) {
          <p class="display__headingSub" [attr.lang]="props['textLang'] ?? null">{{ props.description }}</p>
        }
      </app-section>
    } @else {
      <div class="display" [class.display--computed]="isComputed">
        @if (props.label) {
          <span class="display__label" [attr.lang]="props['textLang'] ?? null">{{ props.label }}</span>
        }
        <p class="display__value">{{ text }}</p>
      </div>
    }
  `,
  styles: [
    `
      .display__heading {
        margin-top: var(--space-3);
      }
      .display__headingSub {
        margin: 0;
        padding: 0 var(--space-1);
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
      .display {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      /* The box of a labelled input: its height, corner, label line and value line. */
      .display--computed {
        box-sizing: border-box;
        min-height: var(--field-height);
        justify-content: space-between;
        gap: 0;
        padding: 8px var(--space-4) 10px;
        background: var(--color-surface-sunken);
        border-radius: var(--radius-field);
      }
      .display--computed .display__label {
        font-size: 0.75rem;
        line-height: 1rem;
        color: var(--color-text-subtle);
      }
      .display--computed .display__value {
        margin: 0;
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
  private readonly i18n = inject(I18nService);

  get isComputed(): boolean {
    return Boolean(this.props['computed']);
  }

  /** True for a section or group heading instead of a value display. */
  get isHeading(): boolean {
    return Boolean(this.props['heading']);
  }

  get text(): string {
    if (this.isComputed) {
      const v = this.formControl.value;
      if (v === null || v === undefined || v === '') return '—';
      const format = (this.props['format'] as ComputedFormat | undefined) ?? 'number';
      return formatComputed(format, v, this.i18n.formatLocale());
    }
    return (this.props['text'] as string | undefined) ?? '';
  }
}
