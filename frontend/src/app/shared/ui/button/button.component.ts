import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

/** Basis-Button des UI-Kits. Clean/minimal, CD-Tokens, a11y-Fokus. */
@Component({
  selector: 'app-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      [type]="type"
      [disabled]="disabled || loading"
      [attr.aria-busy]="loading ? 'true' : null"
      [class]="'btn btn--' + variant + ' btn--' + size"
    >
      @if (loading) {
        <span class="btn__spinner" aria-hidden="true"></span>
      }
      <span class="btn__label"><ng-content /></span>
    </button>
  `,
  styles: [
    `
      :host {
        display: inline-flex;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: var(--space-2);
        font-weight: var(--fw-semibold);
        line-height: 1;
        border: var(--border-width) solid transparent;
        border-radius: var(--radius-md);
        cursor: pointer;
        white-space: nowrap;
        transition:
          background-color var(--motion-fast) var(--ease-standard),
          color var(--motion-fast) var(--ease-standard),
          border-color var(--motion-fast) var(--ease-standard);
      }
      .btn:disabled {
        opacity: 0.55;
        cursor: not-allowed;
      }
      .btn--sm {
        padding: var(--space-2) var(--space-3);
        font-size: var(--fs-sm);
      }
      .btn--md {
        padding: var(--space-3) var(--space-5);
        font-size: var(--fs-md);
      }
      .btn--lg {
        padding: var(--space-4) var(--space-6);
        font-size: var(--fs-lg);
      }
      .btn--primary {
        background: var(--color-primary);
        color: var(--color-on-primary);
      }
      .btn--primary:hover:not(:disabled) {
        background: var(--color-primary-hover);
      }
      .btn--secondary {
        background: var(--color-surface);
        color: var(--color-text);
        border-color: var(--color-border-strong);
      }
      .btn--secondary:hover:not(:disabled) {
        background: var(--color-surface-sunken);
      }
      .btn--ghost {
        background: transparent;
        color: var(--color-primary);
      }
      .btn--ghost:hover:not(:disabled) {
        background: var(--color-primary-subtle);
      }
      .btn--danger {
        background: var(--color-danger);
        color: var(--color-text-inverse);
      }
      .btn__spinner {
        width: 1em;
        height: 1em;
        border: 2px solid currentColor;
        border-right-color: transparent;
        border-radius: var(--radius-pill);
        animation: btn-spin 0.6s linear infinite;
      }
      @keyframes btn-spin {
        to {
          transform: rotate(360deg);
        }
      }
    `,
  ],
})
export class ButtonComponent {
  @Input() variant: ButtonVariant = 'primary';
  @Input() size: ButtonSize = 'md';
  @Input() type: 'button' | 'submit' | 'reset' = 'button';
  @Input() disabled = false;
  @Input() loading = false;
}
