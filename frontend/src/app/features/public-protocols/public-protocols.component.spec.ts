import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Meta } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError, type Observable } from 'rxjs';
import type { PublicProtocolPage, PublicSemester } from './public-protocols.models';
import { PublicProtocolsComponent } from './public-protocols.component';
import { PublicProtocolsService } from './public-protocols.service';
import { pageFixture, summaryFixture } from './public-protocols.fixtures';

const GREMIEN = [
  { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa', protocolCount: 8 },
  { id: 'g-2', name: 'AStA', slug: 'asta', protocolCount: 7 },
];

function makeApi(over: Record<string, jest.Mock> = {}) {
  return {
    gremien: jest.fn(() => of(GREMIEN)),
    list: jest.fn((): Observable<PublicProtocolPage> => of(pageFixture([summaryFixture()]))),
    semesters: jest.fn((): Observable<PublicSemester[]> => of([{ key: 'ss-2026', count: 12 }])),
    pdfUrl: (id: string) => `/api/public/protocols/${id}/pdf`,
    ...over,
  };
}

async function setup(api = makeApi(), query: Record<string, string | string[]> = {}) {
  const view = await render(PublicProtocolsComponent, {
    providers: [
      provideRouter([]),
      { provide: PublicProtocolsService, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { queryParamMap: convertToParamMap(query) } },
      },
    ],
  });
  return { ...view, api };
}

