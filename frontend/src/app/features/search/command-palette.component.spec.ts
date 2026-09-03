import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { SearchResults } from '@core/api/models';
import { CommandPaletteComponent } from './command-palette.component';
import { PageIndexService } from './page-index.service';

const PAGES = [
  { path: '/admin/roles', label: 'Rollen', parentLabel: 'Verwaltung' },
  { path: '/invoices', label: 'Rechnungen', parentLabel: null },
];

const HITS: SearchResults = {
  hits: [
    {
      kind: 'application',
      id: 'a-1',
      title: 'Anschaffung Beamer',
      subtitle: 'Entwurf',
      url: '/applications/a-1',
    },
  ],
  truncated: false,
  failed: [],
};

async function setup(pages = PAGES) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(CommandPaletteComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: PageIndexService, useValue: { visible: () => pages } },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const router = TestBed.inject(Router);
  const cmp = view.fixture.componentInstance;
  return { ...view, http, router, cmp };
}

/** Let the 180ms debounce elapse and answer the request it produced. */
async function answer(http: HttpTestingController, body: SearchResults = HITS) {
  jest.advanceTimersByTime(200);
  const req = http.expectOne((r) => r.url.endsWith('/api/search'));
  req.flush(body);
  return req;
}

describe('CommandPaletteComponent', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('is closed until it is opened', async () => {
    const { cmp, container } = await setup();
    expect(cmp.open()).toBe(false);
    expect(container.querySelector('.pal')).toBeNull();
  });

  it('opens on Ctrl+K and closes on Escape', async () => {
    const { cmp, fixture } = await setup();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
    fixture.detectChanges();
    expect(cmp.open()).toBe(true);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(cmp.open()).toBe(false);
  });

  it('opens on Cmd+K too, for a Mac', async () => {
    const { cmp, fixture } = await setup();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'K', metaKey: true }));
    fixture.detectChanges();
    expect(cmp.open()).toBe(true);
  });

  it('asks the server nothing for a query below the floor', async () => {
    // The palette runs on every keystroke, and the first one is not a mistake.
    const { cmp, http } = await setup();
    cmp.show();
    cmp.onQuery('a');
    jest.advanceTimersByTime(500);
    http.expectNone((r) => r.url.endsWith('/api/search'));
    expect(cmp.loading()).toBe(false);
  });

  it('matches pages without a round trip', async () => {
    const { cmp, fixture, http } = await setup();
    cmp.show();
    cmp.onQuery('Rollen');
    fixture.detectChanges();

    // The page row is already there, before any response arrives.
    expect(screen.getByText('Rollen')).toBeInTheDocument();
    expect(screen.getByText('Verwaltung')).toBeInTheDocument();
    await answer(http, { hits: [], truncated: false, failed: [] });
  });

  it('gives a page row the icon of its section, not a gear for everything', async () => {
    // A gear on every page row said "setting" about pages that are not one. It stays on
    // the admin pages, where it is true.
    const { cmp } = await setup([
      { path: '/dashboard', label: 'Seite Dashboard', parentLabel: null },
      { path: '/admin/roles', label: 'Seite Rollen', parentLabel: 'Verwaltung' },
      { path: '/invoices', label: 'Seite Rechnungen', parentLabel: null },
    ]);
    cmp.show();
    cmp.query.set('seite');
    const byTitle = new Map(cmp.rows().map((r) => [r.title, r.icon]));
    expect(byTitle.get('Seite Dashboard')).toBe('home');
    expect(byTitle.get('Seite Rollen')).toBe('gear');
    expect(byTitle.get('Seite Rechnungen')).toBe('euro');
  });

  it('falls back to a gear for a section nothing maps', async () => {
    const { cmp } = await setup([{ path: '/somewhere-new', label: 'Neu', parentLabel: null }]);
    cmp.show();
    cmp.query.set('ne');
    expect(cmp.rows()[0]?.icon).toBe('gear');
  });

  it('shows records from the server under their own group', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    await answer(http);
    fixture.detectChanges();

    expect(screen.getByText('Anschaffung Beamer')).toBeInTheDocument();
    expect(screen.getByText('Entwurf')).toBeInTheDocument();
    expect(screen.getByText('Anträge')).toBeInTheDocument();
  });

  it('drops a stale answer when the query has moved on', async () => {
    // With a slow connection the answer to "ab" must never overwrite the answer to
    // "abcd". `switchMap` cancels the earlier request rather than racing it.
    const { cmp, http } = await setup([]);
    cmp.show();
    cmp.onQuery('abc');
    jest.advanceTimersByTime(200);
    const first = http.expectOne((r) => r.url.endsWith('/api/search'));

    cmp.onQuery('abcd');
    jest.advanceTimersByTime(200);
    expect(first.cancelled).toBe(true);

    const second = http.expectOne((r) => r.url.endsWith('/api/search'));
    expect(second.request.params.get('q')).toBe('abcd');
    second.flush(HITS);
  });

  it('clears the previous answer as soon as the query drops below the floor', async () => {
    // Otherwise the reader deletes characters and keeps seeing results for a query
    // that is no longer on screen.
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    await answer(http);
    fixture.detectChanges();
    expect(screen.getByText('Anschaffung Beamer')).toBeInTheDocument();

    cmp.onQuery('B');
    fixture.detectChanges();
    expect(screen.queryByText('Anschaffung Beamer')).not.toBeInTheDocument();
  });

  it('moves the highlight with the arrow keys and opens the row on Enter', async () => {
    const { cmp, fixture, http, router } = await setup();
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    cmp.show();
    cmp.onQuery('Re');
    await answer(http, { hits: [], truncated: false, failed: [] });
    fixture.detectChanges();

    expect(cmp.active()).toBe(0);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    fixture.detectChanges();
    // One page matches "Re" (Rechnungen), so the list wraps back to itself.
    expect(cmp.active()).toBe(0);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(nav).toHaveBeenCalledWith('/invoices');
    expect(cmp.open()).toBe(false);
  });

  it('navigates by URL, so a hit can carry a query string', async () => {
    // A cost-centre hit is `/budget?ks=…`, which `navigate` would not parse.
    const { cmp, fixture, http, router } = await setup([]);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    cmp.show();
    cmp.onQuery('VSM');
    await answer(http, {
      hits: [
        {
          kind: 'budget',
          id: 'b-1',
          title: 'VS-Mittel',
          subtitle: 'VSM',
          url: '/budget?ks=b-1',
        },
      ],
      truncated: false,
      failed: [],
    });
    fixture.detectChanges();

    await userEvent.click(screen.getByText('VS-Mittel'), { advanceTimers: jest.advanceTimersByTime });
    expect(nav).toHaveBeenCalledWith('/budget?ks=b-1');
  });

  it('says so when a source had more than it returned', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    await answer(http, { ...HITS, truncated: true });
    fixture.detectChanges();
    expect(screen.getByText('Es gibt weitere Treffer. Suchbegriff eingrenzen.')).toBeInTheDocument();
  });

  it('reports nothing found rather than staying blank', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('zzz');
    await answer(http, { hits: [], truncated: false, failed: [] });
    fixture.detectChanges();
    expect(screen.getByText('Nichts gefunden.')).toBeInTheDocument();
  });

  it('survives a failed request without leaving the spinner up', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    jest.advanceTimersByTime(200);
    http
      .expectOne((r) => r.url.endsWith('/api/search'))
      .flush(null, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(cmp.loading()).toBe(false);
    expect(cmp.rows()).toEqual([]);
  });

  it('starts each opening from a clean field', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    await answer(http);
    cmp.close();

    cmp.show();
    fixture.detectChanges();
    expect(cmp.query()).toBe('');
    expect(cmp.rows()).toEqual([]);
  });
});
