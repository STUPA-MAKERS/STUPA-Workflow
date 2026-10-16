import type { TodoEvent } from '@core/api/todos.service';
import { de, type TranslationKey } from '@core/i18n/translations';
import { TODAY, board, link, summary, tile } from '../../../testing/todo-fixtures';
import {
  NO_FILTER,
  applyMove,
  cardsOf,
  daysUntil,
  defaultBoard,
  dueInfo,
  eventText,
  filterActive,
  isoDay,
  linkLine,
  linkSub,
  linkTitle,
  longDay,
  matchesFilter,
  mentionIds,
  moveRequest,
  parseDay,
  personName,
  relativeDays,
  removeTile,
  placeTile,
  replaceTile,
  shortDay,
  sortedColumns,
  splitUrl,
  type Translate,
} from './todos.util';

/** The German catalogue with its placeholders filled. */
const t: Translate = (key: TranslationKey, params?: Record<string, string | number>) => {
  let text: string = de[key] ?? key;
  for (const [k, v] of Object.entries(params ?? {})) text = text.replaceAll(`{${k}}`, String(v));
  return text;
};

function event(kind: TodoEvent['kind'], payload: Record<string, unknown> = {}, actor = true): TodoEvent {
  return {
    id: 'e',
    kind,
    actor: actor ? { principalId: 'p-1', displayName: 'Selin' } : null,
    at: '2026-10-16T08:00:00Z',
    payload,
  };
}

