import { createHash, webcrypto } from 'node:crypto';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';
import { AltchaService, solveChallenge } from './altcha.service';

function challengeFor(number: number, maxnumber = 10): AltchaChallenge {
  const salt = 'abc?expires=9999999999';
  const challenge = createHash('sha256').update(`${salt}${number}`).digest('hex');
  return { algorithm: 'SHA-256', challenge, salt, signature: 'sig', maxnumber };
}

describe('AltchaService', () => {
  beforeAll(() => {
    if (!globalThis.crypto?.subtle) {
      Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
    }
  });

  function setup(altchaChallenge: () => ReturnType<ApiClient['altchaChallenge']>) {
    TestBed.configureTestingModule({
      providers: [{ provide: ApiClient, useValue: { altchaChallenge } }],
    });
    return TestBed.inject(AltchaService);
  }

  it('solves a fresh challenge into the base64 payload', async () => {
    const c = challengeFor(3);
    const solution = await setup(() => of(c)).solve();
    expect(JSON.parse(atob(solution as string))).toEqual({
      algorithm: 'SHA-256',
      challenge: c.challenge,
      number: 3,
      salt: c.salt,
      signature: 'sig',
    });
  });

  it('gives null when the server has ALTCHA off', async () => {
    await expect(setup(() => of(null)).solve()).resolves.toBeNull();
  });

  it('rejects when the challenge request fails', async () => {
    await expect(setup(() => throwError(() => new Error('net'))).solve()).rejects.toThrow('net');
  });

  it('rejects a challenge without a solution up to maxnumber', async () => {
    await expect(solveChallenge(challengeFor(5, 2))).rejects.toThrow(/unsolvable/);
  });
});
