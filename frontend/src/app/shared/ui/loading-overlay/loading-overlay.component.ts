import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LoadingService } from '@core/loading/loading.service';

/**
 * Globaler Ladebildschirm (#loading): halbtransparenter Overlay über dem
 * Inhaltsbereich (unterhalb des Headers) mit zentriertem Spinner, gesteuert vom
 * {@link LoadingService}. Header/Navigation bleiben bedienbar. Liegt unter
 * Dialogen/Toasts (z-index), damit diese darüber sichtbar bleiben.
 */
@Component({
  selector: 'app-loading-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    @if (loading.visible()) {
      <div class="lo" role="status" aria-live="polite">
        <div class="lo__box">
          <span class="lo__spinner" aria-hidden="true"></span>
          <span class="lo__text">{{ 'app.loading' | t }}</span>
        </div>
      </div>
    }
  `,
  styles: [
    `
      .lo {
        position: fixed;
        top: var(--layout-header-height);
        inset-inline: 0;
        bottom: 0;
        z-index: 1100;
        display: flex;
        align-items: center;
        justify-content: center;
        background: color-mix(in srgb, var(--color-bg, #000) 55%, transparent);
        backdrop-filter: blur(1px);
        animation: lo-fade 120ms ease-out;
      }
      .lo__box {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-5) var(--space-6);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        box-shadow: var(--shadow-lg);
      }
      .lo__spinner {
        width: 2.25rem;
        height: 2.25rem;
        border-radius: 999px;
        border: 3px solid var(--color-border-strong, currentColor);
        border-top-color: var(--color-primary);
        animation: lo-spin 0.7s linear infinite;
      }
      .lo__text {
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
      @keyframes lo-spin {
        to {
          transform: rotate(360deg);
        }
      }
      @keyframes lo-fade {
        from {
          opacity: 0;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .lo {
          animation: none;
        }
        .lo__spinner {
          animation-duration: 1.5s;
        }
      }
    `,
  ],
})
export class LoadingOverlayComponent {
  protected readonly loading = inject(LoadingService);
}
