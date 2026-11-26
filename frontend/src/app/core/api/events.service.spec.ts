import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { USE_MOCK_API } from './api.config';
import { EventsApiService } from './events.service';

describe('EventsApiService', () => {
  let svc: EventsApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    svc = TestBed.inject(EventsApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  /** §F/collaboration/events/003027 and 003028: the list with its segment and filter. */
  it('reads the list, one Event, the teams, the picker and the series', () => {
    svc.page({ segment: 'past', team: 't-1', q: undefined }).subscribe();
    const page = http.expectOne((r) => r.url === '/api/events');
    expect(page.request.params.get('segment')).toBe('past');
    expect(page.request.params.get('team')).toBe('t-1');
    expect(page.request.params.has('q')).toBe(false);
    page.flush({ items: [], total: 0 });
    svc.page().subscribe();
    http.expectOne((r) => r.url === '/api/events').flush({ items: [], total: 0 });
    svc.get('e-1').subscribe();
    http.expectOne('/api/events/e-1').flush({});
    svc.teams().subscribe();
    http.expectOne('/api/events/teams').flush([]);
    svc.refs().subscribe();
    expect(http.expectOne((r) => r.url === '/api/events/refs').request.params.keys()).toEqual([]);
    svc.refs('Ball').subscribe();
    http.expectOne((r) => r.url === '/api/events/refs' && r.params.get('q') === 'Ball').flush([]);
    svc.series().subscribe();
    expect(http.expectOne((r) => r.url === '/api/events/series').request.params.keys()).toEqual([]);
    svc.series('Fest').subscribe();
    http.expectOne((r) => r.url === '/api/events/series' && r.params.get('q') === 'Fest').flush([]);
  });

  it('writes an Event, a status and a series, and deletes an Event', () => {
    svc.createSeries('Neu').subscribe();
    expect(http.expectOne('/api/events/series').request.body).toEqual({ name: 'Neu' });
    svc.create({ teamId: 't-1', title: 'Fest' }).subscribe();
    const created = http.expectOne('/api/events');
    expect(created.request.method).toBe('POST');
    expect(created.request.body).toEqual({ teamId: 't-1', title: 'Fest' });
    svc.update('e-1', 3, { place: 'Hof' }).subscribe();
    const changed = http.expectOne('/api/events/e-1');
    expect(changed.request.method).toBe('PATCH');
    expect(changed.request.body).toEqual({ place: 'Hof', version: 3 });
    svc.setStatus('e-1', 'settled', 4).subscribe();
    expect(http.expectOne('/api/events/e-1/status').request.body).toEqual({ status: 'settled', version: 4 });
    svc.remove('e-1').subscribe();
    expect(http.expectOne('/api/events/e-1').request.method).toBe('DELETE');
  });

  /** §F/collaboration/events/003034: the export takes the filter and no paging. */
  it('exports the list as a file without the paging', () => {
    svc.exportXlsx({ segment: 'done', limit: 50, offset: 100 }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/events/export.xlsx');
    expect(req.request.responseType).toBe('blob');
    expect(req.request.params.get('segment')).toBe('done');
    expect(req.request.params.has('limit')).toBe(false);
    expect(req.request.params.has('offset')).toBe(false);
    svc.exportXlsx().subscribe();
    http.expectOne((r) => r.url === '/api/events/export.xlsx').flush(new Blob());
    req.flush(new Blob());
  });
});
