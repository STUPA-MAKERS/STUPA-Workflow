import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { GremienApiService, type GremiumDecision } from '@core/api/gremien.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { GREMIEN_TEST_NOW, decision, gremienApiMock } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { GREMIEN_NOW } from '../gremien.store';
import { GremiumDecisionsComponent } from './gremium-decisions.component';

const ITEMS: GremiumDecision[] = [
  decision(),
  decision({
    id: 'v-2',
    question: 'Genehmigung der Tagesordnung',
    kind: 'motion',
    applicationId: null,
    applicationTitle: null,
    amount: null,
    result: 'tie',
  }),
  decision({
    id: 'v-3',
    question: 'Wahl der Sitzungsleitung',
    kind: 'election',
    applicationId: null,
    applicationTitle: null,
    amount: null,
    secret: true,
    majorityRule: null,
    counts: null,
    ballots: 25,
    result: 'elected',
    elected: ['Jonas Albrecht', 'Mia Roth'],
    meetingId: 'm-2',
    meetingTitle: '32. Sitzung',
    meetingDate: '2026-09-29',
  }),
  decision({
    id: 'v-4',
    question: null,
    applicationTitle: 'Sommerkino',
    amount: null,
    counts: null,
    ballots: 1,
    result: null,
    meetingId: null,
    meetingTitle: null,
    meetingDate: null,
    closedAt: '2026-09-02T10:00:00Z',
  }),
  decision({
    id: 'v-5',
    question: null,
    applicationTitle: null,
    result: 'rejected',
    meetingId: null,
    meetingTitle: null,
    meetingDate: null,
    closedAt: null,
  }),
];

async function setup(opts: { api?: ReturnType<typeof gremienApiMock>; phone?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.phone ? [MEDIA.phone] : []));
  const api = opts.api ?? gremienApiMock({ decisions: jest.fn(() => of({ items: ITEMS, nextCursor: null })) });
  const view = await render(GremiumDecisionsComponent, {
    inputs: { gremiumId: 'g-1' },
    providers: [
      provideRouter([]),
      { provide: GremienApiService, useValue: api },
      { provide: GREMIEN_NOW, useValue: GREMIEN_TEST_NOW },
    ],
  });
  return { ...view, api, restore, cmp: view.fixture.componentInstance };
}

const NO_FILTER = { q: null, result: null, kind: null, since: null };

