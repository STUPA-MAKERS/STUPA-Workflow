import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { HelpTicketsSettings } from '../admin.models';
import { HelpTicketsComponent, isHttpUrl } from './help-tickets.component';

const STORED: HelpTicketsSettings = {
  wikiUrl: 'https://wiki.example.org/books/stupa',
  publicEnabled: true,
  notifyNew: true,
  retentionMonths: 12,
};

function makeApi(initial: HelpTicketsSettings = STORED) {
  return {
    getHelpTickets: jest.fn(() => of({ ...initial })),
    putHelpTickets: jest.fn((b: HelpTicketsSettings) => of({ ...b })),
  };
}

async function setup(opts: { api?: Record<string, jest.Mock>; perms?: string[] } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.site']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(HelpTicketsComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useValue: toast },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

const wikiField = () => screen.getByLabelText(/Adresse des Handbuchs/) as HTMLInputElement;
const save = () => screen.getByRole('button', { name: 'Speichern' });
const discard = () => screen.getByRole('button', { name: 'Verwerfen' });
const sw = (name: string) => screen.getByRole('switch', { name });

describe('isHttpUrl', () => {
  it.each([
    ['https://wiki.example.org/x', true],
    ['http://wiki.example.org', true],
    [' https://wiki.example.org ', true],
    ['ftp://wiki.example.org', false],
    ['javascript:alert(1)', false],
    ['wiki.example.org', false],
    ['', false],
  ])('%s → %s', (text, ok) => {
    expect(isHttpUrl(text)).toBe(ok);
  });
});

describe('HelpTicketsComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows the stored settings, with nothing to save', async () => {
    const { api } = await setup();
    expect(api.getHelpTickets).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Hilfe & Tickets' })).toBeInTheDocument();
    expect(wikiField().value).toBe(STORED.wikiUrl);
    expect(sw('Meldungen ohne Konto erlauben')).toHaveAttribute('aria-checked', 'true');
    expect(sw('Neue Meldungen per Mail')).toHaveAttribute('aria-checked', 'true');
    expect(sw('Erledigte Meldungen anonymisieren')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('button', { name: /nach 12 Monaten/ })).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(discard()).toBeDisabled();
  });

  it('saves the switches, the link and the months', async () => {
    const { api, toast, fixture } = await setup();
    await userEvent.click(sw('Meldungen ohne Konto erlauben'));
    await userEvent.click(sw('Neue Meldungen per Mail'));
    await userEvent.clear(wikiField());
    await userEvent.type(wikiField(), '  https://wiki.example.org/neu  ');
    const c = fixture.componentInstance as unknown as { setMonths(v: string): void };
    c.setMonths('24');
    fixture.detectChanges();
    await userEvent.click(save());
    expect(api.putHelpTickets).toHaveBeenCalledWith({
      wikiUrl: 'https://wiki.example.org/neu',
      publicEnabled: false,
      notifyNew: false,
      retentionMonths: 24,
    });
    expect(toast.success).toHaveBeenCalledWith('Gespeichert.');
    fixture.detectChanges();
    expect(save()).toBeDisabled();
  });

  it('turns the anonymization off and on again with the last months', async () => {
    const { api, fixture } = await setup();
    const c = fixture.componentInstance as unknown as { setMonths(v: string): void };
    c.setMonths('6');
    fixture.detectChanges();
    await userEvent.click(sw('Erledigte Meldungen anonymisieren'));
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: /nach 6 Monaten/ })).not.toBeInTheDocument();
    await userEvent.click(save());
    expect(api.putHelpTickets).toHaveBeenLastCalledWith(expect.objectContaining({ retentionMonths: null }));
    fixture.detectChanges();
    await userEvent.click(sw('Erledigte Meldungen anonymisieren'));
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: /nach 6 Monaten/ })).toBeInTheDocument();
  });

  it('turns the anonymization on with 12 months when it was never set', async () => {
    const { fixture } = await setup({ api: makeApi({ ...STORED, retentionMonths: null }) });
    expect(sw('Erledigte Meldungen anonymisieren')).toHaveAttribute('aria-checked', 'false');
    const c = fixture.componentInstance as unknown as { monthOptions(): unknown[] };
    expect(c.monthOptions()).toHaveLength(8);
    await userEvent.click(sw('Erledigte Meldungen anonymisieren'));
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: /nach 12 Monaten/ })).toBeInTheDocument();
  });

  it('names one month in the singular', async () => {
    const { fixture } = await setup({ api: makeApi({ ...STORED, retentionMonths: 1 }) });
    const c = fixture.componentInstance as unknown as { monthOptions(): { value: string; label: string }[] };
    expect(c.monthOptions()[0]).toEqual({ value: '1', label: 'nach 1 Monat' });
  });

  it('offers the stored months even when they are not a usual choice', async () => {
    const { fixture } = await setup({ api: makeApi({ ...STORED, retentionMonths: 18 }) });
    const c = fixture.componentInstance as unknown as { monthOptions(): { value: string }[] };
    expect(c.monthOptions().map((o) => o.value)).toEqual(['1', '3', '6', '12', '18', '24', '36', '60', '120']);
  });

  it('refuses a link that is not http(s)', async () => {
    const { api } = await setup();
    await userEvent.clear(wikiField());
    await userEvent.type(wikiField(), 'ftp://wiki');
    expect(screen.getByText('Bitte eine Adresse mit http:// oder https:// eingeben.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(discard()).toBeEnabled();
    expect(api.putHelpTickets).not.toHaveBeenCalled();
  });

  it('puts the stored values back on Verwerfen', async () => {
    const { fixture } = await setup();
    await userEvent.click(sw('Neue Meldungen per Mail'));
    await userEvent.click(discard());
    fixture.detectChanges();
    expect(sw('Neue Meldungen per Mail')).toHaveAttribute('aria-checked', 'true');
    expect(discard()).toBeDisabled();
  });

  it('names a failed save and keeps the draft', async () => {
    const api = makeApi();
    api.putHelpTickets.mockReturnValueOnce(throwError(() => new Error('x')));
    const { toast } = await setup({ api });
    await userEvent.click(sw('Neue Meldungen per Mail'));
    await userEvent.click(save());
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(sw('Neue Meldungen per Mail')).toHaveAttribute('aria-checked', 'false');
    expect(save()).toBeEnabled();
  });

  it('saves only once while a save runs', async () => {
    const api = makeApi();
    const pending = new Subject<HelpTicketsSettings>();
    api.putHelpTickets.mockReturnValueOnce(pending);
    const { fixture } = await setup({ api });
    await userEvent.click(sw('Neue Meldungen per Mail'));
    const c = fixture.componentInstance as unknown as { save(): void; discard(): void };
    c.save();
    c.save();
    expect(api.putHelpTickets).toHaveBeenCalledTimes(1);
  });

  it('shows no form without the right to manage the site', async () => {
    const { api } = await setup({ perms: [] });
    expect(api.getHelpTickets).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Für diese Einstellungen fehlt das Recht');
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  });

  it('shows no form after a 403', async () => {
    await setup({ api: { getHelpTickets: jest.fn(() => throwError(() => ({ status: 403 }))), putHelpTickets: jest.fn() } });
    expect(screen.getByRole('alert')).toHaveTextContent('Für diese Einstellungen fehlt das Recht');
  });

  it('names a failed read', async () => {
    await setup({ api: { getHelpTickets: jest.fn(() => throwError(() => null)), putHelpTickets: jest.fn() } });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Einstellungen konnten nicht geladen werden.');
  });

  it('shows the skeleton while it loads', async () => {
    const { fixture } = await setup({ api: { getHelpTickets: jest.fn(() => new Subject()), putHelpTickets: jest.fn() } });
    expect(document.querySelector('app-skeleton')).not.toBeNull();
    const c = fixture.componentInstance as unknown as { dirty(): boolean; discard(): void };
    expect(c.dirty()).toBe(false);
    c.discard();
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  });
});
