import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import {
  type AppointmentInput,
  CalendarApiService,
  type ExternalCalendarInput,
  ExternalCalendarsApiService,
  PublicCalendarApiService,
} from './calendar.service';

const BODY: AppointmentInput = {
  title: 'Klausur',
  startsOn: '2026-11-17',
  endsOn: '2026-11-19',
  startTime: null,
  endTime: null,
  place: null,
  description: null,
  forAll: false,
  public: false,
  gremiumIds: ['g-1'],
  principalIds: [],
};

describe('CalendarApiService', () => {
  let api: CalendarApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(CalendarApiService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('reads the entries of a range, with "mine" only when it is set', () => {
    const got: unknown[] = [];
    api.entries('2026-11-01', '2026-11-30', false).subscribe((items) => got.push(items));
    const all = http.expectOne((r) => r.url === '/api/calendar/entries');
    expect(all.request.params.get('from')).toBe('2026-11-01');
    expect(all.request.params.get('to')).toBe('2026-11-30');
    expect(all.request.params.has('mine')).toBe(false);
    all.flush({ items: [{ id: 'a' }] });
    expect(got).toEqual([[{ id: 'a' }]]);
    api.entries('2026-11-01', '2026-11-30', true).subscribe();
    const mine = http.expectOne((r) => r.url === '/api/calendar/entries');
    expect(mine.request.params.get('mine')).toBe('true');
    mine.flush({ items: [] });
  });

  it('searches the entries and the people', () => {
    const got: unknown[] = [];
    api.search('klausur').subscribe((items) => got.push(items));
    const search = http.expectOne((r) => r.url === '/api/calendar/search');
    expect(search.request.params.get('q')).toBe('klausur');
    search.flush({ items: [{ id: 'a' }] });
    api.people('da').subscribe((items) => got.push(items));
    const people = http.expectOne((r) => r.url === '/api/calendar/people');
    expect(people.request.params.get('q')).toBe('da');
    people.flush([{ id: 'p', name: 'Dana' }]);
    expect(got).toEqual([[{ id: 'a' }], [{ id: 'p', name: 'Dana' }]]);
  });

  it('reads, creates, changes, answers and deletes a Termin', () => {
    api.appointment('a-1').subscribe();
    expect(http.expectOne('/api/calendar/appointments/a-1').request.method).toBe('GET');
    api.create(BODY).subscribe();
    const create = http.expectOne('/api/calendar/appointments');
    expect(create.request.method).toBe('POST');
    expect(create.request.body).toEqual(BODY);
    api.update('a-1', BODY).subscribe();
    const update = http.expectOne('/api/calendar/appointments/a-1');
    expect(update.request.method).toBe('PUT');
    expect(update.request.body).toEqual(BODY);
    api.answer('a-1', 'tentative').subscribe();
    const answer = http.expectOne('/api/calendar/appointments/a-1/answer');
    expect(answer.request.method).toBe('PUT');
    expect(answer.request.body).toEqual({ answer: 'tentative' });
    api.remove('a-1').subscribe();
    expect(http.expectOne('/api/calendar/appointments/a-1').request.method).toBe('DELETE');
  });

  it('reads an entry of an external calendar', () => {
    api.externalEntry('x-1').subscribe();
    expect(http.expectOne('/api/calendar/external/x-1').request.method).toBe('GET');
  });

  /** § 000729: the routes of the admin page. */
  it('lists, creates, changes, fetches and deletes an external calendar', () => {
    const admin = TestBed.inject(ExternalCalendarsApiService);
    const body: ExternalCalendarInput = {
      name: 'Hochschule',
      url: 'https://example.org/a.ics',
      gremiumId: null,
      intervalMinutes: 60,
    };
    admin.list().subscribe();
    expect(http.expectOne('/api/admin/calendars').request.method).toBe('GET');
    admin.create(body).subscribe();
    const create = http.expectOne('/api/admin/calendars');
    expect([create.request.method, create.request.body]).toEqual(['POST', body]);
    admin.update('c-1', body).subscribe();
    const update = http.expectOne('/api/admin/calendars/c-1');
    expect([update.request.method, update.request.body]).toEqual(['PUT', body]);
    admin.fetchNow('c-1').subscribe();
    expect(http.expectOne('/api/admin/calendars/c-1/fetch').request.method).toBe('POST');
    admin.remove('c-1').subscribe();
    expect(http.expectOne('/api/admin/calendars/c-1').request.method).toBe('DELETE');
  });
});

describe('PublicCalendarApiService', () => {
  let api: PublicCalendarApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(PublicCalendarApiService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('reads the entries, the hits and the Gremien of the public calendar', () => {
    const got: unknown[] = [];
    api.entries('2026-11-01', '2026-11-30').subscribe((items) => got.push(items));
    const entries = http.expectOne((r) => r.url === '/api/public/calendar/entries');
    expect(entries.request.params.get('from')).toBe('2026-11-01');
    expect(entries.request.params.get('to')).toBe('2026-11-30');
    entries.flush({ items: [{ id: 'a' }] });
    api.search('Voll').subscribe((items) => got.push(items));
    const search = http.expectOne((r) => r.url === '/api/public/calendar/search');
    expect(search.request.params.get('q')).toBe('Voll');
    search.flush({ items: [{ id: 'b' }] });
    api.gremien().subscribe((list) => got.push(list));
    http.expectOne('/api/public/calendar/committees').flush([{ id: 'g-1', name: 'StuPa' }]);
    expect(got).toEqual([[{ id: 'a' }], [{ id: 'b' }], [{ id: 'g-1', name: 'StuPa' }]]);
  });

  it('reads one Termin and one meeting and knows the address of the feed', () => {
    api.appointment('a-7').subscribe();
    expect(http.expectOne('/api/public/calendar/appointments/a-7').request.method).toBe('GET');
    api.meeting('m-35').subscribe();
    expect(http.expectOne('/api/public/calendar/meetings/m-35').request.method).toBe('GET');
    expect(api.feedUrl()).toBe('http://localhost/api/public/calendar.ics');
  });
});
