import { of, throwError } from 'rxjs';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import {
  type ExternalCalendar,
  type ExternalCalendarInput,
  ExternalCalendarsApiService,
} from '@core/api/calendar.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { loadErrorToast, retryLoadError, toastWith } from '../../../../testing/load-error';
import { AdminOptionsService } from '../admin-options.service';
import { AdminCalendarsComponent, fetchState } from './calendars.component';

function calendar(id: string, over: Partial<ExternalCalendar> = {}): ExternalCalendar {
  return {
    id,
    name: `Kalender ${id}`,
    url: `https://example.org/${id}.ics`,
    gremiumId: null,
    gremiumName: null,
    intervalMinutes: 60,
    lastAttemptAt: '2026-11-11T18:00:00Z',
    lastSuccessAt: '2026-11-11T18:00:00Z',
    lastError: null,
    entryCount: 42,
    ...over,
  };
}

const UNI = calendar('uni', { name: 'Hochschulkalender', intervalMinutes: 1440 });
const SENAT = calendar('senat', { name: 'Senatstermine', gremiumId: 'g-1', gremiumName: 'Studierendenparlament' });
const RAUM = calendar('raum', {
  name: 'Raumbelegung',
  intervalMinutes: 15,
  lastSuccessAt: '2026-11-09T13:00:00Z',
  lastError: 'timeout',
  entryCount: 17,
});
const NEW = calendar('neu', { name: 'Neu', lastAttemptAt: null, lastSuccessAt: null, entryCount: 0 });

interface Opts {
  listError?: boolean;
  writeError?: boolean;
  gremienError?: boolean;
}

async function setup(seed: readonly ExternalCalendar[] = [UNI, SENAT, RAUM], opts: Opts = {}) {
  const fail = () => throwError(() => new Error('boom'));
  const list = jest
    .fn()
    .mockImplementationOnce(() => (opts.listError ? fail() : of(seed)))
    .mockImplementation(() => of(seed));
  const api = {
    list,
    create: jest.fn((body: ExternalCalendarInput) =>
      opts.writeError ? fail() : of(calendar('made', { ...body, lastAttemptAt: null, lastSuccessAt: null })),
    ),
    update: jest.fn((id: string, body: ExternalCalendarInput) =>
      opts.writeError ? fail() : of(calendar(id, { ...body, gremiumName: body.gremiumId ? 'AStA' : null })),
    ),
    remove: jest.fn(() => (opts.writeError ? fail() : of(void 0))),
    fetchNow: jest.fn((id: string) => (opts.writeError ? fail() : of(calendar(id, { name: 'Raumbelegung' })))),
  };
  const options = {
    gremiumOptions: jest.fn(() =>
      opts.gremienError
        ? fail()
        : of([
            { value: 'g-1', label: 'Studierendenparlament' },
            { value: 'g-2', label: 'AStA' },
          ]),
    ),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminCalendarsComponent, {
    providers: [
      { provide: ExternalCalendarsApiService, useValue: api },
      { provide: AdminOptionsService, useValue: options },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

const rows = () => within(screen.getByRole('list', { name: 'Externe Kalender' })).getAllByRole('listitem');

async function menu(name: string, action: string): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: `Weitere Aktionen: ${name}` }));
  await userEvent.click(await screen.findByRole('menuitem', { name: action }));
}

