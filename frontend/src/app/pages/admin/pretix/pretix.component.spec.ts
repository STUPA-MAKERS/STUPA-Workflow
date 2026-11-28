import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideRouter } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';
import { MOCK_PRETIX, MOCK_PRETIX_FAILED } from '@core/api/mock-sales';
import { type PretixConnection, type PretixConnectionIn, SalesApiService } from '@core/api/sales.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastWith } from '../../../../testing/load-error';
import { PretixComponent } from './pretix.component';

function makeApi(stored: PretixConnection = MOCK_PRETIX) {
  return {
    getPretix: jest.fn(() => of({ ...stored })),
    putPretix: jest.fn((b: PretixConnectionIn) => of({ ...stored, ...b, tokenSet: stored.tokenSet || !!b.token })),
    testPretix: jest.fn(() => of({ ok: true, error: null as string | null, name: 'stupa' as string | null })),
    pretixFailed: jest.fn(() => of({ items: MOCK_PRETIX_FAILED })),
  };
}

interface Page {
  act(key: string): void;
  set(key: string, value: boolean): void;
  save(): void;
  discard(): void;
  patch(change: Record<string, unknown>): void;
  groups(): { key: string; rows: { key: string; disabled?: boolean; value?: unknown }[] }[];
  urlError(): string;
  tokenError(): string;
  screenState(): { state: string };
  notice(): unknown;
}

