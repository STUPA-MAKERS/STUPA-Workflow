import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { MeetingOutWire, Transition } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { AgendaDialogComponent } from './agenda-dialog.component';

const G = 'g1';

/** A local `YYYY-MM-DD`, `days` away from today. */
function day(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function meeting(over: Partial<MeetingOutWire>): MeetingOutWire {
  return {
    id: 'm',
    title: 'Sitzung',
    date: day(7),
    startTime: '18:00:00',
    status: 'planned',
    gremiumId: G,
    gremiumName: 'Studierendenparlament',
    agendaItemCount: 3,
    votes: [],
    createdAt: '2026-09-01T10:00:00Z',
    ...over,
  };
}

const MEETINGS: MeetingOutWire[] = [
  meeting({ id: 'm-late', title: '35. Sitzung', date: day(21), agendaItemCount: 1 }),
  meeting({ id: 'm-next', title: '34. Sitzung', date: day(7) }),
  // A planned meeting in the past: still allowed by the server, but not the suggestion.
  meeting({ id: 'm-past', title: '33. Sitzung', date: day(-3), startTime: null, agendaItemCount: undefined }),
  meeting({ id: 'm-nodate', title: 'Ohne Datum', date: null, startTime: null }),
  // A broken date shows no weekday.
  meeting({ id: 'm-broken', title: 'Kaputt', date: 'kaputt', startTime: '19:30:00' }),
  meeting({ id: 'm-live', title: 'Läuft', status: 'live', date: day(0) }),
  meeting({ id: 'm-closed', title: 'Zu', status: 'closed', date: day(-10) }),
  meeting({ id: 'm-other', title: 'Fremd', gremiumId: 'g2' }),
];

const AGENDA: Transition = {
  id: 'tr-agenda',
  fromStateId: 's1',
  toStateId: 's2',
  label: 'Auf Tagesordnung setzen',
  color: null,
  addsToAgenda: true,
  agendaGremiumId: G,
};

async function setup(transition: Transition | null = AGENDA, open = true) {
  localStorage.setItem('ap.locale', 'de');
  const done = jest.fn();
  const view = await render(AgendaDialogComponent, {
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    componentInputs: { applicationId: 'app-1', applicationTitle: 'Zuschuss Party', transition, open },
    on: { done },
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  return { ...view, http, toast, done };
}

const LIST = (r: { url: string; params: { get(k: string): string | null } }) =>
  r.url === '/api/meetings' && r.params.get('gremiumId') === G;
const FIRE = (r: { url: string }) => r.url === '/api/applications/app-1/transition';

describe('AgendaDialogComponent', () => {
  it('offers only the planned meetings of the agenda gremium, oldest first', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    const dialog = screen.getByRole('dialog', { name: /Auf Tagesordnung setzen/ });
    expect(within(dialog).getByText('Zuschuss Party')).toBeInTheDocument();
    expect(within(dialog).getByText('Studierendenparlament')).toBeInTheDocument();
    const radios = within(dialog).getAllByRole('radio');
    expect(radios.map((r) => r.closest('label')?.querySelector('.agd__title')?.textContent)).toEqual([
      '33. Sitzung',
      '34. Sitzung',
      '35. Sitzung',
      'Ohne Datum',
      'Kaputt',
    ]);
    // The first meeting from today on is the suggestion and starts chosen.
    const next = radios[1];
    expect(next).toBeChecked();
    expect(next.closest('label')?.textContent).toContain('Vorschlag');
    expect(radios[0].closest('label')?.textContent).not.toContain('Vorschlag');
    // Weekday and time, then the number of agenda items; missing parts leave no dot.
    const sub = (i: number) => radios[i].closest('label')?.querySelector('.agd__sub')?.textContent ?? '';
    expect(sub(1)).toMatch(/^\w{2}, 18:00 · 3 TOPs$/);
    expect(sub(2)).toMatch(/· 1 TOP$/);
    expect(sub(0)).toMatch(/^\w{2} · 0 TOPs$/);
    expect(sub(3)).toBe('3 TOPs');
    expect(sub(4)).toBe('19:30 · 3 TOPs');
    expect(screen.getByText('Der Antrag kommt als neuer TOP ans Ende.')).toBeInTheDocument();
    http.verify();
  });

  it('fires the transition with the chosen meeting, the NÖ flag and the note', async () => {
    const { http, detectChanges, toast, done, fixture } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    const success = jest.spyOn(toast, 'success');

    await userEvent.click(screen.getByText('35. Sitzung'));
    await userEvent.click(screen.getByRole('switch', { name: /Nicht öffentlich/ }));
    await userEvent.type(screen.getByLabelText('Notiz zum Übergang (optional)'), '  Bitte vorziehen ');
    detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Auf Tagesordnung setzen' }));

    const post = http.expectOne(FIRE);
    expect(post.request.body).toEqual({
      transitionId: 'tr-agenda',
      meetingId: 'm-late',
      nonPublic: true,
      note: 'Bitte vorziehen',
    });
    post.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });
    expect(success).toHaveBeenCalledWith('Auf die Tagesordnung von „35. Sitzung“ gesetzt.');
    expect(done).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.open()).toBe(false);
    http.verify();
  });

  it('sends no note when the field is empty, and guards a second click', async () => {
    const { http, detectChanges, fixture } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    fixture.componentInstance.submit();
    fixture.componentInstance.submit();
    const post = http.expectOne(FIRE);
    expect(post.request.body).toMatchObject({ meetingId: 'm-next', nonPublic: false, note: null });
    post.flush({});
    http.verify();
  });

  it('shows the refusal of the server and offers the meetings that are still planned', async () => {
    const { http, detectChanges, done } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Auf Tagesordnung setzen' }));
    http.expectOne(FIRE).flush(
      { status: 422, code: 'agenda_meeting_invalid', errors: [{ field: 'meetingId', msg: 'not planned' }] },
      { status: 422, statusText: 'Unprocessable' },
    );
    detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Diese Sitzung nimmt keine Anträge mehr an.');
    // The meeting started meanwhile: the new list no longer has it, the next one is chosen.
    http.expectOne(LIST).flush(MEETINGS.filter((m) => m.id !== 'm-next'));
    detectChanges();
    expect(screen.getByRole('radio', { name: /35\. Sitzung/ })).toBeChecked();
    expect(done).not.toHaveBeenCalled();
    http.verify();
  });

  it('keeps the chosen meeting when the reload still has it', async () => {
    const { http, detectChanges, fixture } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    await userEvent.click(screen.getByText('Ohne Datum'));
    fixture.componentInstance.submit();
    http.expectOne(FIRE).flush({ code: 'agenda_meeting_invalid' }, { status: 422, statusText: 'x' });
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    expect(screen.getByRole('radio', { name: /Ohne Datum/ })).toBeChecked();
    http.verify();
  });

  it('closes on a 409 and lets the caller load the application again', async () => {
    const { http, detectChanges, toast, done, fixture } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    const error = jest.spyOn(toast, 'error');
    fixture.componentInstance.submit();
    http.expectOne(FIRE).flush({ code: 'conflict' }, { status: 409, statusText: 'Conflict' });
    expect(error).toHaveBeenCalledWith(
      'Statuswechsel nicht möglich (Status hat sich geändert oder Bedingung nicht erfüllt).',
    );
    expect(done).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.open()).toBe(false);
    http.verify();
  });

  it.each([
    [403, 'Sie dürfen diesen Übergang nicht ausführen.'],
    [422, 'Statuswechsel fehlgeschlagen.'],
    [500, 'Statuswechsel fehlgeschlagen.'],
  ])('toasts a %s and stays open', async (status, message) => {
    const { http, detectChanges, toast, done, fixture } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    const error = jest.spyOn(toast, 'error');
    fixture.componentInstance.submit();
    http.expectOne(FIRE).flush({ code: 'other' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    expect(done).not.toHaveBeenCalled();
    expect(fixture.componentInstance.open()).toBe(true);
    http.verify();
  });

  it('says so when the gremium has no planned meeting, and cannot confirm', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(LIST).flush([meeting({ status: 'closed' })]);
    detectChanges();
    expect(screen.getByText(/keine geplante Sitzung/)).toBeInTheDocument();
    expect(screen.queryByText('Der Antrag kommt als neuer TOP ans Ende.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Auf Tagesordnung setzen' })).toBeDisabled();
    http.verify();
  });

  it('treats a failed load as no meetings', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(LIST).flush({}, { status: 500, statusText: 'x' });
    detectChanges();
    expect(screen.getByText(/keine geplante Sitzung/)).toBeInTheDocument();
    http.verify();
  });

  it('drops a late answer of an earlier opening', async () => {
    const { http, detectChanges, fixture } = await setup();
    const first = http.expectOne(LIST);
    fixture.componentInstance.close();
    detectChanges();
    fixture.componentInstance.open.set(true);
    detectChanges();
    const second = http.expectOne(LIST);
    // The first answer arrives late.
    first.flush([meeting({ id: 'stale', title: 'Alt' })]);
    detectChanges();
    expect(screen.queryByText('Alt')).not.toBeInTheDocument();
    second.flush(MEETINGS);
    detectChanges();
    expect(screen.getByText('34. Sitzung')).toBeInTheDocument();
    http.verify();
  });

  it('drops a late error of an earlier opening', async () => {
    const { http, detectChanges, fixture } = await setup();
    const first = http.expectOne(LIST);
    fixture.componentInstance.close();
    detectChanges();
    fixture.componentInstance.open.set(true);
    detectChanges();
    const second = http.expectOne(LIST);
    second.flush(MEETINGS);
    first.flush({}, { status: 500, statusText: 'x' });
    detectChanges();
    expect(screen.getByText('34. Sitzung')).toBeInTheDocument();
    http.verify();
  });

  it('loads nothing without a transition and does not fire', async () => {
    const { http, fixture } = await setup(null);
    fixture.componentInstance.submit();
    http.verify();
  });

  it('loads nothing without an agenda gremium; the button names the dialog', async () => {
    const { http } = await setup({ ...AGENDA, agendaGremiumId: null, label: '' });
    http.verify();
    // Without its own label the button says what the dialog does.
    expect(screen.getByRole('button', { name: 'Auf Tagesordnung setzen' })).toBeDisabled();
  });

  it('loads nothing while closed', async () => {
    const { http } = await setup(AGENDA, false);
    http.verify();
  });

  it('has no a11y violations', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(LIST).flush(MEETINGS);
    detectChanges();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
