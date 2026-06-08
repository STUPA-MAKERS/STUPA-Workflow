import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';

type AltchaState = 'idle' | 'verifying' | 'solved' | 'error';

/**
 * Altcha-Widget (Issue #23). Holt eine **server-signierte** PoW-Challenge
 * (`GET /altcha/challenge`), löst den Proof-of-Work lokal (sucht `number` mit
 * `SHA-256(salt+number) == challenge` per Web-Crypto) und liefert die
 * Base64-Lösung an den Wizard. Ohne konfiguriertes Altcha (404) meldet das
 * Widget `unavailable` → der Wizard verlangt dann keine Lösung. Das Submit ist
 * erst nach `solved` (bzw. `unavailable`) möglich.
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
        [disabled]="state() === 'verifying' || state() === 'solved'"
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
            @case ('error') {
              {{ 'altcha.error' | t }}
            }
          }
        </span>
      </button>
      <p class="altcha__note" role="status">
        @switch (state()) {
          @case ('solved') {
            {{ 'altcha.noteSolved' | t }}
          }
          @case ('error') {
            {{ 'altcha.noteError' | t }}
          }
          @default {
            {{ 'altcha.note' | t }}
          }
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
      .altcha[data-state='error'] .altcha__btn {
        border-color: var(--color-danger);
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
  private readonly api = inject(ApiClient);

  /** Emittiert die Base64-PoW-Lösung, sobald die Challenge gelöst ist. */
  readonly solved = output<string>();
  /** Emittiert, wenn Altcha serverseitig deaktiviert ist (kein Captcha nötig). */
  readonly unavailable = output<void>();

  readonly state = signal<AltchaState>('idle');

  async solve(): Promise<void> {
    if (this.state() === 'verifying' || this.state() === 'solved') return;
    this.state.set('verifying');
    try {
      const challenge = await firstValueFrom(this.api.altchaChallenge());
      if (!challenge) {
        // Altcha aus (404) → kein Captcha erforderlich.
        this.state.set('solved');
        this.unavailable.emit();
        return;
      }
      const solution = await this.solveChallenge(challenge);
      this.state.set('solved');
      this.solved.emit(solution);
    } catch {
      this.state.set('error');
    }
  }

  /** Proof-of-Work lösen: `number` finden mit `SHA-256(salt+number) == challenge`. */
  private async solveChallenge(c: AltchaChallenge): Promise<string> {
    for (let number = 0; number <= c.maxnumber; number++) {
      if ((await sha256Hex(`${c.salt}${number}`)) === c.challenge) {
        const payload = {
          algorithm: c.algorithm,
          challenge: c.challenge,
          number,
          salt: c.salt,
          signature: c.signature,
        };
        // Standard-Base64 (btoa) — der Payload ist reines ASCII (Hex/Int/„SHA-256").
        return btoa(JSON.stringify(payload));
      }
    }
    throw new Error('altcha challenge unsolvable within maxnumber');
  }
}

/** Hex-SHA-256 über Web-Crypto. */
async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
