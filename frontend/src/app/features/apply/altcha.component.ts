import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';

type AltchaState = 'idle' | 'verifying' | 'solved' | 'error';

/**
 * Altcha widget. Fetches a server-signed PoW challenge
 * (`GET /altcha/challenge`), solves the proof-of-work locally (finds `number`
 * with `SHA-256(salt+number) == challenge` via Web Crypto) and emits the
 * base64 solution to the wizard. With Altcha unconfigured (404) the widget
 * signals `unavailable`, so the wizard requires no solution. Submit is only
 * possible after `solved` (or `unavailable`).
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

  /** Emits the base64 PoW solution once the challenge is solved. */
  readonly solved = output<string>();
  /** Emits when Altcha is disabled server-side (no captcha needed). */
  readonly unavailable = output<void>();

  readonly state = signal<AltchaState>('idle');

  async solve(): Promise<void> {
    if (this.state() === 'verifying' || this.state() === 'solved') return;
    this.state.set('verifying');
    try {
      const challenge = await firstValueFrom(this.api.altchaChallenge());
      if (!challenge) {
        // Altcha off (404) → no captcha required.
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

  /** Solve the proof-of-work: find `number` with `SHA-256(salt+number) == challenge`. */
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
        // Standard base64 (btoa) — the payload is pure ASCII (hex/int/"SHA-256").
        return btoa(JSON.stringify(payload));
      }
    }
    throw new Error('altcha challenge unsolvable within maxnumber');
  }
}

/** Hex SHA-256 via Web Crypto. */
async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