describe('AdminCalendarsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** § 000729: one row per calendar with the name, the state, the scope and the address. */
  it('lists the calendars with the state of the newest fetch', async () => {
    const view = await setup();
    const [uni, senat, raum] = rows();
    expect(uni.textContent).toContain('Hochschulkalender');
    expect(uni.textContent).toContain('Abgerufen');
    expect(uni.textContent).toContain('Alle · Täglich · https://example.org/uni.ics');
    expect(senat.textContent).toContain('Studierendenparlament · Stündlich');
    expect(raum.textContent).toContain('Abruf fehlgeschlagen');
    expect(raum.textContent).toContain('Alle 15 Minuten');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('names the three states of a fetch', () => {
    expect(fetchState(UNI)).toEqual({ kind: 'accent', key: 'admin.calendars.state.ok' });
    expect(fetchState(RAUM)).toEqual({ kind: 'error', key: 'admin.calendars.state.failed' });
    expect(fetchState(NEW)).toEqual({ kind: 'muted', key: 'admin.calendars.state.pending' });
  });

  /** § 000729: the body shows the times, the number of entries and the reason. */
  it('opens the fetch details of a row', async () => {
    const view = await setup([RAUM, NEW]);
    await userEvent.click(screen.getByRole('button', { name: 'Abruf: Raumbelegung' }));
    const body = rows()[0];
    expect(body.textContent).toContain('Letzter Versuch');
    expect(body.textContent).toContain('17');
    expect(body.textContent).toContain('Die Adresse antwortet nicht (Zeitüberschreitung).');
    expect(view.c.reasonLabel('newer_code')).toBe('newer_code');
    expect(view.c.reasonLabel(null)).toBe('—');
    await userEvent.click(screen.getByRole('button', { name: 'Abruf: Neu' }));
    expect(view.c.openId()).toBe('neu');
    expect(rows()[1].textContent).toContain('Noch nicht abgerufen');
    await userEvent.click(screen.getByRole('button', { name: 'Abruf: Neu' }));
    expect(view.c.openId()).toBeNull();
  });

  it('shows an empty state without calendars', async () => {
    await setup([]);
    expect(screen.getByText('Keine externen Kalender')).toBeInTheDocument();
  });

  it('shows a failed read as an error with a retry', async () => {
    const view = await setup([UNI], { listError: true });
    expect(loadErrorToast()).toBe('Kalender nicht geladen');
    await retryLoadError();
    view.fixture.detectChanges();
    expect(rows().length).toBe(1);
  });

  /** § 000729: the dialog refuses an address that does not start with https://. */
  it('subscribes a calendar for all and refuses an address without https', async () => {
    const view = await setup([UNI]);
    await userEvent.click(screen.getByRole('button', { name: 'Kalender abonnieren' }));
    const dialog = await screen.findByRole('dialog', { name: 'Kalender abonnieren' });
    const save = within(dialog).getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Senat');
    await userEvent.type(within(dialog).getByLabelText('ICS-Adresse'), 'http://example.org/a.ics');
    expect(within(dialog).getByText('Die Adresse muss mit https:// beginnen.')).toBeInTheDocument();
    expect(save).toBeDisabled();
    view.c.save();
    expect(view.api.create).not.toHaveBeenCalled();
    view.c.patch('url', ' https://example.org/a.ics ');
    view.fixture.detectChanges();
    expect(within(dialog).queryByLabelText('Gremium')).toBeNull();
    await userEvent.click(save);
    expect(view.api.create).toHaveBeenCalledWith({
      name: 'Senat',
      url: 'https://example.org/a.ics',
      gremiumId: null,
      intervalMinutes: 60,
    });
    expect(view.toast.success).toHaveBeenCalledWith('Gespeichert.');
    expect(rows().length).toBe(2);
    expect(view.c.draft()).toBeNull();
  });

  /** § 000729: "Ein Gremium" asks for the Gremium, and the interval is one of four. */
  it('edits a calendar on a press on its row and saves a Gremium and an interval', async () => {
    const view = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Hochschulkalender' }));
    const dialog = await screen.findByRole('dialog', { name: 'Kalender bearbeiten' });
    await waitFor(() => expect(within(dialog).getByLabelText('Name')).toHaveValue('Hochschulkalender'));
    expect(view.c.intervalOptions().map((o: { label: string }) => o.label)).toEqual([
      'Alle 15 Minuten',
      'Stündlich',
      'Alle 6 Stunden',
      'Täglich',
    ]);
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Ein Gremium' }));
    expect(within(dialog).getByRole('button', { name: 'Speichern' })).toBeDisabled();
    view.c.patch('gremiumId', 'g-2');
    view.c.patch('interval', '360');
    view.fixture.detectChanges();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    expect(view.api.update).toHaveBeenCalledWith('uni', {
      name: 'Hochschulkalender',
      url: 'https://example.org/uni.ics',
      gremiumId: 'g-2',
      intervalMinutes: 360,
    });
    expect(rows()[0].textContent).toContain('AStA · Alle 6 Stunden');
    expect(rows().length).toBe(3);
  });

  it('keeps the dialog open when the save fails, and closes it on cancel', async () => {
    const view = await setup([SENAT], { writeError: true, gremienError: true });
    expect(view.c.gremien()).toEqual([]);
    await menu('Senatstermine', 'Bearbeiten');
    const dialog = await screen.findByRole('dialog', { name: 'Kalender bearbeiten' });
    expect(view.c.draft().scope).toBe('gremium');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    expect(view.toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(view.c.draft()).not.toBeNull();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen' }));
    expect(view.c.draft()).toBeNull();
    view.c.patch('name', 'x');
    view.c.save();
    expect(view.c.draft()).toBeNull();
  });

  /** § 000729: "Jetzt abrufen" only asks the worker; the page says so. */
  it('asks for a fetch from the menu', async () => {
    const view = await setup([RAUM]);
    await menu('Raumbelegung', 'Jetzt abrufen');
    expect(view.api.fetchNow).toHaveBeenCalledWith('raum');
    expect(view.toast.success).toHaveBeenCalledWith('Der Abruf startet in der nächsten Minute.');
    expect(rows()[0].textContent).toContain('Abgerufen');
  });

  /** § 000729: "Löschen" asks first and removes the calendar. */
  it('deletes a calendar after a confirmation', async () => {
    const view = await setup([UNI, RAUM]);
    view.c.doDelete();
    expect(view.api.remove).not.toHaveBeenCalled();
    await menu('Raumbelegung', 'Entfernen');
    const confirm = await screen.findByRole('dialog', { name: /Kalender löschen/ });
    expect(confirm.textContent).toContain('„Raumbelegung“ und seine Einträge werden entfernt.');
    await userEvent.click(within(confirm).getByRole('button', { name: 'Abbrechen' }));
    expect(view.c.confirmDelete()).toBeNull();
    view.c.onMenu('delete', RAUM);
    view.c.doDelete();
    expect(view.api.remove).toHaveBeenCalledWith('raum');
    expect(view.toast.success).toHaveBeenCalledWith('Kalender gelöscht');
    expect(view.c.calendars().map((c: ExternalCalendar) => c.id)).toEqual(['uni']);
  });

  it('reports a failed fetch request and a failed delete', async () => {
    const view = await setup([RAUM], { writeError: true });
    view.c.onMenu('fetch', RAUM);
    expect(view.toast.error).toHaveBeenCalledWith('Der Abruf ließ sich nicht starten.');
    view.c.onMenu('delete', RAUM);
    view.c.doDelete();
    expect(view.toast.error).toHaveBeenCalledWith('Löschen fehlgeschlagen.');
    expect(view.c.calendars().length).toBe(1);
  });
});
