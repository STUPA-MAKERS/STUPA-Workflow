import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Meta } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError, type Observable } from 'rxjs';
import type {
  PublicDecisionPage,
  PublicDecisionRow,
  PublicSemester,
} from './public-protocols.models';
import { PublicDecisionsComponent } from './public-decisions.component';
import { ToastService } from '@stupa-makers/ui-kit';
import { PublicProtocolsService } from './public-protocols.service';
import { decisionRowFixture } from './public-protocols.fixtures';

const GREMIEN = [
  { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa', protocolCount: 8, latestDate: '2026-09-29' },
  { id: 'g-2', name: 'AStA', slug: 'asta', protocolCount: 7, latestDate: '2026-07-14' },
];

function page(items: readonly PublicDecisionRow[], total = items.length, offset = 0): PublicDecisionPage {
  return { items, total, limit: 20, offset };
}

function makeApi(over: Record<string, jest.Mock> = {}) {
  return {
    gremien: jest.fn(() => of(GREMIEN)),
    decisions: jest.fn((): Observable<PublicDecisionPage> => of(page([decisionRowFixture()]))),
    semesters: jest.fn((): Observable<PublicSemester[]> => of([{ key: 'ss-2026', count: 12 }])),
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
  const view = await render(PublicDecisionsComponent, {
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

const MORE = 'Weitere Beschlüsse laden';

describe('PublicDecisionsComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    toasts = makeToasts();
  });
  afterEach(() => localStorage.clear());

  it('lists a motion with its meeting, its result and the sums of the votes', async () => {
    const { api } = await setup();
    expect(api.decisions).toHaveBeenCalledWith({ gremium: ['g-1'], semester: '', q: '', limit: 20 });
    expect(api.semesters).toHaveBeenCalledWith({ gremium: ['g-1'] });
    expect(screen.getByRole('heading', { level: 1, name: 'Studierendenparlament' })).toBeInTheDocument();
    const crumbs = screen.getByRole('navigation', { name: 'Pfad' });
    expect(within(crumbs).getByRole('link', { name: 'Beschlüsse' })).toHaveAttribute('href', '/decisions');
    expect(screen.getByRole('heading', { level: 2, name: 'Sommersemester 2026' })).toBeInTheDocument();
    const card = oneCard();
    expect(within(card).getByRole('heading', { level: 3, name: 'Zuschuss für das Sommerfest' })).toBeInTheDocument();
    expect(within(card).getByText('Di, 29.09.2026')).toBeInTheDocument();
    expect(within(card).getByText('34. Sitzung des Studierendenparlaments')).toBeInTheDocument();
    expect(within(card).getByText('Angenommen')).toBeInTheDocument();
    expect(within(card).getByText('Ja 5')).toBeInTheDocument();
    expect(within(card).getByText('Nein 1')).toBeInTheDocument();
    expect(within(card).getByText('Enthaltung 0')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: /Zum Protokoll/ })).toHaveAttribute('href', '/protocols/p-1');
    expect(screen.getByRole('link', { name: 'Protokolle' })).toHaveAttribute('href', '/protocols/stupa');
    expect(document.body.textContent).not.toContain('g-1');
    expect(TestBed.inject(Meta).getTag('name="robots"')?.content).toBe('noindex');
  });

  it('shows an election with its question and its date only', async () => {
    const election = decisionRowFixture({
      kind: 'election',
      question: 'Wahl des Vorsitzes',
      meetingTitle: null,
      result: null,
      counts: {},
    });
    await setup(makeApi({ decisions: jest.fn(() => of(page([election]))) }));
    const card = oneCard();
    expect(within(card).getByRole('heading', { level: 3, name: 'Wahl des Vorsitzes' })).toBeInTheDocument();
    expect(within(card).getByText('Wahl')).toBeInTheDocument();
    expect(within(card).getByText('Di, 29.09.2026')).toBeInTheDocument();
    expect(within(card).queryByText(/Sitzung/)).toBeNull();
    expect(within(card).queryByText('Angenommen')).toBeNull();
  });

  it('names a circular vote in place of a meeting and links no protocol (§F/meetings/voting/000949)', async () => {
    const circular = decisionRowFixture({
      kind: 'circular',
      protocolId: null,
      question: 'Lastenanhänger beschaffen',
      meetingTitle: null,
      date: '2026-10-20',
    });
    await setup(makeApi({ decisions: jest.fn(() => of(page([circular]))) }));
    const card = oneCard();
    expect(within(card).getByText('Lastenanhänger beschaffen')).toBeInTheDocument();
    expect(within(card).getByText('Umlaufverfahren')).toBeInTheDocument();
    expect(within(card).getByText('Angenommen')).toBeInTheDocument();
    expect(within(card).queryByRole('link')).toBeNull();
  });

  it('words a rejected motion, another option and a missing question', async () => {
    const rows = [
      decisionRowFixture({ result: 'rejected', counts: { ja: 1, vertagen: 2 } }),
      decisionRowFixture({ question: null, result: null, counts: {}, semester: 'ws-2025' }),
    ];
    await setup(makeApi({ decisions: jest.fn(() => of(page(rows))) }));
    const [first, second] = allCards();
    expect(within(first).getByText('Abgelehnt')).toHaveClass('pp__result--no');
    expect(within(first).getByText('vertagen 2')).toBeInTheDocument();
    expect(within(second).getByRole('heading', { level: 3, name: 'Beschluss ohne Frage' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Wintersemester 2025/26' })).toBeInTheDocument();
  });

  it('searches after a pause and on Enter and marks the hits', async () => {
    const { api } = await setup();
    const box = screen.getByRole('searchbox', { name: 'Beschluss suchen' });
    await userEvent.type(box, 'Sommer');
    await waitFor(() =>
      expect(api.decisions).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Sommer' })),
    );
    expect(await screen.findByText('Sommer', { selector: 'mark' })).toBeInTheDocument();
    await userEvent.type(box, 'fest{enter}');
    expect(api.decisions).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Sommerfest' }));
  });

  it('filters by a semester and has no gremium filter', async () => {
    const { api } = await setup();
    expect(screen.queryByRole('button', { name: /^Gremium/ })).toBeNull();
    const semesterCalls = api.semesters.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Semester: Alle' }));
    await userEvent.click(screen.getByRole('option', { name: 'Sommersemester 2026' }));
    expect(api.decisions).toHaveBeenLastCalledWith(
      expect.objectContaining({ gremium: ['g-1'], semester: 'ss-2026' }),
    );
    expect(api.semesters.mock.calls.length).toBe(semesterCalls);
    expect(screen.getByRole('button', { name: 'Semester: Sommersemester 2026' })).toBeInTheDocument();
  });

  /** Spec 002403: a slug of no public Gremium reads no page and links the list of Gremien. */
  it('shows the empty state for a slug of no public gremium', async () => {
    const { api } = await setup(makeApi(), 'nope');
    expect(api.decisions).not.toHaveBeenCalled();
    expect(screen.getByText('Keine öffentlichen Protokolle')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Alle Gremien/ })).toHaveAttribute('href', '/decisions');
    expect(screen.getByRole('heading', { level: 1, name: 'Beschlüsse' })).toBeInTheDocument();
  });

  it('reads the gremien again after a failed read', async () => {
    const gremien = jest
      .fn()
      .mockReturnValueOnce(throwError(() => new Error('down')))
      .mockReturnValue(of(GREMIEN));
    const { api } = await setup(makeApi({ gremien }));
    expect(api.decisions).not.toHaveBeenCalled();
    toasts['show'].mock.calls[0][0].closed('action');
    expect(api.decisions).toHaveBeenCalledWith(expect.objectContaining({ gremium: ['g-1'] }));
  });

  it('loads the next page once while it runs', async () => {
    const next = new Subject<PublicDecisionPage>();
    const decisions = jest
      .fn()
      .mockReturnValueOnce(of(page([decisionRowFixture()], 2)))
      .mockReturnValueOnce(next);
    const { fixture } = await setup(makeApi({ decisions }));
    const cmp = fixture.componentInstance as unknown as { loadMore(): void };
    cmp.loadMore();
    cmp.loadMore();
    expect(decisions).toHaveBeenCalledTimes(2);
  });

  it('loads more pages and appends them', async () => {
    const decisions = jest
      .fn()
      .mockReturnValueOnce(of(page([decisionRowFixture()], 2)))
      .mockReturnValueOnce(of(page([decisionRowFixture({ question: 'Zweite' })], 2, 1)));
    const { api } = await setup(makeApi({ decisions }));
    await userEvent.click(screen.getByRole('button', { name: MORE }));
    expect(api.decisions).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1 }));
    expect(allCards()).toHaveLength(2);
    expect(screen.queryByRole('button', { name: MORE })).toBeNull();
  });

  it('reports a failed next page below the rows', async () => {
    const decisions = jest
      .fn()
      .mockReturnValueOnce(of(page([decisionRowFixture()], 2)))
      .mockReturnValueOnce(throwError(() => new Error('down')));
    await setup(makeApi({ decisions }));
    await userEvent.click(screen.getByRole('button', { name: MORE }));
    expect(screen.getByRole('alert')).toHaveTextContent('nicht geladen');
    expect(allCards()).toHaveLength(1);
  });

  it('drops the answer of an older request', async () => {
    const first = new Subject<PublicDecisionPage>();
    const more = new Subject<PublicDecisionPage>();
    const decisions = jest
      .fn()
      .mockReturnValueOnce(of(page([decisionRowFixture()], 3)))
      .mockReturnValueOnce(more)
      .mockReturnValueOnce(first)
      .mockReturnValue(of(page([decisionRowFixture({ question: 'Neu' })])));
    const semesters = jest.fn().mockReturnValueOnce(of([])).mockReturnValue(new Subject());
    const { fixture } = await setup(makeApi({ decisions, semesters }));
    await userEvent.click(screen.getByRole('button', { name: MORE }));
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
    more.next(page([decisionRowFixture({ question: 'Alt' })], 3));
    more.error(new Error('late'));
    fixture.detectChanges();
    expect(screen.queryByText('Alt')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    first.next(page([decisionRowFixture({ question: 'Neu' })]));
    fixture.detectChanges();
    expect(await screen.findByText('Neu')).toBeInTheDocument();
  });

  it('drops a stale first page', async () => {
    const stale = new Subject<PublicDecisionPage>();
    const decisions = jest
      .fn()
      .mockReturnValueOnce(of(page([decisionRowFixture()])))
      .mockReturnValueOnce(stale)
      .mockReturnValue(of(page([decisionRowFixture({ question: 'Neu' })])));
    const { fixture } = await setup(makeApi({ decisions }));
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
    await userEvent.type(screen.getByRole('searchbox'), 'y{enter}');
    stale.next(page([decisionRowFixture({ question: 'Alt' })]));
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
    late.next([{ key: 'ws-2030', count: 1 }]);
    late.error(new Error('late'));
    await userEvent.click(screen.getByRole('button', { name: 'Semester: Alle' }));
    expect(screen.queryByRole('option', { name: /2030/ })).toBeNull();
  });

  it('says that no decision is public yet and links to the protocols', async () => {
    await setup(makeApi({ decisions: jest.fn(() => of(page([]))) }));
    expect(screen.getByText('Noch keine öffentlichen Beschlüsse')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Protokolle/ })[1]).toHaveAttribute('href', '/protocols/stupa');
    expect(screen.queryByRole('searchbox')).toBeNull();
  });

  it('says that nothing matches and resets the filters', async () => {
    const decisions = jest
      .fn()
      .mockReturnValueOnce(of(page([decisionRowFixture()])))
      .mockReturnValueOnce(of(page([])))
      .mockReturnValue(of(page([decisionRowFixture()])));
    const { api } = await setup(makeApi({ decisions }));
    await userEvent.type(screen.getByRole('searchbox'), 'Haushalt{enter}');
    expect(screen.getByText('Keine Beschlüsse gefunden')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    expect(api.decisions).toHaveBeenLastCalledWith({ gremium: ['g-1'], semester: '', q: '', limit: 20 });
    expect(oneCard()).toBeInTheDocument();
  });

  it('reports a failed list', async () => {
    await setup(makeApi({ decisions: jest.fn(() => throwError(() => new Error('down'))) }));
    expect(toasts['show']).toHaveBeenCalledWith(
      expect.objectContaining({
        text: expect.stringContaining('Die Beschlüsse konnten nicht geladen werden.'),
      }),
    );
  });

  it('localizes to English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByRole('link', { name: 'Decisions' })).toHaveAttribute('href', '/decisions');
    expect(screen.getByText('Passed')).toBeInTheDocument();
  });
});