async function setup(opts: { api?: ReturnType<typeof makeApi>; perms?: string[] } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.pretix']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(PretixComponent, {
    providers: [
      provideRouter([]),
      { provide: SalesApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast, page: view.fixture.componentInstance as unknown as Page };
}

describe('PretixComponent', () => {
  it('shows the connection, the switches and the failed bookings with their cause', async () => {
    const { page } = await setup();
    expect(screen.getByText('Verkaufszahlen zeigen')).toBeTruthy();
    expect(screen.getByText('Einnahmen buchen')).toBeTruthy();
    expect(screen.getByText('ABC12')).toBeTruthy();
    expect(screen.getByText(/Das Haushaltsjahr ist abgeschlossen\./)).toBeTruthy();
    expect((screen.getByLabelText(/Neuer API-Token/) as HTMLInputElement).value).toBe('');
    expect(page.groups().find((g) => g.key === 'actions')?.rows[0].disabled).toBe(false);
  });

  it('saves the switches and a new token, and never shows the stored one', async () => {
    const { page, api } = await setup();
    page.set('showSales', false);
    page.set('unknown', true);
    await userEvent.type(screen.getByLabelText(/Neuer API-Token/), 'secret');
    page.patch({ organizer: ' stupa ' });
    page.save();
    expect(api.putPretix).toHaveBeenCalledWith({
      baseUrl: 'https://pretix.eu',
      organizer: 'stupa',
      token: 'secret',
      showSales: false,
      bookIncome: true,
    });
  });

  it('needs a web address and the token again for a new address', async () => {
    const { page, api } = await setup();
    page.patch({ baseUrl: 'pretix' });
    expect(page.urlError()).toBe('Gib eine Adresse mit http:// oder https:// ein.');
    page.patch({ baseUrl: 'https://other.example/' });
    expect(page.tokenError()).toBe('Gib für eine neue Adresse den Token erneut ein.');
    page.save();
    expect(api.putPretix).not.toHaveBeenCalled();
    page.patch({ baseUrl: 'https://pretix.eu/', token: '' });
    expect(page.tokenError()).toBe('');
  });

  it('names the allowed hosts when the server refuses the host, and forgets it on discard', async () => {
    const api = makeApi();
    api.putPretix.mockReturnValueOnce(throwError(() => ({ error: { code: 'pretix_host_not_allowed' } })));
    const { page } = await setup({ api });
    page.patch({ baseUrl: 'https://evil.example', token: 't' });
    page.save();
    expect(page.urlError()).toBe('Dieser Host ist nicht freigegeben. Freigegeben: pretix.eu');
    page.discard();
    page.patch({ baseUrl: 'https://evil.example', token: 't' });
    expect(page.urlError()).toBe('');
  });

  it('keeps the address error away for another refusal and with an empty allowlist', async () => {
    const api = makeApi({ ...MOCK_PRETIX, allowedHosts: [] });
    api.putPretix
      .mockReturnValueOnce(throwError(() => null))
      .mockReturnValueOnce(throwError(() => ({ error: { code: 'pretix_host_not_allowed' } })));
    const { page } = await setup({ api });
    page.patch({ baseUrl: 'https://a.example', token: 't' });
    page.save();
    expect(page.urlError()).toBe('');
    page.save();
    expect(page.urlError()).toBe('Dieser Host ist nicht freigegeben. Freigegeben: –');
  });

  it('tests the connection and shows the result', async () => {
    const api = makeApi();
    const { page, toast } = await setup({ api });
    page.act('test');
    expect(toast.success).toHaveBeenCalledWith('Die Verbindung zu Pretix steht: stupa');
    api.testPretix.mockReturnValueOnce(of({ ok: false, error: 'unauthorized', name: null }));
    page.act('test');
    expect(toast.error).toHaveBeenCalledWith('Der Dienst lehnt den Token ab.');
    api.testPretix.mockReturnValueOnce(throwError(() => new Error('x')));
    page.act('test');
    expect(toast.error).toHaveBeenLastCalledWith('Unbekannter Fehler.');
    page.act('other');
    expect(api.testPretix).toHaveBeenCalledTimes(3);
  });

  it('keeps the test off while the connection is incomplete or changed', async () => {
    const { page } = await setup({ api: makeApi({ ...MOCK_PRETIX, organizer: null, tokenSet: false }) });
    expect(page.groups().find((g) => g.key === 'actions')?.rows[0].disabled).toBe(true);
    expect(screen.getByLabelText(/^API-Token/)).toBeTruthy();
  });

  it('says when the failed bookings cannot be read, and hides their group while none failed', async () => {
    const api = makeApi();
    api.pretixFailed.mockReturnValueOnce(throwError(() => new Error('x')));
    const { page } = await setup({ api });
    expect(page.notice()).toEqual({ kind: 'error', text: 'Die fehlgeschlagenen Buchungen konnten nicht geladen werden.' });
    expect(page.groups().some((g) => g.key === 'failed')).toBe(false);
  });

  it('shows the missing right and a load error with a retry', async () => {
    const forbidden = await setup({ perms: [] });
    expect(forbidden.page.screenState()).toEqual({ state: 'forbidden', message: 'Dir fehlt das Recht „Pretix verwalten“.' });
    expect(forbidden.api.pretixFailed).not.toHaveBeenCalled();
  });

  it('shows a load error with a retry', async () => {
    const api = makeApi();
    api.getPretix.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    const { page } = await setup({ api });
    const state = page.screenState() as { state: string; retry?: () => void };
    expect(state.state).toBe('error');
    state.retry?.();
    expect(api.getPretix).toHaveBeenCalledTimes(2);
  });

  it('starts empty, saves an address without a token and sends empty fields as none', async () => {
    const api = makeApi({ ...MOCK_PRETIX, baseUrl: null, organizer: null, tokenSet: false });
    const { page } = await setup({ api });
    page.patch({ baseUrl: 'https://pretix.eu' });
    expect(page.tokenError()).toBe('');
    page.save();
    expect(api.putPretix).toHaveBeenCalledWith({
      baseUrl: 'https://pretix.eu',
      organizer: null,
      showSales: true,
      bookIncome: true,
    });
  });

  it('shows the skeleton while it reads', async () => {
    const api = makeApi();
    api.getPretix.mockReturnValueOnce(NEVER);
    const { page } = await setup({ api });
    expect(page.screenState()).toEqual({ state: 'loading' });
  });
});