describe('GremiumDecisionsComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('groups the votes by month and meeting, with kind, votes, majority and result', async () => {
    const view = await setup();
    restore = view.restore;
    expect(view.api.decisions).toHaveBeenCalledTimes(1);
    expect(view.api.decisions).toHaveBeenCalledWith('g-1', NO_FILTER);
    const groups = view.cmp.groups();
    expect(groups.map((g) => [g.label, g.meeting])).toEqual([
      ['Oktober 2026', '33. Sitzung · 06.10.'],
      ['September 2026', '32. Sitzung · 29.09.'],
      ['September 2026', 'Ohne Sitzung'],
      ['Ohne Datum', 'Ohne Sitzung'],
    ]);
    const [app, motion] = groups[0].rows;
    expect(app.parts.map((p) => p.replace(/\s/g, ' '))).toEqual(['Antrag · 2.890,00 €', 'Ja 19 · Nein 4 · Enth. 2', 'Einfache Mehrheit']);
    expect(app.status.key).toBe('vote.result.passed');
    expect(motion.parts[0]).toBe('Beschluss');
    expect(motion.status.key).toBe('vote.result.rejected');
    const election = groups[1].rows[0];
    expect(election.parts).toEqual(['Wahl', 'geheim', '25 Stimmen']);
    expect(election.status.key).toBe('election.status.elected');
    expect(election.elected).toBe('Jonas Albrecht, Mia Roth');
    const loose = groups[2].rows[0];
    expect(loose.title).toBe('Sommerkino');
    expect(loose.parts).toEqual(['Antrag', '1 Stimme', 'Einfache Mehrheit']);
    expect(loose.status.key).toBe('gremien.decisions.noResult');
    expect(groups[3].rows[0].title).toBe('Abstimmung ohne Titel');

    expect(screen.getByText('Gewählt: Jonas Albrecht, Mia Roth')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Lastenrad für das Fachschaftsbüro/ }).getAttribute('href')).toBe('/voting/v-1');
    expect(screen.queryByRole('button', { name: 'Weitere laden' })).toBeNull();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('sends the chips and the search to the server', async () => {
    const view = await setup();
    restore = view.restore;
    const last = () => view.api.decisions.mock.calls.at(-1);

    view.cmp.setResult('passed');
    view.fixture.detectChanges();
    expect(last()).toEqual(['g-1', { ...NO_FILTER, result: 'passed' }]);
    expect(view.cmp.resultText()).toBe('Ergebnis: Angenommen');

    view.cmp.setKind('election');
    view.fixture.detectChanges();
    expect(last()).toEqual(['g-1', { ...NO_FILTER, result: 'passed', kind: 'election' }]);
    expect(view.cmp.kindText()).toBe('Art: Wahl');

    view.cmp.setResult('');
    view.cmp.setKind('');
    view.cmp.setSince('last3');
    view.fixture.detectChanges();
    expect(last()).toEqual(['g-1', { ...NO_FILTER, since: '2026-08-01' }]);
    expect(view.cmp.sinceText()).toBe('Zeitraum: Letzte 3 Monate');
    view.cmp.setSince('last12');
    view.fixture.detectChanges();
    expect(last()).toEqual(['g-1', { ...NO_FILTER, since: '2025-11-01' }]);
    view.cmp.setSince('odd');
    expect(view.cmp.sinceText()).toBe('Zeitraum: ');
    view.cmp.setSince('');
    view.fixture.detectChanges();

    view.cmp.search.set('rad');
    view.cmp.search.flush();
    expect(last()).toEqual(['g-1', { ...NO_FILTER, q: 'rad' }]);
    expect(view.cmp.resultText()).toBeNull();
    expect(view.cmp.kindText()).toBeNull();
  });

  it('says when nothing matches, and shows the empty state without votes', async () => {
    const decisions = jest.fn(() => of({ items: [] as GremiumDecision[], nextCursor: null }));
    const view = await setup({ api: gremienApiMock({ decisions }) });
    restore = view.restore;
    expect(screen.getByText('Noch keine Beschlüsse')).toBeTruthy();
    view.cmp.search.set('x');
    view.cmp.search.flush();
    view.fixture.detectChanges();
    expect(view.cmp.filterActive()).toBe(true);
    expect(screen.getByText('Kein Beschluss passt zur Suche oder zu den Filtern.')).toBeTruthy();
  });

  it('loads the next page behind the rows, and reports a failed one', async () => {
    const decisions = jest.fn((_id: string, q: { cursor?: string | null }) =>
      q.cursor === 'c2'
        ? of({ items: [decision({ id: 'v-9', question: 'Später' })], nextCursor: 'c3' })
        : q.cursor === 'c3'
          ? throwError(() => new Error('x'))
          : of({ items: [decision()], nextCursor: 'c2' }),
    );
    const view = await setup({ api: gremienApiMock({ decisions }) });
    restore = view.restore;
    screen.getByRole('button', { name: 'Weitere laden' }).click();
    view.fixture.detectChanges();
    expect(decisions).toHaveBeenLastCalledWith('g-1', { ...NO_FILTER, cursor: 'c2' });
    expect(view.cmp.items().map((d) => d.id)).toEqual(['v-1', 'v-9']);
    screen.getByRole('button', { name: 'Weitere laden' }).click();
    view.fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Weitere Beschlüsse konnten nicht geladen werden.');
    expect(view.cmp.items()).toHaveLength(2);
  });

  it('loads nothing more without a cursor or while a page loads', async () => {
    const view = await setup();
    restore = view.restore;
    view.cmp.loadMore();
    expect(view.api.decisions).toHaveBeenCalledTimes(1);
    view.cmp.nextCursor.set('c2');
    view.cmp.loadingMore.set(true);
    view.cmp.loadMore();
    expect(view.api.decisions).toHaveBeenCalledTimes(1);
  });

  it('reports a failed read and reads again', async () => {
    const decisions = jest.fn((): ReturnType<GremienApiService['decisions']> => throwError(() => new Error('x')));
    const view = await setup({ api: gremienApiMock({ decisions }) });
    restore = view.restore;
    expect(screen.getByRole('alert')).toHaveTextContent('Die Beschlüsse konnten nicht geladen werden.');
    decisions.mockReturnValue(of({ items: ITEMS, nextCursor: null }));
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    view.fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(view.cmp.groups()).toHaveLength(4);
  });

  it('puts the result first in the sub line on a phone, without the range chip', async () => {
    const view = await setup({ phone: true });
    restore = view.restore;
    expect(screen.queryByText('Gewählt: Jonas Albrecht, Mia Roth')).toBeNull();
    const link = screen.getByRole('link', { name: /Wahl der Sitzungsleitung/ });
    expect(link.closest('app-list-item')?.textContent).toContain('Gewählt');
    expect(view.container.querySelectorAll('app-filter-select')).toHaveLength(2);
  });
});
