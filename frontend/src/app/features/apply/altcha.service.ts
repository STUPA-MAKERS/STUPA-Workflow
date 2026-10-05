import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';

/**
 * ALTCHA proof of work.
 *
 * `solve` gets a server-signed challenge from `GET /altcha/challenge` and solves it
 * locally with Web Crypto: it finds the `number` where `SHA-256(salt+number) ==
 * challenge`. A solution is good for one request only (the server keeps a replay
 * guard), so every request that needs one calls `solve` again.
 *
 * The widget (`app-altcha`) uses it for the submit; the draft uploads of the wizard
 * use it without a widget for the first anonymous upload (Z4).
 */
@Injectable({ providedIn: 'root' })
export class AltchaService {
  private readonly api = inject(ApiClient);

  /**
   * The base64 solution of a fresh challenge, or `null` when the server has ALTCHA off
   * (the challenge route answers 404). Rejects when the request fails or the challenge
   * has no solution up to `maxnumber`.
   */
  async solve(): Promise<string | null> {
    const challenge = await firstValueFrom(this.api.altchaChallenge());
    if (!challenge) return null;
    return solveChallenge(challenge);
  }
}

/** Solve the proof of work: find `number` with `SHA-256(salt+number) == challenge`. */
export async function solveChallenge(c: AltchaChallenge): Promise<string> {
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

/** Hex SHA-256 via Web Crypto. */
async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
