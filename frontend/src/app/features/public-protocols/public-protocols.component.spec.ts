import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Meta } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError, type Observable } from 'rxjs';
import type { PublicProtocolPage, PublicSemester } from './public-protocols.models';
import { PublicProtocolsComponent } from './public-protocols.component';
import { ToastService } from '@stupa-makers/ui-kit';
import { PublicProtocolsService } from './public-protocols.service';
import { pageFixture, summaryFixture } from './public-protocols.fixtures';

const GREMIEN = [
  { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa', protocolCount: 8, latestDate: '2026-09-29' },
  { id: 'g-2', name: 'AStA', slug: 'asta', protocolCount: 7, latestDate: '2026-07-14' },
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

/** A stand-in of the toasts: the kit public screen shows a failed first read as a toast. */
function makeToasts(): Record<string, jest.Mock> {
  const fns: Record<string, jest.Mock> = {};
  return new Proxy(fns, { get: (t, k: string) => (t[k] ??= jest.fn(() => 1)) });
}
let toasts = makeToasts();

/** The row cards; the kit public screen is an `article` too. */
const allCards = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('article.pp__card')];
const oneCard = (): HTMLElement => {
  const all = allCards();
  if (all.length !== 1) throw new Error(`expected one card, found ${all.length}`);
  return all[0];
};

async function setup(api = makeApi(), committee = 'stupa') {
  const view = await render(PublicProtocolsComponent, {
    providers: [
      provideRouter([]),
      { provide: PublicProtocolsService, useValue: api },
      { provide: ToastService, useValue: toasts },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: convertToParamMap({ committee }), queryParamMap: convertToParamMap({}) },
        },
      },
    ],
  });
  return { ...view, api };
}

describe('PublicProtocolsComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    toasts = makeToasts();
  });
  afterEach(() => localStorage.clear());

  /** The page shows no raw ids. */
  it('lists the protocols by semester with the agenda, the results and the PDF', async () => {
    const { api } = await setup();
    expect(api.list).toHaveBeenCalledWith({ gremium: ['g-1'], semester: '', q: '', limit: 20 });
    expect(screen.getByRole('heading', { level: 1, name: 'Studierendenparlament' })).toBeInTheDocument();
    const crumbs = screen.getByRole('navigation', { name: 'Pfad' });
    expect(within(crumbs).getByRole('link', { name: 'Öffentliche Protokolle' })).toHaveAttribute('href', '/protocols');
    expect(within(crumbs).getByText('Studierendenparlament')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('heading', { level: 2, name: 'Sommersemester 2026' })).toBeInTheDocument();
    const card = oneCard();
    expect(within(card).getByText('Di, 29.09.2026')).toBeInTheDocument();
    expect(
      within(card).getByRole('link', { name: '34. Sitzung des Studierendenparlaments' }),
    ).toHaveAttribute('href', '/protocols/p-1');
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
    expect(screen.getByText('1 Protokoll')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Beschlüsse' })).toHaveAttribute('href', '/decisions/stupa');
    expect(document.body.textContent).not.toContain('g-1');
    expect(TestBed.inject(Meta).getTag('name="robots"')?.content).toBe('noindex');
  });

  /** A group without a semester count counts its loaded rows. */
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
    expect(screen.getByRole('heading', { level: 2, name: 'Wintersemester 2025/26' })).toBeInTheDocument();
    const first = allCards()[0];
    expect(within(first).queryByRole('link', { name: /PDF/ })).toBeNull();
    expect(within(first).getByText('PDF')).toBeInTheDocument();
  });

  /** Enter with the same text searches nothing new. */
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
    const calls = api.list.mock.calls.length;
    await userEvent.type(box, '{enter}');
    expect(api.list.mock.calls.length).toBe(calls);
    await userEvent.type(box, 'halt{enter}');
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Haushalt' }));
  });

  /** The semester counts do not depend on the semester filter. The page has no Gremium chip. */
  it('filters by a semester and has no gremium filter', async () => {
    const { api } = await setup();
    expect(screen.queryByRole('button', { name: /^Gremium/ })).toBeNull();
    const semesterCalls = api.semesters.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Semester: Alle' }));
    await userEvent.click(screen.getByRole('option', { name: 'Sommersemester 2026' }));
    expect(api.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ gremium: ['g-1'], semester: 'ss-2026' }),
    );
    expect(api.semesters.mock.calls.length).toBe(semesterCalls);
    expect(screen.getByRole('button', { name: 'Semester: Sommersemester 2026' })).toBeInTheDocument();
  });

  /** Spec 002403: a slug of no public Gremium reads no page. */
  it('shows the empty state for a slug of no public gremium', async () => {
    const { api } = await setup(makeApi(), 'nope');
    expect(api.list).not.toHaveBeenCalled();
    expect(screen.getByText('Keine öffentlichen Protokolle')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Alle Gremien/ })).toHaveAttribute('href', '/protocols');
    expect(screen.getByRole('heading', { level: 1, name: 'Öffentliche Protokolle' })).toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).toBeNull();
  });

  it('reports a failed read of the gremien', async () => {
    const { api } = await setup(makeApi({ gremien: jest.fn(() => throwError(() => new Error('down'))) }));
    expect(api.list).not.toHaveBeenCalled();
    expect(toasts['showAction']).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('Die Protokolle konnten nicht geladen werden.') }),
    );
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
    expect(allCards()).toHaveLength(2);
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
    expect(allCards()).toHaveLength(1);
  });

  /** A new filter starts while the next page still loads. */
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
      .mockReturnValueOnce(of(pageFixture([summaryFixture()])))
      .mockReturnValueOnce(stale)
      .mockReturnValue(of(pageFixture([summaryFixture({ id: 'p-9', title: 'Neu' })])));
    const { fixture } = await setup(makeApi({ list }));
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
    await userEvent.type(screen.getByRole('searchbox'), 'y{enter}');
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

  it('says that the gremium has no protocols yet and links back to the start', async () => {
    await setup(makeApi({ list: jest.fn(() => of(pageFixture([]))) }));
    expect(screen.getByText('Noch keine öffentlichen Protokolle')).toBeInTheDocument();
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
    expect(screen.getByText('Keine Protokolle gefunden')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    expect(api.list).toHaveBeenLastCalledWith({ gremium: ['g-1'], semester: '', q: '', limit: 20 });
    expect(oneCard()).toBeInTheDocument();
  });

  it('reports a failed list', async () => {
    const list = jest
      .fn()
      .mockReturnValueOnce(throwError(() => new Error('down')))
      .mockReturnValue(of(pageFixture([summaryFixture()])));
    const { api } = await setup(makeApi({ list }));
    const toast = toasts['showAction'].mock.calls[0][0];
    expect(toast.message).toContain('Die Protokolle konnten nicht geladen werden.');
    toast.closed('action');
    expect(api.list).toHaveBeenCalledTimes(2);
    expect(await waitFor(() => oneCard())).toBeInTheDocument();
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
    expect(screen.getByRole('link', { name: 'Public minutes' })).toHaveAttribute('href', '/protocols');
    expect(screen.getByRole('heading', { level: 2, name: /Summer semester 2026/ })).toBeInTheDocument();
  });
});
