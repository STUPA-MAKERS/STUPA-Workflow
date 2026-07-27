import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';

type AltchaState = 'idle' | 'verifying' | 'solved' | 'error';

/**
 * Altcha widget.
 *
 * The widget gets a server-signed proof-of-work challenge from
 * `GET /altcha/challenge`. It solves the proof of work locally with Web Crypto: it
 * finds the `number` where `SHA-256(salt+number) == challenge`. It then emits the
 * base64 solution to the wizard. If Altcha has no configuration, the endpoint answers
 * 404 and the widget emits `unavailable`. The wizard then needs no solution. The
 * wizard allows submit only after `solved` or `unavailable`.
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

  /** Emits the base64 proof-of-work solution after the widget solves the challenge. */
  readonly solved = output<string>();
  /** Emits when the server has Altcha off. The form then needs no captcha. */
  readonly unavailable = output<void>();

  readonly state = signal<AltchaState>('idle');

  async solve(): Promise<void> {
    if (this.state() === 'verifying' || this.state() === 'solved') return;
    this.state.set('verifying');
    try {
      const challenge = await firstValueFrom(this.api.altchaChallenge());
      if (!challenge) {
        // A null challenge means the server answered 404: Altcha is off, no captcha.
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

  /** Solve the proof of work: find `number` with `SHA-256(salt+number) == challenge`. */
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
        // Standard base64 (btoa) is safe here: the payload holds only ASCII.
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