describe('PublicProtocolsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('lists the protocols by semester with the agenda, the results and the PDF', async () => {
    const { api } = await setup();
    expect(api.list).toHaveBeenCalledWith({ gremium: [], semester: '', q: '', limit: 20 });
    expect(screen.getByRole('heading', { level: 1, name: 'Öffentliche Protokolle' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /Sommersemester 2026\s*12/ })).toBeInTheDocument();
    const card = screen.getByRole('article');
    expect(within(card).getByText('Studierendenparlament · Di, 29.09.2026')).toBeInTheDocument();
    expect(
      within(card).getByRole('link', { name: '34. Sitzung des Studierendenparlaments' }),
    ).toHaveAttribute('href', '/protokolle/p-1');
    expect(within(card).getByText('Nicht-öffentlicher TOP')).toBeInTheDocument();
    expect(within(card).getByText('Angenommen')).toBeInTheDocument();
    expect(within(card).getByText('Abgelehnt')).toBeInTheDocument();
    expect(within(card).getByText('2 Beschlüsse')).toBeInTheDocument();
    expect(within(card).getByText('1 nicht-öffentlicher TOP ausgelassen')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: /PDF \(öffentliche Fassung\)/ })).toHaveAttribute(
      'href',
      '/api/public/protocols/p-1/pdf',
    );
    expect(within(card).getByText('PDF · 212 KB · finalisiert 02.10.2026')).toBeInTheDocument();
    expect(screen.getByText('1 Protokolle')).toBeInTheDocument();
    // No raw ids on the page.
    expect(document.body.textContent).not.toContain('g-1');
    expect(TestBed.inject(Meta).getTag('name="robots"')?.content).toBe('noindex');
  });

  it('words the counts of a protocol without decisions and with several skipped items', async () => {
    const one = summaryFixture({
      hasPdf: false,
      pdfSize: null,
      finalizedAt: null,
      tops: [
        { number: 1, title: 'A', nonPublic: false, results: ['passed'] },
        { number: 2, title: null, nonPublic: true, results: [] },
        { number: 3, title: null, nonPublic: true, results: [] },
      ],
    });
    const none = summaryFixture({ id: 'p-2', semester: 'ws-2025', tops: [] });
    await setup(makeApi({ list: jest.fn(() => of(pageFixture([one, none]))) }));
    expect(screen.getByText('1 Beschluss')).toBeInTheDocument();
    expect(screen.getByText('2 nicht-öffentliche TOPs ausgelassen')).toBeInTheDocument();
    expect(screen.getByText('Ohne Beschluss')).toBeInTheDocument();
    // A group without a semester count counts its loaded rows.
    expect(screen.getByRole('heading', { level: 2, name: /Wintersemester 2025\/26\s*1/ })).toBeInTheDocument();
    const first = screen.getAllByRole('article')[0];
    expect(within(first).queryByRole('link', { name: /PDF/ })).toBeNull();
    expect(within(first).getByText('PDF')).toBeInTheDocument();
  });

  it('searches after a pause and on Enter, marks the hits and words the count', async () => {
    const { api } = await setup();
    const box = screen.getByRole('searchbox', { name: 'Titel oder Text suchen' });
    await userEvent.type(box, 'Haus');
    await waitFor(() =>
      expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Haus' })),
    );
    expect(api.semesters).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Haus' }));
    expect(await screen.findByText('Haus', { selector: 'mark' })).toBeInTheDocument();
    expect(screen.getByText('1 Treffer')).toBeInTheDocument();
    expect(screen.getByText(/Gesucht wird in Sitzungstiteln/)).toBeInTheDocument();
    const calls = api.list.mock.calls.length;
    // Enter with the same text searches nothing new.
    await userEvent.type(box, '{enter}');
    expect(api.list.mock.calls.length).toBe(calls);
    await userEvent.type(box, 'halt{enter}');
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Haushalt' }));
  });

  it('filters by several gremien and a semester', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Gremium' }));
    await userEvent.click(screen.getByRole('option', { name: 'Studierendenparlament' }));
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ gremium: ['g-1'] }));
    expect(screen.getByRole('button', { name: 'Gremium: Studierendenparlament' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('option', { name: 'AStA' }));
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ gremium: ['g-1', 'g-2'] }));
    expect(screen.getByRole('button', { name: 'Gremium: 2 Gremien' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');

    const semesterCalls = api.semesters.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Semester: Alle' }));
    await userEvent.click(screen.getByRole('option', { name: 'Sommersemester 2026' }));
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ semester: 'ss-2026' }));
    // The semester counts do not depend on the semester filter.
    expect(api.semesters.mock.calls.length).toBe(semesterCalls);
    expect(screen.getByRole('button', { name: 'Semester: Sommersemester 2026' })).toBeInTheDocument();
  });

  it('takes the gremium from the link of a detail page', async () => {
    const { api } = await setup(makeApi(), { gremium: 'g-1' });
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ gremium: ['g-1'] }));
    expect(screen.getByRole('button', { name: 'Gremium: Studierendenparlament' })).toBeInTheDocument();
  });

  it('counts a gremium of an old link that publishes no more', async () => {
    await setup(makeApi(), { gremium: 'g-x' });
    expect(screen.getByRole('button', { name: 'Gremium: 1 Gremien' })).toBeInTheDocument();
  });

  it('loads the next page once while it runs', async () => {
    const next = new Subject<PublicProtocolPage>();
    const list = jest
      .fn()
      .mockReturnValueOnce(of(pageFixture([summaryFixture()], 2)))
      .mockReturnValueOnce(next);
    const { fixture } = await setup(makeApi({ list }));
    const cmp = fixture.componentInstance as unknown as { loadMore(): void };
    cmp.loadMore();
    cmp.loadMore();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('loads more pages and appends them', async () => {
    const list = jest
      .fn()
      .mockReturnValueOnce(of(pageFixture([summaryFixture()], 2)))
      .mockReturnValueOnce(of(pageFixture([summaryFixture({ id: 'p-2', title: 'Zweite' })], 2, 1)));
    const { api } = await setup(makeApi({ list }));
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Protokolle laden' }));
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1 }));
    expect(screen.getAllByRole('article')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Weitere Protokolle laden' })).toBeNull();
  });

  it('reports a failed next page below the rows', async () => {
    const list = jest
      .fn()
      .mockReturnValueOnce(of(pageFixture([summaryFixture()], 2)))
      .mockReturnValueOnce(throwError(() => new Error('down')));
    await setup(makeApi({ list }));
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Protokolle laden' }));
    expect(screen.getByRole('alert')).toHaveTextContent('nicht geladen');
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });

  it('drops the answer of an older request', async () => {
    const first = new Subject<PublicProtocolPage>();
    const more = new Subject<PublicProtocolPage>();
    const list = jest
      .fn()
      .mockReturnValueOnce(of(pageFixture([summaryFixture()], 3)))
      .mockReturnValueOnce(more)
      .mockReturnValueOnce(first)
      .mockReturnValue(of(pageFixture([summaryFixture({ id: 'p-9', title: 'Neu' })])));
    const semesters = jest.fn().mockReturnValueOnce(of([])).mockReturnValue(new Subject());
    const { fixture } = await setup(makeApi({ list, semesters }));
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Protokolle laden' }));
    // A new filter starts while the next page still loads.
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
    more.next(pageFixture([summaryFixture({ id: 'p-old', title: 'Alt' })], 3));
    more.error(new Error('late'));
    fixture.detectChanges();
    expect(screen.queryByText('Alt')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    first.next(pageFixture([summaryFixture({ id: 'p-9', title: 'Neu' })]));
    fixture.detectChanges();
    expect(await screen.findByText('Neu')).toBeInTheDocument();
  });

  it('drops a stale first page', async () => {
    const stale = new Subject<PublicProtocolPage>();
    const list = jest
      .fn()
      .mockReturnValueOnce(stale)
      .mockReturnValue(of(pageFixture([summaryFixture({ id: 'p-9', title: 'Neu' })])));
    const { fixture } = await setup(makeApi({ list }));
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
    stale.next(pageFixture([summaryFixture({ id: 'p-old', title: 'Alt' })]));
    stale.error(new Error('late'));
    fixture.detectChanges();
    expect(screen.getByText('Neu')).toBeInTheDocument();
    expect(screen.queryByText('Alt')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('ignores stale semester answers and failed ones', async () => {
    const late = new Subject<PublicSemester[]>();
    const semesters = jest
      .fn()
      .mockReturnValueOnce(late)
      .mockReturnValueOnce(throwError(() => new Error('down')));
    await setup(makeApi({ semesters }));
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
    late.next([{ key: 'ss-2026', count: 99 }]);
    late.error(new Error('late'));
    expect(screen.queryByText('99')).toBeNull();
  });

  it('says that no gremium publishes yet and links back to the start', async () => {
    await setup(
      makeApi({
        list: jest.fn(() => of(pageFixture([]))),
        gremien: jest.fn(() => throwError(() => new Error('down'))),
      }),
    );
    expect(screen.getByRole('heading', { name: 'Noch keine öffentlichen Protokolle' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Zur Startseite/ })).toHaveAttribute('href', '/');
    expect(screen.queryByRole('searchbox')).toBeNull();
  });

  it('says that nothing matches and resets the filters', async () => {
    const list = jest
      .fn()
      .mockReturnValueOnce(of(pageFixture([summaryFixture()])))
      .mockReturnValueOnce(of(pageFixture([])))
      .mockReturnValue(of(pageFixture([summaryFixture()])));
    const { api } = await setup(makeApi({ list }));
    await userEvent.type(screen.getByRole('searchbox'), 'Haushalt 2025{enter}');
    expect(screen.getByRole('heading', { name: 'Keine Protokolle gefunden' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    expect(api.list).toHaveBeenLastCalledWith({ gremium: [], semester: '', q: '', limit: 20 });
    expect(screen.getByRole('article')).toBeInTheDocument();
  });

  it('reports a failed list', async () => {
    await setup(makeApi({ list: jest.fn(() => throwError(() => new Error('down'))) }));
    expect(screen.getByRole('alert')).toHaveTextContent('Die Protokolle konnten nicht geladen werden.');
  });

  it('cancels a pending search when the page goes away', async () => {
    const { api, fixture } = await setup();
    await userEvent.type(screen.getByRole('searchbox'), 'ab');
    const calls = api.list.mock.calls.length;
    fixture.destroy();
    await new Promise((r) => setTimeout(r, 400));
    expect(api.list.mock.calls.length).toBe(calls);
  });

  it('localizes to English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Public minutes' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /Summer semester 2026/ })).toBeInTheDocument();
  });
});
