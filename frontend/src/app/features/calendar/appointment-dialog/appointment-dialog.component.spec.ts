import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Appointment } from '@core/api/calendar.service';
import { AuthService } from '@core/auth/auth.service';
import { LIVE_SEARCH_DEBOUNCE_MS, ToastService } from '@stupa-makers/ui-kit';
import { appointment } from '../../../../testing/calendar-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { errorToasts } from '../../../../testing/load-error';
import { AppointmentDialogComponent } from './appointment-dialog.component';

const GREMIEN = [
  { id: 'g-1', name: 'Haushaltsausschuss' },
  { id: 'g-2', name: 'Studierendenparlament' },
];

async function setup(opts: { appointment?: Appointment | null; publish?: boolean; gremien?: typeof GREMIEN | null } = {}) {
  const on = { closed: jest.fn(), saved: jest.fn() };
  const view = await render(AppointmentDialogComponent, {
    inputs: { open: true, appointment: opts.appointment ?? null, day: '2026-11-17' },
    on,
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: AuthService, useValue: { can: (p: string) => p === 'calendar.publish' && !!opts.publish } },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const http = injector.get(HttpTestingController);
  const committees = http.expectOne('/api/meetings/committees');
  if (opts.gremien === null) committees.flush(null, { status: 500, statusText: 'Error' });
  else committees.flush(opts.gremien ?? GREMIEN);
  view.fixture.detectChanges();
  const toasts = () => injector.get(ToastService).toasts().map((t) => t.message);
  return { ...view, on, http, toasts, cmp: view.fixture.componentInstance };
}

jest.setTimeout(20_000);

describe('AppointmentDialogComponent', () => {
  it('starts a new Termin all-day on the picked day and saves it', async () => {
    const view = await setup();
    const dialog = screen.getByRole('dialog', { name: 'Termin anlegen' });
    const create = within(dialog).getByRole('button', { name: 'Anlegen' });
    expect(create).toBeDisabled();
    expect(view.cmp.form()).toMatchObject({ allDay: true, startsOn: '2026-11-17', endsOn: '2026-11-17' });
    expect(within(dialog).queryByLabelText(/Uhrzeit Beginn/)).toBeNull();
    expect(within(dialog).queryByText('Für alle sichtbar')).toBeNull();
    await userEvent.type(within(dialog).getByLabelText(/Titel/), 'Klausurtagung');
    await userEvent.type(within(dialog).getByLabelText('Ort'), 'Tübingen');
    await userEvent.type(within(dialog).getByLabelText('Beschreibung'), 'Mit Übernachtung');
    expect(create).toBeEnabled();
    expect(await runAxe(view.container)).toHaveNoViolations();
    await userEvent.click(create);
    const req = view.http.expectOne('/api/calendar/appointments');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      title: 'Klausurtagung',
      startsOn: '2026-11-17',
      endsOn: '2026-11-17',
      startTime: null,
      endTime: null,
      place: 'Tübingen',
      description: 'Mit Übernachtung',
      forAll: false,
      public: false,
      gremiumIds: [],
      principalIds: [],
    });
    view.cmp.submit();
    const saved = appointment({ id: 'a-9' });
    req.flush(saved);
    expect(view.on.saved).toHaveBeenCalledWith(saved);
    expect(view.toasts()).toEqual(['Termin angelegt.']);
    view.http.verify();
  });

  it('shows the times of a timed Termin and keeps the end on or after the start', async () => {
    const view = await setup();
    const dialog = screen.getByRole('dialog', { name: 'Termin anlegen' });
    await userEvent.click(within(dialog).getByRole('switch', { name: 'Ganztägig' }));
    expect(within(dialog).getByLabelText(/Uhrzeit Beginn/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Uhrzeit Ende/)).toBeInTheDocument();
    view.cmp.setStart('2026-11-20');
    expect(view.cmp.form()).toMatchObject({ startsOn: '2026-11-20', endsOn: '2026-11-20' });
    view.cmp.patch({ endsOn: '2026-11-22' });
    view.cmp.setStart('2026-11-21');
    expect(view.cmp.form().endsOn).toBe('2026-11-22');
    view.cmp.patch({ title: 'X', endsOn: '2026-11-21', startTime: '10:00', endTime: '09:00' });
    expect(view.cmp.valid()).toBe(false);
    view.cmp.submit();
    view.http.expectNone('/api/calendar/appointments');
  });

  /** § 000717: the creator invites the Gremien whose meetings the creator reads. */
  it('invites Gremien from the meeting Gremien of the person', async () => {
    const view = await setup();
    expect(view.cmp.gremiumOptions().map((o) => o.label)).toEqual(['Haushaltsausschuss', 'Studierendenparlament']);
    view.cmp.addGremium('g-2');
    view.cmp.addGremium('unknown');
    view.fixture.detectChanges();
    expect(view.cmp.gremiumOptions().map((o) => o.value)).toEqual(['g-1']);
    const dialog = screen.getByRole('dialog', { name: 'Termin anlegen' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Studierendenparlament entfernen' }));
    expect(view.cmp.gremien()).toEqual([]);
    view.cmp.addGremium('g-1');
    view.cmp.addGremium('g-2');
    view.fixture.detectChanges();
    expect(view.container.querySelector('app-filter-select')).toBeNull();
  });

  it('offers no Gremium when the read of the Gremien fails', async () => {
    const view = await setup({ gremien: null });
    expect(view.cmp.gremiumOptions()).toEqual([]);
    expect(view.container.querySelector('app-filter-select')).toBeNull();
  });

  /** § 000738: the search finds accounts by name, from two characters on. */
  it('finds persons by name and invites them once', async () => {
    jest.useFakeTimers();
    try {
      const view = await setup({ appointment: appointment() });
      const dialog = screen.getByRole('dialog', { name: 'Termin bearbeiten' });
      const field = within(dialog).getByLabelText('Person einladen');
      fireEvent.input(field, { target: { value: 'j' } });
      jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
      view.http.expectNone((r) => r.url === '/api/calendar/people');
      fireEvent.input(field, { target: { value: 'le' } });
      jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
      const req = view.http.expectOne((r) => r.url === '/api/calendar/people');
      expect(req.request.params.get('q')).toBe('le');
      req.flush([
        { id: 'p-2', name: 'Jonas Weber' },
        { id: 'p-3', name: 'Lea Schmid' },
      ]);
      expect(view.cmp.personHits()).toEqual([{ id: 'p-3', name: 'Lea Schmid' }]);
      view.fixture.detectChanges();
      const hits = within(dialog).getByRole('list', { name: 'Treffer' });
      fireEvent.click(within(hits).getByRole('button', { name: /Lea Schmid/ }));
      view.fixture.detectChanges();
      expect(view.cmp.personQuery()).toBe('');
      expect(view.cmp.personHits()).toEqual([]);
      expect(view.cmp.persons().map((p) => p.name)).toEqual(['Jonas Weber', 'Lea Schmid']);
      fireEvent.click(within(dialog).getByRole('button', { name: 'Jonas Weber entfernen' }));
      expect(view.cmp.persons().map((p) => p.id)).toEqual(['p-3']);

      fireEvent.input(field, { target: { value: 'xy' } });
      jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
      view.http.expectOne((r) => r.url === '/api/calendar/people').flush(null, { status: 500, statusText: 'Error' });
      expect(view.cmp.personHits()).toEqual([]);
    } finally {
      jest.useRealTimers();
    }
  });

  it('opens an existing Termin with its data and saves the change', async () => {
    const view = await setup({ appointment: appointment() });
    const dialog = screen.getByRole('dialog', { name: 'Termin bearbeiten' });
    expect(view.cmp.form()).toMatchObject({
      title: 'Jour fixe',
      allDay: false,
      startTime: '14:00',
      endTime: '15:30',
      place: 'AStA-Büro',
      description: 'Offene Buchungen',
    });
    expect(view.cmp.gremien()).toEqual([{ id: 'g-1', name: 'Haushaltsausschuss' }]);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    const req = view.http.expectOne('/api/calendar/appointments/a-1');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toMatchObject({
      startTime: '14:00:00',
      endTime: '15:30:00',
      gremiumIds: ['g-1'],
      principalIds: ['p-2'],
    });
    req.flush(appointment());
    expect(view.toasts()).toEqual(['Termin gespeichert.']);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen' }));
    expect(view.on.closed).toHaveBeenCalled();
  });

  it('opens an all-day Termin without a place with empty fields', async () => {
    const view = await setup({
      appointment: appointment({ startTime: null, endTime: null, place: null, description: null, forAll: true }),
    });
    expect(view.cmp.form()).toMatchObject({
      allDay: true,
      startTime: '09:00',
      endTime: '10:00',
      place: '',
      description: '',
      forAll: true,
      public: false,
    });
  });

  /** § 000718: only a person with `calendar.publish` sets the switch. */
  it('shows "Für alle sichtbar" with the permission calendar.publish', async () => {
    const view = await setup({ publish: true });
    await userEvent.click(screen.getByRole('switch', { name: 'Für alle sichtbar' }));
    expect(view.cmp.form().forAll).toBe(true);
  });

  /** § 000730: the switch "Öffentlich" needs `calendar.publish` too, and an edit keeps its value. */
  it('shows "Öffentlich" with the permission calendar.publish', async () => {
    const view = await setup({ publish: true, appointment: appointment({ public: true }) });
    const toggle = screen.getByRole('switch', { name: 'Öffentlich' });
    expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    expect(view.cmp.form().public).toBe(false);
  });

  it('hides "Öffentlich" without the permission', async () => {
    await setup();
    expect(screen.queryByRole('switch', { name: 'Öffentlich' })).toBeNull();
  });

  it.each([
    ['calendar_gremium_forbidden', 'Du kannst nur Gremien einladen, deren Sitzungen du siehst.'],
    ['calendar_publish', 'Dir fehlt das Recht, einen Termin für alle sichtbar zu machen.'],
    ['other', 'Der Termin konnte nicht gespeichert werden.'],
  ])('reports the refusal %s of the server', async (code, text) => {
    const view = await setup();
    view.cmp.patch({ title: 'Klausur' });
    view.cmp.submit();
    view.http
      .expectOne('/api/calendar/appointments')
      .flush({ code }, { status: 403, statusText: 'Forbidden' });
    expect(errorToasts()).toEqual([text]);
    expect(view.cmp.saving()).toBe(false);
    expect(view.on.saved).not.toHaveBeenCalled();
  });

  it('reads nothing while it is closed', async () => {
    const view = await render(AppointmentDialogComponent, {
      inputs: { open: false },
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: AuthService, useValue: { can: () => false } }],
    });
    view.fixture.debugElement.injector.get(HttpTestingController).expectNone('/api/meetings/committees');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
