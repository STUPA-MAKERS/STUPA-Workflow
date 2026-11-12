import { HttpErrorResponse } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { StopObservingComponent, endToken } from './stop-observing.component';

async function setup(hash: string, endObservation: jest.Mock) {
  window.history.replaceState(null, '', `/stop-observing${hash}`);
  const view = await render(StopObservingComponent, {
    providers: [provideRouter([]), { provide: ApiClient, useValue: { endObservation } }],
  });
  return { ...view, cmp: view.fixture.componentInstance };
}

describe('StopObservingComponent', () => {
  afterEach(() => window.history.replaceState(null, '', '/'));

  it('reads the token of the fragment', () => {
    expect(endToken('#t=abc.def')).toBe('abc.def');
    expect(endToken('t=abc')).toBe('abc');
    expect(endToken('#x=1')).toBe('');
  });

  it('asks first and ends the observation on the button', async () => {
    const end = jest.fn(() => of(undefined));
    const { cmp } = await setup('#t=o1.sig', end);
    expect(end).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Beobachtung beenden' }));
    expect(end).toHaveBeenCalledWith('o1.sig');
    expect(await screen.findByRole('heading', { name: 'Beobachtung beendet' })).toBeInTheDocument();
    cmp.end();
    expect(end).toHaveBeenCalledTimes(1);
  });

  it('names a dead link', async () => {
    const dead = jest.fn(() => throwError(() => new HttpErrorResponse({ status: 404 })));
    await setup('#t=o1.sig', dead);
    await userEvent.click(screen.getByRole('button', { name: 'Beobachtung beenden' }));
    expect(await screen.findByRole('heading', { name: 'Link ungültig' })).toBeInTheDocument();
  });

  it('keeps the ask after another failure', async () => {
    const down = jest.fn(() => throwError(() => new HttpErrorResponse({ status: 503 })));
    const { cmp } = await setup('#t=o1.sig', down);
    cmp.end();
    expect(cmp.phase()).toBe('ask');
  });

  it('shows the dead link without a token', async () => {
    const end = jest.fn();
    await setup('', end);
    expect(screen.getByRole('heading', { name: 'Link ungültig' })).toBeInTheDocument();
  });
});
