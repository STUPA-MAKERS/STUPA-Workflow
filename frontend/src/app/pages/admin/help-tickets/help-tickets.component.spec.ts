import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { HttpErrorResponse } from '@angular/common/http';
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

  /** With nothing changed neither "Speichern" nor "Verwerfen" shows. */
  it('shows the stored settings, with nothing to save', async () => {
    const { api } = await setup();
    expect(api.getHelpTickets).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Hilfe & Tickets' })).toBeInTheDocument();
    expect(wikiField().value).toBe(STORED.wikiUrl);
    expect(sw('Meldungen ohne Konto erlauben')).toHaveAttribute('aria-checked', 'true');
    expect(sw('Neue Meldungen per E-Mail')).toHaveAttribute('aria-checked', 'true');
    expect(sw('Erledigte Meldungen anonymisieren')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('button', { name: /nach 12 Monaten/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Verwerfen' })).toBeNull();
  });

  it('saves the switches, the link and the months', async () => {
    const { api, toast, fixture } = await setup();
    await userEvent.click(sw('Meldungen ohne Konto erlauben'));
    await userEvent.click(sw('Neue Meldungen per E-Mail'));
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
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
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
    await userEvent.click(sw('Neue Meldungen per E-Mail'));
    await userEvent.click(discard());
    fixture.detectChanges();
    expect(sw('Neue Meldungen per E-Mail')).toHaveAttribute('aria-checked', 'true');
    expect(screen.queryByRole('button', { name: 'Verwerfen' })).toBeNull();
  });

  it('names a failed save and keeps the draft', async () => {
    const api = makeApi();
    api.putHelpTickets.mockReturnValueOnce(throwError(() => new Error('x')));
    const { toast } = await setup({ api });
    await userEvent.click(sw('Neue Meldungen per E-Mail'));
    await userEvent.click(save());
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(sw('Neue Meldungen per E-Mail')).toHaveAttribute('aria-checked', 'false');
    expect(save()).toBeEnabled();
  });

  it('saves only once while a save runs', async () => {
    const api = makeApi();
    const pending = new Subject<HelpTicketsSettings>();
    api.putHelpTickets.mockReturnValueOnce(pending);
    const { fixture } = await setup({ api });
    await userEvent.click(sw('Neue Meldungen per E-Mail'));
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

  /** The form shows in its loaded shape: the field and the switch rows with their labels. */
  it('shows the skeleton while it loads', async () => {
    const { fixture } = await setup({ api: { getHelpTickets: jest.fn(() => new Subject()), putHelpTickets: jest.fn() } });
    expect(document.querySelector('.ht__skelField')).not.toBeNull();
    expect(document.querySelectorAll('.ht__skelSwitch')).toHaveLength(3);
    expect(screen.getByRole('status')).toHaveTextContent('Wird geladen');
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
        'spam@example.orggesperrt am 14.10.2026T-00423 abgefangene Meldungen Entsperren',
        'Finn Schulzegesperrt am 10.10.20261 abgefangene Meldung Entsperren',
        'weg@example.orggesperrt am 09.10.2026 Entsperren',
      ]);
      expect(screen.getByRole('link', { name: 'T-0042' })).toHaveAttribute('href', '/tickets/t42');
    });

    /**
     * No separator is its own flex item: every child of the wrapping row is a part. The mixins of
     * the ui-kit give a wrapping row that starts one separator early, and a dot in a box of the
     * separator width before every part.
     */
    it('draws the dots in CSS, so a wrapped line never starts or ends with one', async () => {
      await setup({ perms: ['admin.site', 'ticket.manage'] });
      const meta = document.querySelector('.ht__blocks li .ht__meta');
      const parts = [...(meta?.querySelector('.ht__parts')?.children ?? [])];
      expect(parts.map((p) => p.className)).toEqual(['ht__part', 'ht__part', 'ht__part']);
      expect(parts.map((p) => p.textContent?.trim())).toEqual(['gesperrt am 14.10.2026', 'T-0042', '3 abgefangene Meldungen']);
      expect(meta?.textContent).not.toContain('·');
      const css = readFileSync(join(__dirname, 'help-tickets.component.scss'), 'utf8');
      const rule = (sel: string) => css.match(new RegExp(`\\n${sel.replace(/[.:]/g, '\\$&')} \\{([^}]*)\\}`))?.[1] ?? '';
      expect(rule('.ht__meta')).toMatch(/overflow-x: clip;/);
      expect(rule('.ht__parts')).toMatch(/@include dots\.list\(var\(--ht-sep\)\);/);
      expect(rule('.ht__part')).toMatch(/@include dots\.part\(var\(--ht-sep\)/);
      const dots = readFileSync(join(__dirname, '../../../../../vendor/ui-kit/src/styles/_dot-parts.scss'), 'utf8');
      expect(dots).toMatch(/@mixin list\(\$sep\) \{[^}]*flex-wrap: wrap;[^}]*margin-inline-start: calc\(-1 \* #\{\$sep\}\);/);
      expect(dots).toMatch(/&::before \{[^}]*width: \$sep;[^}]*content: '·' \/ '';/);
    });

    it('lists only the blocks without the site right, with no alert', async () => {
      const { api } = await setup({ perms: ['ticket.manage'] });
      expect(api.getHelpTickets).not.toHaveBeenCalled();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText(/fehlt das Recht/)).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Gesperrte Absender' })).toBeInTheDocument();
      expect(rows()).toHaveLength(3);
    });

    it('shows no alert after a 403 when the blocks are there', async () => {
      await setup({
        perms: ['admin.site', 'ticket.manage'],
        api: { getHelpTickets: jest.fn(() => throwError(() => ({ status: 403 }))), putHelpTickets: jest.fn() },
      });
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(rows()).toHaveLength(3);
    });

    it('unblocks a sender, and the focus goes to the row that takes its place', async () => {
      const { tickets, toast, fixture } = await setup({ perms: ['admin.site', 'ticket.manage'] });
      await userEvent.click(screen.getByRole('button', { name: 'spam@example.org entsperren' }));
      await fixture.whenStable();
      expect(tickets.deleteBlockedSender).toHaveBeenCalledWith('b1');
      expect(rows()).toHaveLength(2);
      expect(toast.success).toHaveBeenCalledWith('Absender entsperrt.');
      expect(screen.getByRole('button', { name: 'Finn Schulze entsperren' })).toHaveFocus();
    });

    it('gives the focus to the row before after the last unblock, then to the heading', async () => {
      const { fixture } = await setup({ perms: ['admin.site', 'ticket.manage'] });
      await userEvent.click(screen.getByRole('button', { name: 'weg@example.org entsperren' }));
      await fixture.whenStable();
      expect(screen.getByRole('button', { name: 'Finn Schulze entsperren' })).toHaveFocus();
      await userEvent.click(screen.getByRole('button', { name: 'Finn Schulze entsperren' }));
      await fixture.whenStable();
      await userEvent.click(screen.getByRole('button', { name: 'spam@example.org entsperren' }));
      await fixture.whenStable();
      expect(screen.getByRole('heading', { name: 'Gesperrte Absender' })).toHaveFocus();
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

    it('drops the row of a block that is gone already (404), as on a success', async () => {
      const tickets = makeTickets();
      tickets.deleteBlockedSender.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 404 })));
      const { toast, fixture } = await setup({ perms: ['admin.site', 'ticket.manage'], tickets });
      await userEvent.click(screen.getByRole('button', { name: 'spam@example.org entsperren' }));
      await fixture.whenStable();
      expect(rows()).toHaveLength(2);
      expect(toast.error).not.toHaveBeenCalled();
      expect(toast.success).toHaveBeenCalledWith('Absender entsperrt.');
      expect(screen.getByRole('button', { name: 'Finn Schulze entsperren' })).toHaveFocus();
    });

    it('says when nobody is blocked', async () => {
      await setup({ perms: ['admin.site', 'ticket.manage'], tickets: makeTickets(of([])) });
      expect(screen.getByText('Keine gesperrten Absender.')).toBeInTheDocument();
    });

    it('names a failed read', async () => {
      await setup({ perms: ['admin.site', 'ticket.manage'], tickets: makeTickets(throwError(() => new Error('x'))) });
      expect(screen.getByText('Die gesperrten Absender konnten nicht geladen werden.')).toBeInTheDocument();
    });

    /** An unblock before the list arrives leaves an empty list. */
    it('shows a skeleton while the blocks load', async () => {
      const { fixture } = await setup({
        perms: ['admin.site', 'ticket.manage'],
        tickets: makeTickets(new Subject<TicketBlockedSender[]>()),
      });
      expect(document.querySelectorAll('.ht__skelBlocks li')).toHaveLength(1);
      expect(document.querySelector('.ht__blocks')).toBeNull();
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
