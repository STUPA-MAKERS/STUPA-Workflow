import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { isoDay } from '@shared/date-format';
import { USE_MOCK_API } from './api.config';
import type { Appointment, AppointmentInput, CalendarEntry, CalendarPerson } from './calendar.service';
import { mockApiInterceptor } from './mock-api.interceptor';
import { mockCalendar, resetMockCalendar } from './mock-calendar';

const params = (values: Record<string, string>) => ({ get: (name: string) => values[name] ?? null });
const NONE = params({});
const TODAY = isoDay(new Date());

const BODY: AppointmentInput = {
  title: 'Neu',
  startsOn: TODAY,
  endsOn: TODAY,
  startTime: null,
  endTime: null,
  place: null,
  description: null,
  forAll: false,
  gremiumIds: ['g0000000-0000-0000-0000-000000000001'],
  principalIds: ['p0000000-0000-0000-0000-000000000002'],
};

describe('mockCalendar (demo data)', () => {
  beforeEach(() => resetMockCalendar());

  const entries = (values: Record<string, string>) =>
    (mockCalendar('GET', '/api/calendar/entries', params(values), null)!.body as { items: CalendarEntry[] }).items;

  it('serves the entries of a range and limits them with "mine"', () => {
    const today = entries({ from: TODAY, to: TODAY });
    expect(today.map((e) => e.title)).toEqual(['Angebot Technik einholen', 'Jour fixe Finanzreferat', 'Kurzer Abgleich']);
    expect(entries({})).toEqual([]);
    const all = entries({ from: '2000-01-01', to: '2999-01-01' });
    const mine = entries({ from: '2000-01-01', to: '2999-01-01', mine: 'true' });
    expect(new Set(all.map((e) => e.kind))).toEqual(new Set(['meeting', 'card', 'event', 'appointment']));
    expect(mine.length).toBeLessThan(all.length);
    expect(mine.every((e) => e.kind === 'meeting' || e.mine)).toBe(true);
  });

  it('searches the titles and the people from two characters on', () => {
    const search = (q?: string) =>
      (mockCalendar('GET', '/api/calendar/search', q === undefined ? NONE : params({ q }), null)!.body as {
        items: CalendarEntry[];
      }).items;
    expect(search('s')).toEqual([]);
    expect(search()).toEqual([]);
    expect(search('SITZUNG').map((e) => e.kind)).toEqual(['meeting', 'meeting']);
    const people = (q?: string) =>
      mockCalendar('GET', '/api/calendar/people', q === undefined ? NONE : params({ q }), null)!.body as CalendarPerson[];
    expect(people('j')).toEqual([]);
    expect(people()).toEqual([]);
    expect(people('jo').map((p) => p.name)).toEqual(['Jonas Weber']);
  });

  it('creates, reads, changes, answers and deletes a Termin', () => {
    const made = mockCalendar('POST', '/api/calendar/appointments', NONE, BODY)!;
    expect(made.status).toBe(201);
    const a = made.body as Appointment;
    expect(a).toMatchObject({ title: 'Neu', canEdit: true, invited: false, myAnswer: null });
    expect(a.gremien.map((g) => g.name)).toEqual(['Studierendenparlament']);
    expect(a.persons.map((p) => p.name)).toEqual(['Jonas Weber']);
    const path = `/api/calendar/appointments/${a.id}`;
    expect(mockCalendar('GET', path, NONE, null)!.body).toEqual(a);
    expect(entries({ from: TODAY, to: TODAY }).some((e) => e.id === a.id && e.mine)).toBe(true);

    const answered = mockCalendar('PUT', `${path}/answer`, NONE, { answer: 'accept' })!.body as Appointment;
    expect(answered.myAnswer).toBe('accept');
    expect(answered.answers).toEqual([{ principalId: 'p0000000-0000-0000-0000-000000000001', name: 'Dana Meier', answer: 'accept' }]);
    const again = mockCalendar('PUT', `${path}/answer`, NONE, { answer: 'decline' })!.body as Appointment;
    expect(again.answers.map((row) => row.answer)).toEqual(['decline']);

    const renamed = mockCalendar('PUT', path, NONE, { ...BODY, title: 'Anders' })!.body as Appointment;
    expect(renamed).toMatchObject({ title: 'Anders', myAnswer: 'decline' });
    const moved = mockCalendar('PUT', path, NONE, { ...BODY, startTime: '09:00:00', endTime: '10:00:00' })!
      .body as Appointment;
    expect(moved).toMatchObject({ myAnswer: null, answers: [] });

    expect(mockCalendar('DELETE', path, NONE, null)).toEqual({ status: 204, body: null });
    expect(mockCalendar('GET', path, NONE, null)).toBeNull();
  });

  it('keeps the creator and the invitation of a Termin of another person', () => {
    const path = '/api/calendar/appointments/a0000000-0000-0000-0000-000000000001';
    const before = mockCalendar('GET', path, NONE, null)!.body as Appointment;
    const after = mockCalendar('PUT', path, NONE, { ...BODY, startsOn: before.startsOn, endsOn: before.endsOn, startTime: before.startTime, endTime: before.endTime })!
      .body as Appointment;
    expect(after.creator).toEqual(before.creator);
    expect(after.invited).toBe(true);
    expect(after.answers).toEqual(before.answers);
  });

  it('does not know other paths and methods', () => {
    const path = '/api/calendar/appointments/a0000000-0000-0000-0000-000000000001';
    expect(mockCalendar('GET', '/api/calendar/other', NONE, null)).toBeNull();
    expect(mockCalendar('GET', '/api/other', NONE, null)).toBeNull();
    expect(mockCalendar('PATCH', path, NONE, null)).toBeNull();
    expect(mockCalendar('GET', `${path}/answer`, NONE, null)).toBeNull();
    expect(mockCalendar('DELETE', '/api/calendar/entries', NONE, null)).toBeNull();
  });
});

/**
 * `isDevMode` is a non-configurable named export of @angular/core, so the test mocks the
 * module and keeps every other export.
 */
jest.mock('@angular/core', () => {
  const actual = jest.requireActual('@angular/core');
  return { ...actual, isDevMode: (): boolean => true };
});

describe('mockApiInterceptor (Kalender)', () => {
  beforeEach(() => {
    resetMockCalendar();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
  });

  it('answers the Kalender routes from the demo data, and 404 for an unknown Termin', async () => {
    const http = TestBed.inject(HttpClient);
    const page = await firstValueFrom(
      http.get<{ items: CalendarEntry[] }>('/api/calendar/entries', { params: { from: TODAY, to: TODAY } }),
    );
    expect(page.items.length).toBe(3);
    await expect(firstValueFrom(http.get('/api/calendar/appointments/none'))).rejects.toMatchObject({ status: 404 });
  });
});
