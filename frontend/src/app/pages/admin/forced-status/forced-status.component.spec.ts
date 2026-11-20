import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import type { ForcedEvent, ForcedReport } from '@core/api/models';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';
import { ForcedStatusComponent, defaultFrom, pathValue } from './forced-status.component';

const REPORT: ForcedReport = {
  from: '2026-08-21',
  to: '2026-11-19',
  total: 4,
  byReason: [{ reason: 'outside_decision', count: 2 }],
  byPath: [
    { fromKey: 'agenda', fromLabel: { de: 'Auf Tagesordnung' }, toKey: 'approved', toLabel: { de: 'Bewilligt' }, count: 3 },
    { fromKey: null, fromLabel: null, toKey: 'draft', toLabel: null, count: 1 },
  ],
};

const EVENTS: ForcedEvent[] = [
  {
    applicationId: 'app-1',
    title: null,
    at: '2026-11-12T10:15:00Z',
    reason: 'outside_decision',
    note: 'Beschluss vom 11.11.',
    fromLabel: null,
    toLabel: { de: 'Bewilligt' },
  },
  {
    applicationId: 'app-2',
    title: 'Drucker',
    at: '2026-11-03T09:40:00Z',
    reason: 'legacy',
    note: null,
    fromLabel: { de: 'Auf Tagesordnung' },
    toLabel: { de: 'Bewilligt' },
  },
];

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
    expect(pathValue(null, 'draft')).toBe('>draft');
  });

  /** Specs 001651, 001652: one list, the rows link the application; no reason reads "Ohne Grund". */
  it('lists every forced change in one list', async () => {
    const { http, cmp, detectChanges } = await setup();
    http.expectOne(isReport).flush(REPORT);
    http.expectOne(isEvents).flush(EVENTS);
    detectChanges();
    expect(screen.getByRole('link', { name: 'Ohne Titel' })).toHaveAttribute('href', '/applications/app-1');
    expect(screen.getByRole('link', { name: 'Drucker' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(cmp.pathOf(EVENTS[0])).toBe('Ohne Zustand → Bewilligt');
    expect(cmp.reasonLabel('legacy')).toBe('Ohne Grund');
    expect(cmp.pathOptions().map((o) => o.label)).toEqual(['Auf Tagesordnung → Bewilligt', 'Ohne Zustand → draft']);
  });

  it('filters by reason and by path on the server', async () => {
    const { http, cmp } = await setup();
    http.expectOne(isReport).flush(REPORT);
    http.expectOne(isEvents).flush(EVENTS);
    cmp.setReason('outside_decision');
    const byReason = http.expectOne(isEvents);
    expect(byReason.request.params.get('reason')).toBe('outside_decision');
    byReason.flush([]);
    expect(cmp.reasonText()).toBe('Beschluss außerhalb der Plattform');
    expect(cmp.filtered()).toBe(true);
    cmp.setPath(['agenda>approved']);
    const byPath = http.expectOne(isEvents);
    expect(byPath.request.params.get('fromKey')).toBe('agenda');
    expect(byPath.request.params.get('toKey')).toBe('approved');
    byPath.flush([]);
    expect(cmp.pathText()).toBe('Auf Tagesordnung → Bewilligt');
  });

  it('reloads for a new period and shows a load error', async () => {
    const { http, cmp, detectChanges } = await setup();
    http.expectOne(isReport).flush(REPORT);
    http.expectOne(isEvents).flush(EVENTS);
    cmp.setPath('agenda>approved');
    http.expectOne(isEvents).flush(EVENTS);
    cmp.setRange({ from: '2026-10-01', to: '' });
    expect(cmp.path()).toBe('');
    const report = http.expectOne(isReport);
    expect(report.request.params.get('from')).toBe('2026-10-01');
    report.flush({}, { status: 500, statusText: 'x' });
    http.expectOne(isEvents).flush({}, { status: 500, statusText: 'x' });
    detectChanges();
    expect(cmp.failed()).toBe(true);
    expect(cmp.paths()).toEqual([]);
    expect(cmp.loadState()).toBe('error');
    expect(loadErrorToast()).toBe('Die Liste konnte nicht geladen werden.');
    retryLoadError();
    http.expectOne(isEvents).flush([]);
    expect(cmp.loadState()).toBe('ok');
  });

  it('keeps only the answer of the last load and falls back to the default period', async () => {
    const { http, cmp } = await setup();
    http.expectOne(isReport).flush(REPORT);
    http.expectOne(isEvents).flush([]);
    cmp.setReason('legacy');
    cmp.setReason('none');
    const [stale, fresh] = http.match(isEvents);
    fresh.flush(EVENTS);
    stale.flush([]);
    expect(cmp.events()).toEqual(EVENTS);
    cmp.setReason('legacy');
    cmp.setReason('');
    const [staleErr, last] = http.match(isEvents);
    last.flush([]);
    staleErr.flush({}, { status: 500, statusText: 'x' });
    expect(cmp.failed()).toBe(false);
    cmp.setRange({ from: '', to: '' });
    expect(cmp.from()).toBe(defaultFrom(cmp.to()));
    http.expectOne(isReport).flush(REPORT);
    http.expectOne(isEvents).flush([]);
    expect(cmp.titleOf(EVENTS[1])).toBe('Drucker');
    cmp.setPath('agenda>approved');
    http.expectOne(isEvents).flush([]);
    expect(cmp.filtered()).toBe(true);
    cmp.setPath([]);
    http.expectOne(isEvents).flush([]);
    cmp.setReason([]);
    http.expectOne(isEvents).flush([]);
    expect(cmp.filtered()).toBe(false);
  });
});
