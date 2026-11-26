import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { API_BASE_URL } from './api.config';
import { DEFAULT_STATUS_LISTS, StatusCatalog, provideTestStatuses } from './statuses.service';

describe('StatusCatalog', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => TestBed.resetTestingModule());

  /** § 003035: the first read loads the list once; until then a key shows as itself. */
  it('reads a list once and names, colors and phases its statuses', async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: API_BASE_URL, useValue: '/api' }],
    });
    const catalog = TestBed.inject(StatusCatalog);
    const http = TestBed.inject(HttpTestingController);
    expect(catalog.label('order', 'ordered')).toBe('ordered');
    expect(catalog.tone('order', 'ordered')).toBe('neutral');
    expect(catalog.phase('order', 'ordered')).toBeNull();
    await Promise.resolve();
    http.expectOne('/api/statuses/order').flush({ kind: 'order', statuses: DEFAULT_STATUS_LISTS.order });
    catalog.list('order');
    await Promise.resolve();
    http.expectNone('/api/statuses/order');
    expect(catalog.label('order', 'ordered')).toBe('Bestellt');
    expect(catalog.tone('order', 'ordered')).toBe('warn');
    expect(catalog.phase('order', 'cancelled')).toBe('void');
    expect(catalog.label('order', null)).toBe('');
    http.verify();
  });

  it('keeps the keys when the read fails', async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: API_BASE_URL, useValue: '/api' }],
    });
    const catalog = TestBed.inject(StatusCatalog);
    const http = TestBed.inject(HttpTestingController);
    catalog.list('event');
    await Promise.resolve();
    http.expectOne('/api/statuses/event').flush(null, { status: 500, statusText: 'Error' });
    expect(catalog.label('event', 'planned')).toBe('planned');
    http.verify();
  });

  it('holds the seeded lists without a read', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideTestStatuses()],
    });
    const catalog = TestBed.inject(StatusCatalog);
    expect(catalog.label('event', 'settled')).toBe('Abgerechnet');
    catalog.set('event', [{ key: 'x', name: { en: 'X' }, tone: 'accent', phase: 'open', start: true }]);
    expect(catalog.label('event', 'x')).toBe('x');
    TestBed.inject(HttpTestingController).verify();
  });
});
