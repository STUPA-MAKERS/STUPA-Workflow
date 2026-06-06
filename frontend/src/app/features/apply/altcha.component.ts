import { ChangeDetectionStrategy, Component, output, signal } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

type AltchaState = 'idle' | 'verifying' | 'solved';

/**
 * Altcha-Widget — **Stub** (T-30). Bildet den Proof-of-Work-Flow nach (Klick →
 * „rechnet" → gelöst) und liefert eine Lösungs-Zeichenkette an den Wizard. Die
 * echte Altcha-Integration (Challenge vom Backend, WASM-Solver) folgt mit der
 * Härtung (T-41 / api.md §1 „Altcha + Rate-Limit"). Das Submit ist erst nach
 * `solved` möglich.
 */
@Component({
  selector: 'app-altcha',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    <div class="altcha" [attr.data-state]="state()">
      <button
        type="button"
        class="altcha__btn"
        [disabled]="state() !== 'idle'"
        (click)="solve()"
      >
        <span class="altcha__box" aria-hidden="true">
          @switch (state()) {
            @case ('solved') {
              ✓
            }
            @case ('verifying') {
              <span class="altcha__spinner"></span>
            }
          }
        </span>
        <span class="altcha__label">
          @switch (state()) {
            @case ('idle') {
              {{ 'altcha.idle' | t }}
            }
            @case ('verifying') {
              {{ 'altcha.verifying' | t }}
            }
            @case ('solved') {
              {{ 'altcha.solved' | t }}
            }
          }
        </span>
      </button>
      <p class="altcha__note" role="status">
        @if (state() === 'solved') {
          {{ 'altcha.noteSolved' | t }}
        } @else {
          {{ 'altcha.note' | t }}
        }
      </p>
    </div>
  `,
  styles: [
    `
      .altcha {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .altcha__btn {
        display: inline-flex;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-3) var(--space-4);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        cursor: pointer;
        font: inherit;
        color: var(--color-text);
        align-self: flex-start;
      }
      .altcha__btn:disabled {
        cursor: default;
      }
      .altcha[data-state='solved'] .altcha__btn {
        border-color: var(--color-success);
      }
      .altcha__box {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.4rem;
        height: 1.4rem;
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-sm);
        color: var(--color-success);
        font-weight: var(--fw-semibold);
      }
      .altcha__spinner {
        width: 0.9rem;
        height: 0.9rem;
        border: 2px solid var(--color-text-muted);
        border-right-color: transparent;
        border-radius: var(--radius-pill);
        animation: altcha-spin 0.6s linear infinite;
      }
      @keyframes altcha-spin {
        to {
          transform: rotate(360deg);
        }
      }
      .altcha__note {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
    `,
  ],
})
export class AltchaComponent {
  /** Emittiert die (Stub-)Lösung, sobald die Challenge „gelöst" ist. */
  readonly solved = output<string>();

  readonly state = signal<AltchaState>('idle');

  solve(): void {
    if (this.state() !== 'idle') return;
    this.state.set('verifying');
    // Stub: kurze „Rechenzeit", dann fixe Lösung. Echter Solver in T-41.
    setTimeout(() => {
      this.state.set('solved');
      this.solved.emit('altcha-stub-solution');
    }, 300);
  }
}