describe('todos.util', () => {
  describe('days', () => {
    it('writes and reads a local calendar day', () => {
      expect(isoDay(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05');
      expect(parseDay('2026-10-16')?.getHours()).toBe(12);
      expect(parseDay('16.10.2026')).toBeNull();
      expect(parseDay(null)).toBeNull();
    });

    it('counts calendar days and gives null for a bad day', () => {
      expect(daysUntil('2026-10-17', TODAY)).toBe(1);
      expect(daysUntil('2026-10-13', TODAY)).toBe(-3);
      expect(daysUntil('x', TODAY)).toBeNull();
      expect(daysUntil(TODAY, 'x')).toBeNull();
    });

    it('writes a short day with the year only for another year', () => {
      expect(shortDay('2026-10-23', TODAY, 'de-DE')).toBe('23.10.');
      expect(shortDay('2027-01-05', TODAY, 'de-DE')).toBe('05.01.2027');
      expect(shortDay('2026-10-23', TODAY, 'en-GB')).toBe('23/10');
      expect(shortDay('bad', TODAY, 'de-DE')).toBe('bad');
    });

    it('adds the closing dot where an engine leaves it out', () => {
      const real = Intl.DateTimeFormat;
      const spy = jest
        .spyOn(Intl, 'DateTimeFormat')
        .mockImplementation(() => ({ format: () => '23.10' }) as unknown as Intl.DateTimeFormat);
      expect(shortDay('2026-10-23', TODAY, 'de-DE')).toBe('23.10.');
      spy.mockRestore();
      expect(Intl.DateTimeFormat).toBe(real);
    });

    it('writes a long day with the weekday', () => {
      expect(longDay('2026-11-03', 'de-DE')).toBe('Di, 03.11.2026');
      expect(longDay('bad', 'de-DE')).toBe('bad');
    });

    it('colours a due date: overdue, today, tomorrow, later and done', () => {
      expect(dueInfo('2026-10-14', TODAY, 'de-DE', t)).toEqual({ date: '14.10.', note: 'überfällig', tone: 'overdue' });
      expect(dueInfo(TODAY, TODAY, 'de-DE', t)).toEqual({ date: '16.10.', note: 'heute', tone: 'soon' });
      expect(dueInfo('2026-10-17', TODAY, 'de-DE', t).note).toBe('morgen');
      expect(dueInfo('2026-10-20', TODAY, 'de-DE', t)).toEqual({ date: '20.10.', note: null, tone: 'normal' });
      expect(dueInfo('2026-10-14', TODAY, 'de-DE', t, true).tone).toBe('normal');
      expect(dueInfo('bad', TODAY, 'de-DE', t).tone).toBe('normal');
    });

    it('says a day relative to today', () => {
      expect(relativeDays(TODAY, TODAY, t)).toBe('heute');
      expect(relativeDays('2026-10-17', TODAY, t)).toBe('morgen');
      expect(relativeDays('2026-10-15', TODAY, t)).toBe('gestern');
      expect(relativeDays('2026-11-04', TODAY, t)).toBe('in 19 Tagen');
      expect(relativeDays('2026-10-13', TODAY, t)).toBe('vor 3 Tagen');
      expect(relativeDays('bad', TODAY, t)).toBe('');
    });
  });

  describe('links', () => {
    it('names a person, a deleted one as such', () => {
      expect(personName({ principalId: 'p', displayName: 'Jonas' }, t)).toBe('Jonas');
      expect(personName(null, t)).toBe('Gelöschte Person');
    });

    it('titles a link, without access by its kind', () => {
      expect(linkTitle(link(), t)).toBe('Lerncafé');
      expect(linkTitle(link({ accessible: false, title: null }), t)).toBe('Antrag (kein Zugriff)');
      expect(linkTitle(link({ kind: 'ticket', title: null }), t)).toBe('Ticket (kein Zugriff)');
    });

    it('lists the facts of each kind below the title', () => {
      const sub = (l: Parameters<typeof linkSub>[0]) => linkSub(l, 'de-DE', 'de', t);
      expect(sub(link({ detail: { stateLabel: { de: 'In Prüfung', en: 'In review' } } }))).toBe('Antrag · In Prüfung');
      expect(linkSub(link({ detail: { stateLabel: { de: 'In Prüfung', en: 'In review' } } }), 'en-GB', 'en', t)).toBe(
        'Antrag · In review',
      );
      expect(sub(link({ detail: {} }))).toBe('Antrag');
      expect(sub(link({ kind: 'meeting', detail: { date: '2026-11-03' } }))).toBe('Sitzung · Di, 03.11.2026');
      expect(sub(link({ kind: 'meeting', detail: {} }))).toBe('Sitzung');
      expect(sub(link({ kind: 'agenda_item', detail: { meetingTitle: '33. Sitzung', position: 2 } }))).toBe(
        'TOP · 33. Sitzung · TOP 2',
      );
      expect(sub(link({ kind: 'agenda_item', detail: {} }))).toBe('TOP');
      // A title that already names the TOP or the number does not repeat it.
      expect(
        sub(link({ kind: 'agenda_item', title: 'TOP 2: Haushalt', detail: { meetingTitle: 'Sondersitzung', position: 2 } })),
      ).toBe('TOP · Sondersitzung');
      expect(
        sub(link({ kind: 'ticket', title: 'T-0037 Export', detail: { number: 'T-0037', status: 'in_progress' } })),
      ).toBe('Ticket · In Bearbeitung');
      expect(sub(link({ kind: 'ticket', detail: { number: 'T-0007', status: 'in_progress' } }))).toBe(
        'Ticket · T-0007 · In Bearbeitung',
      );
      expect(sub(link({ kind: 'ticket', detail: { status: 'odd' as never } }))).toBe('Ticket · Neu');
      expect(sub(link({ kind: 'ticket', detail: {} }))).toBe('Ticket');
      expect(sub(link({ kind: 'todo', detail: { boardName: 'StuPa', columnName: 'Offen' } }))).toBe(
        'To-Do · StuPa · Offen',
      );
      expect(sub(link({ kind: 'todo', detail: {} }))).toBe('To-Do');
      // Without access or detail only the kind.
      expect(sub(link({ accessible: false, detail: { stateLabel: { de: 'x' } } }))).toBe('Antrag');
      expect(sub(link({ detail: null }))).toBe('Antrag');
      expect(sub({ kind: 'todo', targetId: 'k', title: 'x', detail: { boardName: 'B' } })).toBe('To-Do · B');
    });

    it('writes the link line of a tile', () => {
      expect(linkLine(link(), TODAY, 'de-DE', t)).toBe('Antrag · Lerncafé');
      expect(linkLine(link({ accessible: false, title: null }), TODAY, 'de-DE', t)).toBe('Antrag (kein Zugriff)');
      expect(linkLine(link({ kind: 'ticket', title: 'Login', detail: { number: 'T-0002' } }), TODAY, 'de-DE', t)).toBe(
        'Ticket · T-0002 · Login',
      );
      expect(linkLine(link({ kind: 'ticket', title: 'Login', detail: null }), TODAY, 'de-DE', t)).toBe('Ticket · Login');
      expect(
        linkLine(link({ kind: 'meeting', title: 'Sondersitzung', detail: { date: '2026-11-03' } }), TODAY, 'de-DE', t),
      ).toBe('Sitzung · Sondersitzung · Di, 03.11.');
      expect(
        linkLine(link({ kind: 'agenda_item', title: 'TOP Haushalt', detail: { date: 'bad' } }), TODAY, 'de-DE', t),
      ).toBe('TOP · TOP Haushalt');
      expect(linkLine(link({ kind: 'meeting', title: 'S', detail: null }), TODAY, 'de-DE', t)).toBe('Sitzung · S');
    });

    it('splits an app url into path and query', () => {
      expect(splitUrl('/meetings/m-1?item=a-1&x=2')).toEqual({ path: '/meetings/m-1', query: { item: 'a-1', x: '2' } });
      expect(splitUrl('/applications/a-1')).toEqual({ path: '/applications/a-1', query: {} });
    });
  });

  describe('events', () => {
    const text = (e: TodoEvent) => eventText(e, 'de-DE', t);

    it('writes every kind of event', () => {
      expect(text(event('created'))).toBe('Selin hat die Karte angelegt');
      expect(text(event('created', {}, false))).toBe('STUPA hat die Karte angelegt');
      expect(text(event('moved', { fromColumnName: 'Offen', toColumnName: 'Erledigt' }))).toBe(
        'Selin hat die Karte von „Offen“ nach „Erledigt“ verschoben',
      );
      expect(text(event('moved', { fromColumnName: 3 }))).toBe('Selin hat die Karte von „“ nach „“ verschoben');
      expect(text(event('due', { to: '2026-11-03' }))).toBe('Selin hat die Fälligkeit auf Di, 03.11.2026 gesetzt');
      expect(text(event('due', { to: null }))).toBe('Selin hat die Fälligkeit entfernt');
      expect(text(event('renamed', { to: 'Neu' }))).toBe('Selin hat die Karte in „Neu“ umbenannt');
      expect(text(event('archived'))).toBe('Selin hat die Karte archiviert');
      expect(text(event('archived', {}, false))).toBe('Die Karte wurde automatisch archiviert');
      expect(text(event('restored'))).toBe('Selin hat die Karte wiederhergestellt');
    });

    it('tells taking a card from assigning somebody else', () => {
      const me = { principalId: 'p-1', displayName: 'Selin' };
      const other = { principalId: 'p-2', displayName: 'Jonas' };
      expect(text(event('assigned', { person: me, added: true }))).toBe('Selin hat die Karte übernommen');
      expect(text(event('assigned', { person: other, added: true }))).toBe('Selin hat Jonas zugewiesen');
      expect(text(event('assigned', { person: other, added: false }))).toBe('Selin hat Jonas entfernt');
      expect(text(event('assigned', { added: true }))).toBe('Selin hat Gelöschte Person zugewiesen');
      expect(text(event('assigned', { person: me, added: true }, false))).toBe('STUPA hat Selin zugewiesen');
    });

    it('names a link target, or its kind without access', () => {
      expect(text(event('linked', { linkKind: 'meeting', title: 'Sondersitzung' }))).toBe(
        'Selin hat Sitzung Sondersitzung verknüpft',
      );
      expect(text(event('unlinked', { linkKind: 'ticket' }))).toBe(
        'Selin hat die Verknüpfung mit Ticket (kein Zugriff) entfernt',
      );
      expect(text(event('linked', { title: 'X' }))).toBe('Selin hat Antrag X verknüpft');
      expect(text(event('linked', { linkKind: 'odd', title: 'X' }))).toBe('Selin hat Antrag X verknüpft');
      expect(text(event('linked', { linkKind: 'odd' }))).toBe('Selin hat Antrag (kein Zugriff) verknüpft');
    });

    it('writes the checklist actions', () => {
      expect(text(event('checklist', { action: 'added', text: 'A' }))).toBe('Selin hat „A“ zur Checkliste hinzugefügt');
      expect(text(event('checklist', { action: 'done', text: 'A' }))).toBe('Selin hat „A“ erledigt');
      expect(text(event('checklist', { action: 'undone', text: 'A' }))).toBe('Selin hat „A“ wieder geöffnet');
      expect(text(event('checklist', { action: 'removed', text: 'A' }))).toBe('Selin hat „A“ aus der Checkliste gelöscht');
      expect(text(event('checklist', { action: 'renamed', text: 'B' }))).toBe('Selin hat einen Punkt in „B“ umbenannt');
      expect(text(event('checklist', { action: 'odd', text: 'A' }))).toBe('Selin hat „A“ zur Checkliste hinzugefügt');
    });
  });

  describe('filters', () => {
    const labels = new Map(board().labels.map((l) => [l.id, l]));
    const ctx = { today: TODAY, mine: new Set(['k-1']), labels };
    const card = tile({
      id: 'k-1',
      title: 'Raum buchen',
      dueDate: '2026-10-14',
      labelIds: ['l-1'],
      assignees: [{ principalId: 'p-1', displayName: 'Selin' }, { principalId: 'p-2', displayName: null }],
      primaryLink: link({ title: 'Lerncafé' }),
    });
    const bare = tile({ id: 'k-2', title: 'Bus' });

    it('knows an active filter', () => {
      expect(filterActive(NO_FILTER)).toBe(false);
      expect(filterActive({ ...NO_FILTER, q: '  ' })).toBe(false);
      expect(filterActive({ ...NO_FILTER, q: 'x' })).toBe(true);
      expect(filterActive({ ...NO_FILTER, assignee: 'me' })).toBe(true);
      expect(filterActive({ ...NO_FILTER, labels: ['l-1'] })).toBe(true);
      expect(filterActive({ ...NO_FILTER, due: 'week' })).toBe(true);
    });

    it('filters by assignee', () => {
      const m = (assignee: string, c = card) => matchesFilter(c, { ...NO_FILTER, assignee }, ctx);
      expect(m('')).toBe(true);
      expect(m('me')).toBe(true);
      expect(m('me', bare)).toBe(false);
      expect(m('none')).toBe(false);
      expect(m('none', bare)).toBe(true);
      expect(m('p-2')).toBe(true);
      expect(m('p-9')).toBe(false);
    });

    it('filters by labels (any of them)', () => {
      expect(matchesFilter(card, { ...NO_FILTER, labels: ['l-2', 'l-1'] }, ctx)).toBe(true);
      expect(matchesFilter(card, { ...NO_FILTER, labels: ['l-2'] }, ctx)).toBe(false);
    });

    it('filters by due date', () => {
      const m = (due: '' | 'overdue' | 'week' | 'none', dueDate: string | null) =>
        matchesFilter(tile({ dueDate }), { ...NO_FILTER, due }, ctx);
      expect(m('overdue', '2026-10-14')).toBe(true);
      expect(m('overdue', TODAY)).toBe(false);
      expect(m('overdue', null)).toBe(false);
      expect(m('week', '2026-10-23')).toBe(true);
      expect(m('week', '2026-10-24')).toBe(false);
      expect(m('week', '2026-10-01')).toBe(true);
      expect(m('week', null)).toBe(false);
      expect(m('none', null)).toBe(true);
      expect(m('none', TODAY)).toBe(false);
    });

    it('searches the title, the link, the labels and the people', () => {
      const q = (text: string, c = card) => matchesFilter(c, { ...NO_FILTER, q: text }, ctx);
      expect(q('raum')).toBe(true);
      expect(q('LERN')).toBe(true);
      expect(q('haushalt')).toBe(true);
      expect(q('selin')).toBe(true);
      expect(q('nichts')).toBe(false);
      expect(q('bus', bare)).toBe(true);
      expect(matchesFilter(tile({ labelIds: ['l-x'] }), { ...NO_FILTER, q: 'proto' }, ctx)).toBe(true);
    });
  });

  describe('board', () => {
    it('sorts columns and lists the cards of one', () => {
      const b = board();
      expect(sortedColumns([...b.columns].reverse()).map((c) => c.id)).toEqual(['c-1', 'c-2', 'c-3', 'c-4']);
      expect(cardsOf(b, 'c-1').map((c) => c.id)).toEqual(['k-1', 'k-2']);
    });

    it('names one neighbour of a move', () => {
      const list = [tile({ id: 'a' }), tile({ id: 'b' })];
      expect(moveRequest(list, 1, 'c')).toEqual({ columnId: 'c', afterId: 'a' });
      expect(moveRequest(list, 0, 'c')).toEqual({ columnId: 'c', beforeId: 'b' });
      expect(moveRequest([tile({ id: 'a' })], 0, 'c')).toEqual({ columnId: 'c' });
    });

    it('moves a card at once, after or before a neighbour or to the end', () => {
      const b = board();
      const ids = (x: ReturnType<typeof board>) => x.cards.map((c) => `${c.id}@${c.columnId}`);
      expect(ids(applyMove(b, 'k-3', { columnId: 'c-1', afterId: 'k-1' }))).toEqual(['k-1@c-1', 'k-3@c-1', 'k-2@c-1']);
      expect(ids(applyMove(b, 'k-3', { columnId: 'c-1', beforeId: 'k-1' }))).toEqual(['k-3@c-1', 'k-1@c-1', 'k-2@c-1']);
      expect(ids(applyMove(b, 'k-1', { columnId: 'c-1' }))).toEqual(['k-2@c-1', 'k-1@c-1', 'k-3@c-4']);
      // An unknown neighbour and an empty column put it at the end.
      expect(ids(applyMove(b, 'k-1', { columnId: 'c-2', afterId: 'nope' }))).toEqual(['k-2@c-1', 'k-3@c-4', 'k-1@c-2']);
      const moved = applyMove(b, 'k-1', { columnId: 'c-2' });
      expect(moved.columns.find((c) => c.id === 'c-2')?.cardCount).toBe(1);
      expect(moved.columns.find((c) => c.id === 'c-1')?.cardCount).toBe(1);
      expect(applyMove(b, 'nope', { columnId: 'c-2' })).toBe(b);
    });

    it('puts a server tile in and takes a card out', () => {
      const b = board();
      const changed = replaceTile(b, tile({ id: 'k-1', title: 'Neu', columnId: 'c-2' }));
      expect(changed.cards[0].title).toBe('Neu');
      expect(changed.columns[1].cardCount).toBe(1);
      const added = replaceTile(b, tile({ id: 'k-9', columnId: 'c-3' }));
      expect(added.cards).toHaveLength(4);
      expect(added.columns[2].cardCount).toBe(1);
      const removed = removeTile(b, 'k-1');
      expect(removed.cards.map((c) => c.id)).toEqual(['k-2', 'k-3']);
      expect(removed.columns[0].cardCount).toBe(1);
    });

    it('places a tile that changed its column by its rank, else in place', () => {
      const b = board({ cards: [
        tile({ id: 'k-1', columnId: 'c-1', rank: 'a' }),
        tile({ id: 'k-2', columnId: 'c-4', rank: 'b' }),
        tile({ id: 'k-3', columnId: 'c-4', rank: 'd' }),
      ] });
      const order = (x: typeof b) => x.cards.map((c) => `${c.id}@${c.columnId}`);
      expect(order(placeTile(b, tile({ id: 'k-1', columnId: 'c-4', rank: 'c' })))).toEqual(['k-2@c-4', 'k-1@c-4', 'k-3@c-4']);
      expect(order(placeTile(b, tile({ id: 'k-1', columnId: 'c-4', rank: 'z' })))).toEqual(['k-2@c-4', 'k-3@c-4', 'k-1@c-4']);
      const renamed = placeTile(b, tile({ id: 'k-3', columnId: 'c-4', rank: 'd', title: 'Neu' }));
      expect(order(renamed)).toEqual(order(b));
      expect(renamed.cards[2].title).toBe('Neu');
      expect(order(placeTile(b, tile({ id: 'k-9', columnId: 'c-1' })))).toEqual(['k-1@c-1', 'k-2@c-4', 'k-3@c-4', 'k-9@c-1']);
    });

    it('opens the first own gremium board, else the personal one, else any', () => {
      const personal = summary({ id: 'p', kind: 'personal' });
      const team = summary({ id: 't', kind: 'team' });
      const gremium = summary({ id: 'g', kind: 'gremium', gremiumId: 'gr-1' });
      expect(defaultBoard([personal, team, gremium], ['gr-1'])?.id).toBe('g');
      expect(defaultBoard([team, personal])?.id).toBe('p');
      expect(defaultBoard([team, gremium])?.id).toBe('g');
      expect(defaultBoard([team])?.id).toBe('t');
      expect(defaultBoard([])).toBeNull();
    });

    it('skips the gremium boards an admin sees but does not belong to', () => {
      const personal = summary({ id: 'p', kind: 'personal' });
      const asta = summary({ id: 'a', kind: 'gremium', gremiumId: 'gr-asta' });
      const fs = summary({ id: 'f', kind: 'gremium', gremiumId: 'gr-fs' });
      const stupa = summary({ id: 's', kind: 'gremium', gremiumId: 'gr-stupa' });
      expect(defaultBoard([personal, asta, fs, stupa], ['gr-stupa'])?.id).toBe('s');
      expect(defaultBoard([personal, asta, fs, stupa], [])?.id).toBe('p');
    });

    it('finds the people a comment mentions, each once', () => {
      const members = [
        { principalId: 'p-1', displayName: 'Selin Yıldız' },
        { principalId: 'p-2', displayName: 'Jonas' },
        { principalId: 'p-1', displayName: 'Selin Yıldız' },
        { principalId: 'p-3', displayName: null },
      ];
      expect(mentionIds('Hallo @Selin Yıldız und @Jonas', members)).toEqual(['p-1', 'p-2']);
      expect(mentionIds('Hallo', members)).toEqual([]);
    });
  });
});
