import { createHash, webcrypto } from 'node:crypto';
import { render, screen, waitFor } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AltchaChallenge } from '@core/api/models';
import { AltchaComponent } from './altcha.component';

/** Build a challenge that `number = 0` solves, so the solver finds it at once. */
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
  // jsdom has no Web Crypto `subtle`. The browser and localhost have it.
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
    // `findByText` polls until the verified state re-renders. The DOM update follows the
    // `solved` emit one change-detection cycle later, so a direct check is flaky under load.
    expect(await screen.findByText(/Bestätigt/)).toBeInTheDocument();
  });

  it('signals unavailable when altcha is disabled (404 → null)', async () => {
    const unavailable = jest.fn();
    await renderWith(() => of(null), { unavailable });
    screen.getByRole('button').click();
    await waitFor(() => expect(unavailable).toHaveBeenCalled());
  });

  it('enters the error state when the challenge request fails', async () => {
    const solved = jest.fn();
    const unavailable = jest.fn();
    const { fixture } = await renderWith(() => throwError(() => new Error('network')), {
      solved,
      unavailable,
    });
    // Call solve() directly so the test awaits the rejected firstValueFrom. The
    // try/catch of the component then handles the error deterministically.
    await fixture.componentInstance.solve();
    fixture.detectChanges();
    expect(fixture.componentInstance.state()).toBe('error');
    expect(screen.getByText(/fehlgeschlagen/i)).toBeInTheDocument();
    expect(solved).not.toHaveBeenCalled();
    expect(unavailable).not.toHaveBeenCalled();
  });

  it('enters the error state when the PoW is unsolvable within maxnumber', async () => {
    // No number in [0..maxnumber] matches the challenge hash, so solveChallenge throws.
    const unsolvable: AltchaChallenge = {
      algorithm: 'SHA-256',
      challenge: 'deadbeef'.repeat(8), // 64 hex chars, the loop never makes this value
      salt: 'salty',
      signature: 'sig',
      maxnumber: 3,
    };
    const solved = jest.fn();
    const { fixture } = await renderWith(() => of(unsolvable), { solved });
    await fixture.componentInstance.solve();
    expect(fixture.componentInstance.state()).toBe('error');
    expect(solved).not.toHaveBeenCalled();
  });

  it('is a no-op while already verifying or solved', async () => {
    const solved = jest.fn();
    const { fixture } = await renderWith(() => of(challengeForZero()), { solved });
    const comp = fixture.componentInstance;

    await comp.solve();
    expect(comp.state()).toBe('solved');
    expect(solved).toHaveBeenCalledTimes(1);

    await comp.solve();
    expect(solved).toHaveBeenCalledTimes(1);

    comp.state.set('verifying');
    await comp.solve();
    expect(solved).toHaveBeenCalledTimes(1);
    expect(comp.state()).toBe('verifying');
  });
});
