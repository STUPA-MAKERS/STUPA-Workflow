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
  templateUrl: './altcha.component.html',
  styleUrl: './altcha.component.scss',
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
