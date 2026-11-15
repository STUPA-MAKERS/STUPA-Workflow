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
import { PublicProtocolsService } from './public-protocols.service';
import { decisionRowFixture } from './public-protocols.fixtures';

const GREMIEN = [
  { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa', protocolCount: 8 },
  { id: 'g-2', name: 'AStA', slug: 'asta', protocolCount: 7 },
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

async function setup(api = makeApi(), query: Record<string, string | string[]> = {}) {
  const view = await render(PublicDecisionsComponent, {
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

const MORE = 'Weitere Beschlüsse laden';

describe('PublicDecisionsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('lists a motion with its meeting, its result and the sums of the votes', async () => {
    const { api } = await setup();
    expect(api.decisions).toHaveBeenCalledWith({ gremium: [], semester: '', q: '', limit: 20 });
    expect(api.semesters).toHaveBeenCalledWith({ gremium: [] });
    expect(screen.getByRole('heading', { level: 1, name: 'Beschlüsse' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Sommersemester 2026' })).toBeInTheDocument();
    const card = screen.getByRole('article');
    expect(within(card).getByRole('heading', { level: 3, name: 'Zuschuss für das Sommerfest' })).toBeInTheDocument();
    expect(within(card).getByText('Studierendenparlament')).toBeInTheDocument();
    expect(within(card).getByText('Di, 29.09.2026')).toBeInTheDocument();
    expect(within(card).getByText('34. Sitzung des Studierendenparlaments')).toBeInTheDocument();
    expect(within(card).getByText('Angenommen')).toBeInTheDocument();
    expect(within(card).getByText('Ja 5')).toBeInTheDocument();
    expect(within(card).getByText('Nein 1')).toBeInTheDocument();
    expect(within(card).getByText('Enthaltung 0')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: /Zum Protokoll/ })).toHaveAttribute('href', '/protocols/p-1');
    expect(screen.getByRole('link', { name: 'Öffentliche Protokolle' })).toHaveAttribute('href', '/protocols');
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
    const card = screen.getByRole('article');
    expect(within(card).getByRole('heading', { level: 3, name: 'Wahl des Vorsitzes' })).toBeInTheDocument();
    expect(within(card).getByText('Wahl')).toBeInTheDocument();
    expect(within(card).getByText('Di, 29.09.2026')).toBeInTheDocument();
    expect(within(card).queryByText(/Sitzung/)).toBeNull();
    expect(within(card).queryByText('Angenommen')).toBeNull();
  });

  it('words a rejected motion, another option and a missing question', async () => {
    const rows = [
      decisionRowFixture({ result: 'rejected', counts: { ja: 1, vertagen: 2 } }),
      decisionRowFixture({ question: null, result: null, counts: {}, semester: 'ws-2025' }),
    ];
    await setup(makeApi({ decisions: jest.fn(() => of(page(rows))) }));
    const [first, second] = screen.getAllByRole('article');
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

  it('filters by several gremien and a semester', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Gremium' }));
    await userEvent.click(screen.getByRole('option', { name: 'Studierendenparlament' }));
    expect(api.decisions).toHaveBeenLastCalledWith(expect.objectContaining({ gremium: ['g-1'] }));
    expect(screen.getByRole('button', { name: 'Gremium: Studierendenparlament' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('option', { name: 'AStA' }));
    expect(screen.getByRole('button', { name: 'Gremium: 2 Gremien' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');

    const semesterCalls = api.semesters.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Semester: Alle' }));
    await userEvent.click(screen.getByRole('option', { name: 'Sommersemester 2026' }));
    expect(api.decisions).toHaveBeenLastCalledWith(expect.objectContaining({ semester: 'ss-2026' }));
    expect(api.semesters.mock.calls.length).toBe(semesterCalls);
    expect(screen.getByRole('button', { name: 'Semester: Sommersemester 2026' })).toBeInTheDocument();
  });

  it('takes the gremium from a link and counts an unknown one', async () => {
    const { api } = await setup(makeApi(), { committee: 'g-x' });
    expect(api.decisions).toHaveBeenCalledWith(expect.objectContaining({ gremium: ['g-x'] }));
    expect(screen.getByRole('button', { name: 'Gremium: 1 Gremien' })).toBeInTheDocument();
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
    expect(screen.getAllByRole('article')).toHaveLength(2);
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
    expect(screen.getAllByRole('article')).toHaveLength(1);
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
      .mockReturnValueOnce(stale)
      .mockReturnValue(of(page([decisionRowFixture({ question: 'Neu' })])));
    const { fixture } = await setup(makeApi({ decisions }));
    await userEvent.type(screen.getByRole('searchbox'), 'x{enter}');
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
    await setup(
      makeApi({
        decisions: jest.fn(() => of(page([]))),
        gremien: jest.fn(() => throwError(() => new Error('down'))),
      }),
    );
    expect(screen.getByText('Noch keine öffentlichen Beschlüsse')).toBeInTheDocument();
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
    expect(api.decisions).toHaveBeenLastCalledWith({ gremium: [], semester: '', q: '', limit: 20 });
    expect(screen.getByRole('article')).toBeInTheDocument();
  });

  it('reports a failed list', async () => {
    await setup(makeApi({ decisions: jest.fn(() => throwError(() => new Error('down'))) }));
    expect(screen.getByRole('alert')).toHaveTextContent('Die Beschlüsse konnten nicht geladen werden.');
  });

  it('localizes to English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Decisions' })).toBeInTheDocument();
    expect(screen.getByText('Passed')).toBeInTheDocument();
  });
});
