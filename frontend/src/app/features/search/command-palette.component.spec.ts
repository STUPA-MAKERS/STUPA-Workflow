import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { SearchResults } from '@core/api/models';
import { CommandPaletteComponent } from './command-palette.component';
import { CommandPaletteService } from './command-palette.service';
import { PageIndexService } from './page-index.service';
import { runAxe } from '../../../testing/a11y';

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
  // jsdom has no layout, so no scrollIntoView. The arrow keys call it for the active row.
  const scrollIntoView = jest.fn();
  beforeAll(() => (Element.prototype.scrollIntoView = scrollIntoView));
  beforeEach(() => {
    jest.useFakeTimers();
    scrollIntoView.mockClear();
  });
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
    expect(byTitle.get('Seite Rechnungen')).toBe('receipt');
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

    expect(screen.getByTitle('Anschaffung Beamer')).toBeInTheDocument();
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
    expect(screen.getByTitle('Anschaffung Beamer')).toBeInTheDocument();

    cmp.onQuery('B');
    fixture.detectChanges();
    expect(screen.queryByTitle('Anschaffung Beamer')).not.toBeInTheDocument();
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

  it('badges an archived hit and leaves a current one plain', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Antrag');
    await answer(http, {
      hits: [
        { kind: 'application', id: 'a-1', title: 'Laufend', subtitle: null,
          url: '/applications/a-1' },
        { kind: 'application', id: 'a-2', title: 'Archiviert', subtitle: null,
          url: '/applications/a-2', archived: true },
      ],
      truncated: false,
      failed: [],
    });
    fixture.detectChanges();

    const marks = fixture.nativeElement.querySelectorAll('.pal__archived');
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent.trim()).toBe('Archiviert');
  });

  it('groups the records by kind and gives each kind the icon of its area', async () => {
    const { cmp, fixture, http, container } = await setup([]);
    cmp.show();
    cmp.onQuery('rad');
    await answer(http, {
      hits: [
        { kind: 'application', id: 'a', title: 'Lastenrad', subtitle: 'Auf Tagesordnung', url: '/applications/a' },
        { kind: 'invoice', id: 'i', title: 'RE-118', subtitle: '2.890,00 € · Radhaus', url: '/invoices?id=i' },
        { kind: 'expense', id: 'e', title: 'Anzahlung Rad', subtitle: null, url: '/expenses?id=e' },
        { kind: 'principal', id: 'p', title: 'Konrad Pfeiffer', subtitle: 'k@stupa', url: '/admin/users' },
      ],
      truncated: false,
      failed: [],
    });
    fixture.detectChanges();
    expect(cmp.groups().map((g) => g.label)).toEqual(['Anträge', 'Rechnungen', 'Buchungen', 'Personen']);
    expect(cmp.rows().map((r) => r.icon)).toEqual(['file', 'receipt', 'swap', 'user']);
    expect(screen.getByRole('group', { name: 'Rechnungen' })).toBeInTheDocument();
    // The state of an application is status text; other subtitles are plain.
    const status = container.querySelector('app-status-text.pal__rowSub');
    expect(status).toHaveTextContent('Auf Tagesordnung');
  });

  it('marks the matching letters in titles and subtitles', async () => {
    const { cmp, fixture, http, container } = await setup([]);
    cmp.show();
    cmp.onQuery('rad');
    await answer(http, {
      hits: [{ kind: 'invoice', id: 'i', title: 'Lastenrad', subtitle: 'Radhaus', url: '/invoices' }],
      truncated: false,
      failed: [],
    });
    fixture.detectChanges();
    const hits = Array.from(container.querySelectorAll('.pal__hit')).map((h) => h.textContent);
    expect(hits).toEqual(['rad', 'Rad']);
    expect(container.querySelector('.pal__rowTitle')).toHaveTextContent('Lastenrad');
  });

  it('keeps the focus in the field and points it at the active row', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    await answer(http, {
      hits: [
        { kind: 'application', id: 'a-1', title: 'Beamer A', subtitle: null, url: '/applications/a-1' },
        { kind: 'application', id: 'a-2', title: 'Beamer B', subtitle: null, url: '/applications/a-2' },
      ],
      truncated: false,
      failed: [],
    });
    fixture.detectChanges();
    const field = screen.getByRole('combobox', { name: 'Suche' });
    const options = screen.getAllByRole('option');
    expect(field).toHaveAttribute('aria-activedescendant', options[0].id);
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(options[0]).toHaveTextContent('Enter');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    fixture.detectChanges();
    expect(field).toHaveAttribute('aria-activedescendant', options[1].id);
    expect(options[1]).toHaveAttribute('aria-selected', 'true');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp' }));
    fixture.detectChanges();
    expect(field).toHaveAttribute('aria-activedescendant', options[0].id);
  });

  it('shows the key hints at the foot and closes from the close control', async () => {
    const { cmp, fixture } = await setup([]);
    cmp.show();
    fixture.detectChanges();
    expect(screen.getByText('Auswählen')).toBeInTheDocument();
    expect(screen.getByText('Öffnen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Suche schließen' }), {
      advanceTimers: jest.advanceTimersByTime,
    });
    expect(cmp.open()).toBe(false);
  });

  it('opens from the service and starts clean there too', async () => {
    const { cmp, fixture, http } = await setup([]);
    const svc = TestBed.inject(CommandPaletteService);
    svc.open();
    cmp.onQuery('Beamer');
    await answer(http);
    svc.close();
    svc.open();
    fixture.detectChanges();
    expect(cmp.open()).toBe(true);
    expect(cmp.query()).toBe('');
    expect(cmp.rows()).toEqual([]);
  });

  it('keeps searching after a failed request', async () => {
    const { cmp, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    jest.advanceTimersByTime(200);
    http.expectOne((r) => r.url.endsWith('/api/search')).flush(null, { status: 500, statusText: 'Error' });
    cmp.onQuery('Beamer2');
    await answer(http);
    expect(cmp.rows().map((r) => r.title)).toEqual(['Anschaffung Beamer']);
  });

  it('gives the focus back to where it was when it closes', async () => {
    const { cmp, fixture } = await setup([]);
    const before = document.createElement('button');
    document.body.appendChild(before);
    before.focus();
    cmp.show();
    fixture.detectChanges();
    cmp.close();
    expect(before).toHaveFocus();
    before.remove();
  });

  it('has no a11y violations with results open', async () => {
    jest.useRealTimers();
    const { cmp, fixture, http, container } = await setup();
    cmp.show();
    cmp.onQuery('Rollen');
    await new Promise((r) => setTimeout(r, 200));
    http.expectOne((r) => r.url.endsWith('/api/search')).flush(HITS);
    fixture.detectChanges();
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('toggles on Ctrl+K and ignores other keys while closed or without rows', async () => {
    const { cmp, fixture } = await setup([]);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    expect(cmp.open()).toBe(false);
    cmp.close();
    expect(cmp.open()).toBe(false);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
    fixture.detectChanges();
    expect(cmp.open()).toBe(true);
    // No rows yet: the arrows and other keys do nothing.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    expect(cmp.active()).toBe(0);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
    expect(cmp.open()).toBe(false);
  });

  it('scrolls the active row into view and ignores keys other than the arrows and Enter', async () => {
    const { cmp, fixture, http } = await setup([]);
    cmp.show();
    cmp.onQuery('Beamer');
    await answer(http, {
      hits: [
        { kind: 'application', id: 'a-1', title: 'Beamer A', subtitle: null, url: '/applications/a-1' },
        { kind: 'application', id: 'a-2', title: 'Beamer B', subtitle: null, url: '/applications/a-2' },
      ],
      truncated: false,
      failed: [],
    });
    fixture.detectChanges();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    jest.runAllTicks();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
    expect(cmp.active()).toBe(1);
    expect(cmp.open()).toBe(true);
  });
});
