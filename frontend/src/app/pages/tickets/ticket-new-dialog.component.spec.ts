import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { CalendarApiService } from '@core/api/calendar.service';
import { TicketsApiService, type TicketArea, type TicketDetail } from '@core/api/tickets.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastMock } from '../../../testing/toast';
import { TicketNewDialogComponent, manualBody } from './ticket-new-dialog.component';

const PLAT: TicketArea = {
  id: 'a-plat',
  name: 'Plattform',
  gremiumId: null,
  platform: true,
  notifyNew: true,
  inApp: true,
  categories: [],
  mine: true,
};
const ASTA: TicketArea = {
  id: 'a-asta',
  name: 'AStA-Büro',
  gremiumId: 'g1',
  platform: false,
  notifyNew: true,
  inApp: false,
  categories: [{ id: 'c1', name: 'Raumanfrage' }],
  mine: true,
};

async function setup(opts: { areas?: readonly TicketArea[]; preset?: string } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = { createManual: jest.fn(() => of({ id: 't99' } as TicketDetail)) };
  const people = jest.fn(() => of([{ id: 'p7', name: 'Lea Hoffmann' }]));
  const toast = toastMock();
  const created = jest.fn();
  const closed = jest.fn();
  const view = await render(TicketNewDialogComponent, {
    inputs: { open: true, areas: opts.areas ?? [PLAT, ASTA], preset: opts.preset ?? '' },
    on: { created, closed },
    providers: [
      { provide: TicketsApiService, useValue: api },
      { provide: CalendarApiService, useValue: { people } },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const fill = async (value: Record<string, unknown>) => {
    cmp.onValue({ ...cmp.value(), ...value });
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  return { ...view, cmp, api, people, toast, created, closed, fill };
}

/** "Ticket anlegen": a ticket that the team writes by hand (spec 002712). */
describe('TicketNewDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('builds the body of Plattform with a kind and of another Bereich with its Kategorie', () => {
    const value = { title: ' Anruf ', body: ' intern ', message: ' Hallo ', category: 'bug' };
    expect(manualBody(value, PLAT, 'p7')).toEqual({
      areaId: 'a-plat',
      title: 'Anruf',
      body: 'intern',
      message: 'Hallo',
      reporterId: 'p7',
      kind: 'bug',
    });
    expect(manualBody({ ...value, category: 'bogus' }, PLAT, 'p7').kind).toBe('question');
    expect(manualBody({ ...value, category: 'c1' }, ASTA, 'p7')).toMatchObject({ areaId: 'a-asta', categoryId: 'c1' });
    const bare = manualBody({ title: 'x' }, ASTA, 'p7');
    expect(bare).toEqual({ areaId: 'a-asta', title: 'x', body: '', message: '', reporterId: 'p7' });
  });

  it('starts on the Bereich of the list filter and clears the Kategorie with a new Bereich', async () => {
    const { cmp, fill } = await setup({ preset: 'a-asta' });
    expect(screen.getByRole('heading', { name: 'Ticket anlegen' })).toBeInTheDocument();
    expect(cmp.area().id).toBe('a-asta');
    await fill({ category: 'c1' });
    await fill({ areaId: 'a-plat' });
    expect(cmp.value().category).toBe('question');
    await fill({ areaId: 'a-asta' });
    expect(cmp.value().category).toBe('');
  });

  it('shows no Bereich field with one Bereich, and no Kategorie field without a Kategorie', async () => {
    const { cmp } = await setup({ areas: [{ ...ASTA, categories: [] }] });
    const keys = cmp.form().sections[0].fields.map((f: { key: string }) => f.key);
    expect(keys).toEqual(['email', 'title', 'body', 'message']);
  });

  it('asks for a person, searches the accounts and creates the ticket', async () => {
    const { cmp, api, people, created, fill, fixture } = await setup();
    await fill({ title: 'Anruf wegen Raum' });
    cmp.save();
    fixture.detectChanges();
    expect(api.createManual).not.toHaveBeenCalled();
    expect(screen.getByText('Bitte eine Person wählen oder eine E-Mail-Adresse eintragen.')).toBeInTheDocument();
    cmp.findPeople('Lea').subscribe();
    expect(people).toHaveBeenCalledWith('Lea');
    cmp.onPicked({ kind: 'gremium', id: 'g1', name: 'AStA', logoUrl: null });
    expect(cmp.person()).toBeNull();
    cmp.onPicked({ kind: 'person', id: 'p7', name: 'Lea Hoffmann' });
    fixture.detectChanges();
    expect(cmp.taken()).toEqual(['p7']);
    expect(screen.getByText('Lea Hoffmann')).toBeInTheDocument();
    cmp.onAction('save');
    expect(api.createManual).toHaveBeenCalledWith(
      expect.objectContaining({ areaId: 'a-plat', title: 'Anruf wegen Raum', reporterId: 'p7', kind: 'question' }),
    );
    expect(created).toHaveBeenCalledWith({ id: 't99' });
  });

  it('creates a ticket for an e-mail address without an account', async () => {
    const { cmp, api, toast, fill } = await setup();
    await fill({ title: 'Anruf wegen Raum', email: 'keine adresse' });
    cmp.save();
    expect(api.createManual).not.toHaveBeenCalled();
    await fill({ email: ' dora@example.org ' });
    api.createManual.mockReturnValueOnce(throwError(() => ({ error: { code: 'mailbox_off' } })));
    cmp.save();
    expect(api.createManual).toHaveBeenLastCalledWith(
      expect.objectContaining({ title: 'Anruf wegen Raum', email: 'dora@example.org' }),
    );
    expect(api.createManual).not.toHaveBeenCalledWith(expect.objectContaining({ reporterId: expect.anything() }));
    expect(toast.error).toHaveBeenLastCalledWith(
      'Das Postfach dieses Bereichs ist ausgeschaltet. Öffentliche Nachrichten sind gerade nicht möglich.',
    );
  });

  it('saves nothing without a title, and closes on Abbrechen', async () => {
    const { cmp, api, closed } = await setup();
    cmp.onPicked({ kind: 'person', id: 'p7', name: 'Lea Hoffmann' });
    cmp.save();
    expect(api.createManual).not.toHaveBeenCalled();
    cmp.onAction('cancel');
    expect(closed).toHaveBeenCalled();
  });

  it('names a refusal of the server', async () => {
    const { cmp, api, toast, fill } = await setup();
    await fill({ title: 'Anruf' });
    cmp.onPicked({ kind: 'person', id: 'p7', name: 'Lea Hoffmann' });
    api.createManual.mockReturnValueOnce(throwError(() => ({ error: { code: 'ticket_reporter_invalid' } })));
    cmp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Für diese Person kann kein Ticket angelegt werden.');
    api.createManual.mockReturnValueOnce(throwError(() => ({ error: null })));
    cmp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Das Ticket konnte nicht angelegt werden.');
    expect(cmp.saving()).toBe(false);
  });
});
