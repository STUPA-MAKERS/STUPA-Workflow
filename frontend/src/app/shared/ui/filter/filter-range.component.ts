import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Min/Max- bzw. Von/Bis-Bereich im Filter-Popover: zwei projizierte Controls mit
 * einem Trenner dazwischen. Slots: `[start]` und `[end]`.
 *
 * ```html
 * <app-filter-range>
 *   <input start type="date" … />
 *   <input end type="date" … />
 * </app-filter-range>
 * ```
 */
@Component({
  selector: 'app-filter-range',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="filter-range">
      <ng-content select="[start]" />
      <span class="filter-range__sep" aria-hidden="true">{{ separator() }}</span>
      <ng-content select="[end]" />
    </div>
  `,
  styles: [
    `
      .filter-range {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        min-width: 0;
      }
      .filter-range__sep {
        color: var(--color-text-muted);
        flex: 0 0 auto;
      }
      /* app-currency-input als Flex-Item behandeln (bringt eigenes Styling mit). */
      :host ::ng-deep app-currency-input {
        flex: 1 1 0;
        min-width: 0;
      }
      :host ::ng-deep input:not(.cur__input),
      :host ::ng-deep select {
        width: 100%;
        min-width: 0;
        flex: 1 1 0;
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-bg);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font: inherit;
        font-size: var(--fs-md);
      }
      /* Zahlen-Spinner ausblenden — wirkt im schmalen Popout unruhig. */
      :host ::ng-deep input[type='number'] {
        -moz-appearance: textfield;
        appearance: textfield;
      }
      :host ::ng-deep input[type='number']::-webkit-outer-spin-button,
      :host ::ng-deep input[type='number']::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
      }
    `,
  ],
})
export class FilterRangeComponent {
  /** Trennzeichen zwischen den beiden Controls. */
  readonly separator = input('–');
}
