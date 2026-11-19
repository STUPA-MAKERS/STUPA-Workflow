import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import type { ForcedReport } from '@core/api/models';
import { ForcedStatusComponent, defaultFrom } from './forced-status.component';

const REPORT: ForcedReport = {
  from: '2026-08-21',
  to: '2026-11-19',
  total: 4,
  byReason: [
    { reason: 'outside_decision', count: 2 },
    { reason: 'none', count: 1 },
    { reason: 'other', count: 1 },
  ],
  byPath: [
    { fromKey: 'agenda', fromLabel: { de: 'Auf Tagesordnung' }, toKey: 'approved', toLabel: { de: 'Bewilligt' }, count: 3 },
    { fromKey: null, fromLabel: null, toKey: 'draft', toLabel: null, count: 1 },
  ],
};

const isReport = (r: { url: string }) => r.url === '/api/admin/forced-status';
const isEvents = (r: { url: string }) => r.url === '/api/admin/forced-status/events';

async function setup() {
  const view = await render(ForcedStatusComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const cmp = view.fixture.componentInstance;
  return { ...view, http, cmp };
}

describe('ForcedStatusComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('defaults to the last 90 days', () => {
    expect(defaultFrom('2026-11-19')).toBe('2026-08-21');
  });

  /** Specs 001651, 001652: the counts per reason and per path; no reason reads "Ohne Grund". */
  it('shows the counts per reason and per path', async () => {
    const { http, cmp, detectChanges } = await setup();
    const req = http.expectOne(isReport);
    expect(req.request.params.get('from')).toBe(cmp.from());
    req.flush(REPORT);
    detectChanges();
    expect(cmp.reasonRows().map((r) => [r.label, r.count])).toEqual([
      ['Beschluss außerhalb der Plattform', 2],
      ['Ohne Grund', 1],
      ['Sonstiges', 1],
    ]);
    expect(cmp.pathRows().map((r) => r.label)).toEqual(['Auf Tagesordnung → Bewilligt', 'Ohne Zustand → draft']);
    expect(screen.getByRole('heading', { name: 'Nach Grund' })).toBeInTheDocument();
  });

  it('lists the applications behind a count', async () => {
    const { http, cmp, detectChanges } = await setup();
    http.expectOne(isReport).flush(REPORT);
    detectChanges();
    cmp.openList(cmp.pathRows()[0]);
    detectChanges();
    const req = http.expectOne(isEvents);
    expect(req.request.params.get('fromKey')).toBe('agenda');
    expect(req.request.params.get('toKey')).toBe('approved');
    req.flush([
      {
        applicationId: 'app-1',
        title: null,
        at: '2026-11-12T10:15:00Z',
        reason: 'outside_decision',
        note: 'Beschluss vom 11.11.',
        fromLabel: null,
        toLabel: { de: 'Bewilligt' },
      },
    ]);
    detectChanges();
    expect(screen.getByRole('link', { name: 'Ohne Titel' })).toBeInTheDocument();
    expect(cmp.pathOf(cmp.events()[0])).toBe('Ohne Zustand → Bewilligt');
    cmp.closeList();
    expect(cmp.listRow()).toBeNull();
    cmp.openList(cmp.reasonRows()[0]);
    http.expectOne(isEvents).flush({}, { status: 500, statusText: 'x' });
    expect(cmp.eventsLoading()).toBe(false);
  });

  it('reloads for a new period and refuses a reversed one', async () => {
    const { http, cmp, detectChanges } = await setup();
    http.expectOne(isReport).flush(REPORT);
    cmp.setFrom('2026-01-01');
    http.expectOne((r) => isReport(r) && r.params.get('from') === '2026-01-01').flush({ ...REPORT, byReason: [], byPath: [] });
    detectChanges();
    expect(screen.getByText('Keine erzwungenen Status im Zeitraum')).toBeInTheDocument();
    cmp.setTo('2025-01-01');
    expect(cmp.periodError()).toBe('Der Beginn liegt nach dem Ende.');
    http.expectNone(isReport);
  });

  it('names a failed load', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(isReport).flush({}, { status: 500, statusText: 'x' });
    detectChanges();
    expect(screen.getByText('Der Bericht konnte nicht geladen werden.')).toBeInTheDocument();
  });
});
