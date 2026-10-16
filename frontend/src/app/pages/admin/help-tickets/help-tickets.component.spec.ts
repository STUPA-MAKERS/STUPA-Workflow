import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideRouter } from '@angular/router';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TicketsApiService, type TicketBlockedSender } from '@core/api/tickets.service';
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

const BLOCKS: TicketBlockedSender[] = [
  {
    id: 'b1',
    kind: 'email',
    person: null,
    email: 'spam@example.org',
    blockedBy: { principalId: 'p1', displayName: 'Mara Keller' },
    blockedAt: '2026-10-14T08:00:00Z',
    sourceTicket: { id: 't42', number: 'T-0042' },
    hitCount: 3,
    lastHitAt: '2026-10-15T08:00:00Z',
  },
  {
    id: 'b2',
    kind: 'principal',
    person: { principalId: 'p7', displayName: 'Finn Schulze' },
    email: 'finn@example.org',
    blockedBy: null,
    blockedAt: '2026-10-10T08:00:00Z',
    sourceTicket: null,
    hitCount: 1,
    lastHitAt: null,
  },
  {
    id: 'b3',
    kind: 'principal',
    person: { principalId: 'p8', displayName: null },
    email: 'weg@example.org',
    blockedBy: null,
    blockedAt: '2026-10-09T08:00:00Z',
    sourceTicket: null,
    hitCount: 0,
    lastHitAt: null,
  },
];

function makeTickets(list: Observable<TicketBlockedSender[]> = of(BLOCKS)) {
  return {
    blockedSenders: jest.fn(() => list),
    deleteBlockedSender: jest.fn((): Observable<void> => of(undefined)),
  };
}

async function setup(
  opts: { api?: Record<string, jest.Mock>; perms?: string[]; tickets?: ReturnType<typeof makeTickets> } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const api = opts.api ?? makeApi();
  const tickets = opts.tickets ?? makeTickets();
  const perms = new Set(opts.perms ?? ['admin.site']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(HelpTicketsComponent, {
    providers: [
      provideRouter([]),
      { provide: TicketsApiService, useValue: tickets },
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useValue: toast },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, tickets, toast };
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

  describe('blocked senders', () => {
    const rows = () =>
      [...document.querySelectorAll('.ht__blocks li')].map((li) => li.textContent?.replace(/\s+/g, ' ').trim());

    it('shows nothing of the blocks without ticket.manage', async () => {
      const { tickets } = await setup();
      expect(tickets.blockedSenders).not.toHaveBeenCalled();
      expect(screen.queryByRole('heading', { name: 'Gesperrte Absender' })).not.toBeInTheDocument();
    });

    it('lists the blocks with the date, the source ticket and the held-back reports', async () => {
      await setup({ perms: ['admin.site', 'ticket.manage'] });
      expect(screen.getByRole('heading', { name: 'Gesperrte Absender' })).toBeInTheDocument();
      expect(rows()).toEqual([
        'spam@example.orggesperrt am 14.10.2026·T-0042·3 abgefangene Meldungen Entsperren',
        'Finn Schulzegesperrt am 10.10.2026·1 abgefangene Meldung Entsperren',
        'weg@example.orggesperrt am 09.10.2026 Entsperren',
      ]);
      expect(screen.getByRole('link', { name: 'T-0042' })).toHaveAttribute('href', '/tickets/t42');
    });

    it('lists the blocks without the site right too', async () => {
      await setup({ perms: ['ticket.manage'] });
      expect(screen.getByText('Für diese Einstellungen fehlt das Recht, die Seite zu verwalten.')).toBeInTheDocument();
      expect(rows()).toHaveLength(3);
    });

    it('unblocks a sender', async () => {
      const { tickets, toast } = await setup({ perms: ['admin.site', 'ticket.manage'] });
      await userEvent.click(screen.getAllByRole('button', { name: 'Entsperren' })[0]);
      expect(tickets.deleteBlockedSender).toHaveBeenCalledWith('b1');
      expect(rows()).toHaveLength(2);
      expect(toast.success).toHaveBeenCalledWith('Absender entsperrt.');
    });

    it('names a failed unblock and keeps the row, one unblock at a time', async () => {
      const tickets = makeTickets();
      const pending = new Subject<void>();
      tickets.deleteBlockedSender.mockReturnValueOnce(pending).mockReturnValueOnce(throwError(() => new Error('x')));
      const { toast, fixture } = await setup({ perms: ['admin.site', 'ticket.manage'], tickets });
      const cmp = fixture.componentInstance as unknown as { unblock(b: TicketBlockedSender): void };
      cmp.unblock(BLOCKS[0]);
      cmp.unblock(BLOCKS[1]);
      expect(tickets.deleteBlockedSender).toHaveBeenCalledTimes(1);
      pending.next();
      pending.complete();
      cmp.unblock(BLOCKS[1]);
      fixture.detectChanges();
      expect(toast.error).toHaveBeenCalledWith('Die Sperre konnte nicht aufgehoben werden.');
      expect(rows()).toHaveLength(2);
    });

    it('says when nobody is blocked', async () => {
      await setup({ perms: ['admin.site', 'ticket.manage'], tickets: makeTickets(of([])) });
      expect(screen.getByText('Keine gesperrten Absender.')).toBeInTheDocument();
    });

    it('names a failed read', async () => {
      await setup({ perms: ['admin.site', 'ticket.manage'], tickets: makeTickets(throwError(() => new Error('x'))) });
      expect(screen.getByText('Die gesperrten Absender konnten nicht geladen werden.')).toBeInTheDocument();
    });

    it('shows a skeleton while the blocks load', async () => {
      const { fixture } = await setup({
        perms: ['admin.site', 'ticket.manage'],
        tickets: makeTickets(new Subject<TicketBlockedSender[]>()),
      });
      expect(document.querySelectorAll('app-skeleton').length).toBeGreaterThan(0);
      expect(document.querySelector('.ht__blocks')).toBeNull();
      // An unblock before the list arrived leaves an empty list.
      (fixture.componentInstance as unknown as { unblock(b: TicketBlockedSender): void }).unblock(BLOCKS[0]);
      fixture.detectChanges();
      expect(screen.getByText('Keine gesperrten Absender.')).toBeInTheDocument();
    });

    it('names a principal block by its address when the person has no name, and a bare block by nothing', async () => {
      const { fixture } = await setup({ perms: ['ticket.manage'], tickets: makeTickets(of([])) });
      const cmp = fixture.componentInstance as unknown as { senderName(b: TicketBlockedSender): string };
      expect(cmp.senderName({ ...BLOCKS[1], person: { principalId: 'p', displayName: null }, email: null })).toBe(
        'Gelöschte Person',
      );
      expect(cmp.senderName({ ...BLOCKS[1], person: null, email: null })).toBe('');
    });
  });
});
