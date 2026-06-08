import { createHash, webcrypto } from 'node:crypto';
import { render, screen, waitFor } from '@testing-library/angular';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';
import { AltchaComponent } from './altcha.component';

/** Challenge bauen, deren PoW von `number = 0` gelöst wird (Solver findet sofort). */
function challengeForZero(): AltchaChallenge {
  const salt = 'abc?expires=9999999999';
  const challenge = createHash('sha256').update(`${salt}0`).digest('hex');
  return { algorithm: 'SHA-256', challenge, salt, signature: 'sig', maxnumber: 10 };
}

function renderWith(
  altchaChallenge: () => ReturnType<ApiClient['altchaChallenge']>,
  on: { solved?: jest.Mock; unavailable?: jest.Mock } = {},
) {
  return render(AltchaComponent, {
    on,
    providers: [{ provide: ApiClient, useValue: { altchaChallenge } }],
  });
}

describe('AltchaComponent', () => {
  // jsdom hat kein Web-Crypto-`subtle` — im Browser/localhost vorhanden.
  beforeAll(() => {
    if (!globalThis.crypto?.subtle) {
      Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
    }
  });
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders the idle label in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await renderWith(() => of(challengeForZero()));
    expect(screen.getByRole('button', { name: /not a robot/i })).toBeInTheDocument();
  });

  it('fetches a challenge, solves the PoW and emits the base64 solution', async () => {
    const c = challengeForZero();
    const solved = jest.fn();
    await renderWith(() => of(c), { solved });

    screen.getByRole('button', { name: /kein Roboter/i }).click();

    const expected = btoa(
      JSON.stringify({
        algorithm: c.algorithm,
        challenge: c.challenge,
        number: 0,
        salt: c.salt,
        signature: c.signature,
      }),
    );
    await waitFor(() => expect(solved).toHaveBeenCalledWith(expected));
    expect(screen.getByText(/Bestätigt/)).toBeInTheDocument();
  });

  it('signals unavailable when altcha is disabled (404 → null)', async () => {
    const unavailable = jest.fn();
    await renderWith(() => of(null), { unavailable });
    screen.getByRole('button').click();
    await waitFor(() => expect(unavailable).toHaveBeenCalled());
  });
});
