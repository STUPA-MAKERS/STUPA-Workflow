import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ToastService } from './toast.service';

/** Toast-Container — einmal im Shell-Layout platziert. ARIA-Live-Region. */
@Component({
  selector: 'app-toast',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    <div class="toasts" aria-live="polite" aria-atomic="false">
      @for (toast of toastService.toasts(); track toast.id) {
        <div class="toast" [class]="'toast--' + toast.variant" role="status">
          <span class="toast__msg">{{ toast.message }}</span>
          <button
            type="button"
            class="toast__close"
            [attr.aria-label]="'action.close' | t"
            (click)="toastService.dismiss(toast.id)"
          >
            ✕
          </button>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .toasts {
        position: fixed;
        inset-block-end: var(--space-5);
        inset-inline-end: var(--space-5);
        z-index: var(--z-toast);
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        max-width: min(92vw, 24rem);
      }
      .toast {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-3) var(--space-4);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-md);
        border-inline-start: 3px solid currentColor;
        background: var(--color-bg-elevated);
        color: var(--color-text);
      }
      .toast--success {
        border-color: var(--color-success);
      }
      .toast--warning {
        border-color: var(--color-warning);
      }
      .toast--danger {
        border-color: var(--color-danger);
      }
      .toast--info {
        border-color: var(--color-info);
      }
      .toast__msg {
        flex: 1;
        font-size: var(--fs-sm);
      }
      .toast__close {
        background: transparent;
        border: 0;
        cursor: pointer;
        color: var(--color-text-muted);
      }
    `,
  ],
})
export class ToastComponent {
  readonly toastService = inject(ToastService);
}
