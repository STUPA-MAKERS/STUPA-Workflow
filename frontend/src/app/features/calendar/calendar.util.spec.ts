import type { CalendarEntry } from '@core/api/calendar.service';
import { weekOf } from './calendar-grid.util';
import {
  VIEW_STORAGE_KEY,
  allDayOf,
  answerKey,
  answerKind,
  dayBlocks,
  dayList,
  daysBetween,
  emptyForm,
  entryIcon,
  entryLink,
  entryOf,
  entryTime,
  filterKind,
  formError,
  hasEnded,
  hourRange,
  hoursOf,
  kindKey,
  laneCount,
  mergeEntries,
  monthRows,
  onDay,
  readStoredView,
  singleDay,
  spanText,
  storeView,
  toInput,
  visibleEntries,
  weekBars,
} from './calendar.util';

function entry(id: string, over: Partial<CalendarEntry> = {}): CalendarEntry {
  return {
    kind: 'appointment',
    id,
    title: `Eintrag ${id}`,
    startsOn: '2026-11-11',
    endsOn: '2026-11-11',
    startTime: null,
    endTime: null,
    place: null,
    source: null,
    gremiumIds: [],
    mine: false,
    myAnswer: null,
    ...over,
  };
}

const WEEK = weekOf('2026-11-11', new Date(2026, 10, 11));

describe('calendar.util', () => {
  describe('stored view', () => {
    afterEach(() => {
      localStorage.clear();
      jest.restoreAllMocks();
    });

    it('keeps the view per browser, the month by default', () => {
      expect(readStoredView()).toBe('month');
      storeView('week');
      expect(localStorage.getItem(VIEW_STORAGE_KEY)).toBe('week');
      expect(readStoredView()).toBe('week');
      localStorage.setItem(VIEW_STORAGE_KEY, 'other');
      expect(readStoredView()).toBe('month');
    });

    it('falls back to the month when the storage is blocked', () => {
      jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      expect(readStoredView()).toBe('month');
      expect(() => storeView('week')).not.toThrow();
    });
  });

  describe('kinds and filters', () => {
    /** § 000737: the Kalender has no kind "Veranstaltung". */
    it('counts an Event to the Termine', () => {
      expect(filterKind('event')).toBe('appointment');
      expect(filterKind('card')).toBe('card');
      expect(kindKey('event')).toBe('calendar.kind.appointment');
      expect(kindKey('meeting')).toBe('calendar.kind.meeting');
      expect(entryIcon('event')).toBe(entryIcon('appointment'));
      expect(entryIcon('meeting')).toBe('users');
      expect([filterKind('external'), kindKey('external'), entryIcon('external')]).toEqual([
        'external',
        'calendar.kind.external',
        'globe',
      ]);
    });

    /** § 000713: an entry without a Gremium shows only when no Gremium is picked. */
    it('filters by kind and by Gremium', () => {
      const list = [
        entry('private'),
        entry('stupa', { gremiumIds: ['g-1'] }),
        entry('event', { kind: 'event' }),
        entry('card', { kind: 'card', gremiumIds: ['g-1'] }),
        entry('meeting', { kind: 'meeting', gremiumIds: ['g-2'] }),
      ];
      const ids = (kinds: string[], g: string) => visibleEntries(list, kinds, g).map((e) => e.id);
      expect(ids([], '')).toEqual(['private', 'stupa', 'event', 'card', 'meeting']);
      expect(ids([], 'g-1')).toEqual(['stupa', 'card']);
      expect(ids(['appointment'], '')).toEqual(['private', 'stupa', 'event']);
      expect(ids(['card', 'meeting'], 'g-2')).toEqual(['meeting']);
    });

    it('opens a meeting and a card on their page, and a Termin in the dialog', () => {
      expect(entryLink(entry('m', { kind: 'meeting' }))).toEqual({ commands: ['/meetings', 'm'] });
      expect(entryLink(entry('c', { kind: 'card' }))).toEqual({ commands: ['/todos'], queryParams: { card: 'c' } });
      expect(entryLink(entry('e', { kind: 'event' }))).toEqual({ commands: ['/todos'], queryParams: { card: 'e' } });
      expect(entryLink(entry('a'))).toBeNull();
      expect(entryLink(entry('x', { kind: 'external' }))).toBeNull();
    });
  });

  describe('days and bars', () => {
    const span = entry('span', { startsOn: '2026-11-10', endsOn: '2026-11-12' });
    const one = entry('one');

    it('finds the entries of a day', () => {
      expect(onDay([span, one], '2026-11-11').map((e) => e.id)).toEqual(['span', 'one']);
      expect(onDay([span, one], '2026-11-12').map((e) => e.id)).toEqual(['span']);
      expect(singleDay([span, one], '2026-11-11').map((e) => e.id)).toEqual(['one']);
    });

    /** § 000726: an entry over several days is one bar in the grid and one row at each day. */
    it('makes one bar of a three-day entry and a row at each of its days', () => {
      const bars = weekBars([span, one], WEEK);
      expect(bars).toEqual([{ entry: span, from: 2, to: 5, lane: 0, openStart: false, openEnd: false }]);
      expect(dayList([span], daysBetween('2026-11-09', '2026-11-15')).map((d) => d.iso)).toEqual([
        '2026-11-10',
        '2026-11-11',
        '2026-11-12',
      ]);
    });

    it('cuts a bar at the week and gives overlapping bars their own lanes', () => {
      const before = entry('before', { startsOn: '2026-11-05', endsOn: '2026-11-10' });
      const after = entry('after', { startsOn: '2026-11-14', endsOn: '2026-11-20' });
      const over = entry('over', { startsOn: '2026-11-10', endsOn: '2026-11-11' });
      const away = entry('away', { startsOn: '2026-11-20', endsOn: '2026-11-22' });
      const bars = weekBars([before, over, after, away], WEEK);
      expect(bars.map((b) => [b.entry.id, b.from, b.to, b.lane, b.openStart, b.openEnd])).toEqual([
        ['before', 1, 3, 0, true, false],
        ['over', 2, 4, 1, false, false],
        ['after', 6, 8, 0, false, true],
      ]);
      expect(laneCount(bars)).toBe(2);
      expect(laneCount([])).toBe(0);
    });

    it('gives a cell of the month the entries that fit below the bars', () => {
      const many = ['a', 'b', 'c'].map((id) => entry(id));
      const [free] = monthRows(many, [WEEK]);
      expect(free.key).toBe('2026-11-09');
      expect(free.lanes).toBe(0);
      expect(free.cells[2]).toMatchObject({ shown: many.slice(0, 2), more: 1, count: 3 });
      expect(free.cells[0]).toMatchObject({ shown: [], more: 0, count: 0 });
      const [barred] = monthRows([...many, span], [WEEK]);
      expect(barred.lanes).toBe(1);
      expect(barred.cells[2]).toMatchObject({ shown: many.slice(0, 1), more: 2, count: 4 });
    });

    it('lists the days of a range', () => {
      expect(daysBetween('2026-10-31', '2026-11-02')).toEqual(['2026-10-31', '2026-11-01', '2026-11-02']);
      expect(daysBetween('2026-11-02', '2026-11-01')).toEqual([]);
    });

    it('merges two reads without doubles, in the order of the day', () => {
      const late = entry('late', { startTime: '18:00:00' });
      const early = entry('early', { startTime: '09:00:00' });
      const next = entry('next', { startsOn: '2026-11-12', endsOn: '2026-11-12' });
      const b = entry('b', { title: 'B' });
      const a = entry('a', { title: 'A' });
      const merged = mergeEntries([late, next, b], [early, a, { ...late, title: 'Neu' }]);
      expect(merged.map((e) => e.id)).toEqual(['a', 'b', 'early', 'late', 'next']);
      expect(merged[3].title).toBe('Neu');
    });
  });

  describe('week view', () => {
    const timed = entry('timed', { startTime: '14:00:00', endTime: '15:30:00' });

    it('reads a clock time as hours', () => {
      expect(hoursOf('14:30:00')).toBe(14.5);
      expect(hoursOf('08:15')).toBe(8.25);
    });

    /** § 000728: an all-day entry, an entry over days and a due card are above the hours. */
    it('puts untimed entries and entries over several days above the hours', () => {
      const card = entry('card', { kind: 'card' });
      const span = entry('span', { startsOn: '2026-11-10', endsOn: '2026-11-12', startTime: '09:00:00' });
      expect(allDayOf([timed, card, span], '2026-11-11').map((e) => e.id)).toEqual(['card', 'span']);
      expect(dayBlocks([timed, card, span], '2026-11-11', 8).map((b) => b.entry.id)).toEqual(['timed']);
    });

    it('places a block at its time', () => {
      const [block] = dayBlocks([timed], '2026-11-11', 8);
      expect(block).toMatchObject({ top: 6, height: 1.5, left: 0, width: 100, short: false, lines: 3 });
    });

    it('gives a short entry the least height and an open end one hour', () => {
      const short = entry('short', { startTime: '09:00:00', endTime: '09:10:00' });
      const open = entry('open', { startTime: '11:00:00' });
      const [a, b] = dayBlocks([open, short], '2026-11-11', 8);
      expect(a).toMatchObject({ top: 1, height: 0.4, short: true, lines: 1 });
      expect(b).toMatchObject({ top: 3, height: 1, short: false });
    });

    it('shares the width of the day between entries that overlap', () => {
      const other = entry('other', { startTime: '14:30:00', endTime: '14:45:00' });
      const later = entry('later', { startTime: '16:00:00', endTime: '17:00:00' });
      const blocks = dayBlocks([other, later, timed], '2026-11-11', 8);
      expect(blocks.map((b) => [b.entry.id, b.left, b.width])).toEqual([
        ['timed', 0, 50],
        ['other', 50, 50],
        ['later', 0, 100],
      ]);
    });

    it('widens the hour axis for an early or a late entry', () => {
      expect(hourRange([])).toEqual({ from: 8, to: 21 });
      expect(hourRange([timed])).toEqual({ from: 8, to: 21 });
      const early = entry('early', { startTime: '06:30:00', endTime: '07:00:00' });
      const late = entry('late', { startTime: '22:15:00', endTime: '23:30:00' });
      const open = entry('open', { startTime: '21:30:00' });
      expect(hourRange([early, late])).toEqual({ from: 6, to: 24 });
      expect(hourRange([open])).toEqual({ from: 8, to: 23 });
    });
  });

  describe('texts', () => {
    it('writes the time of an entry', () => {
      expect(entryTime(entry('a', { startTime: '14:00:00', endTime: '15:30:00' }), 'de-DE')).toBe('14:00 – 15:30');
      expect(entryTime(entry('a', { startTime: '14:00:00' }), 'de-DE')).toBe('14:00');
      expect(entryTime(entry('a'), 'de-DE')).toBe('');
      expect(entryTime(entry('a', { startsOn: '2026-11-17', endsOn: '2026-11-19' }), 'de-DE')).toBe('17.11. – 19.11.');
    });

    it('writes the span of a Termin', () => {
      const day = { startsOn: '2026-11-11', endsOn: '2026-11-11', startTime: null, endTime: null };
      expect(spanText(day, 'de-DE')).toBe('Mi, 11.11.2026');
      expect(spanText({ ...day, startTime: '14:00:00', endTime: '15:30:00' }, 'de-DE')).toBe(
        'Mi, 11.11.2026 · 14:00 – 15:30',
      );
      expect(spanText({ ...day, endsOn: '2026-11-13' }, 'de-DE')).toBe('Mi, 11.11.2026 – Fr, 13.11.2026');
      expect(spanText({ ...day, endsOn: '2026-11-13', startTime: '09:00:00', endTime: '16:00:00' }, 'de-DE')).toBe(
        'Mi, 11.11.2026, 09:00 – Fr, 13.11.2026, 16:00',
      );
    });

    it('tells when a Termin is over', () => {
      const now = new Date(2026, 10, 11, 15, 0);
      const day = { startsOn: '2026-11-11', endsOn: '2026-11-11', startTime: null, endTime: null };
      expect(hasEnded(day, now)).toBe(false);
      expect(hasEnded({ ...day, startTime: '13:00:00', endTime: '15:00:00' }, now)).toBe(true);
      expect(hasEnded({ ...day, startTime: '13:00:00', endTime: '15:30:00' }, now)).toBe(false);
      expect(hasEnded({ ...day, startsOn: '2026-11-10', endsOn: '2026-11-10' }, now)).toBe(true);
      expect(hasEnded({ ...day, endsOn: '2026-11-12' }, now)).toBe(false);
    });

    it('names and colours an answer', () => {
      expect(answerKey('accept')).toBe('calendar.answer.accept');
      expect([answerKind('accept'), answerKind('tentative'), answerKind('decline')]).toEqual(['accent', 'warn', 'muted']);
    });

    it('makes the entry of a saved Termin', () => {
      const a = {
        id: 'a-1',
        title: 'Klausur',
        startsOn: '2026-11-17',
        endsOn: '2026-11-19',
        startTime: null,
        endTime: null,
        place: 'Tübingen',
      };
      expect(entryOf(a, [{ id: 'g-1', name: 'StuPa' }], 'accept')).toEqual(
        entry('a-1', {
          title: 'Klausur',
          startsOn: '2026-11-17',
          endsOn: '2026-11-19',
          place: 'Tübingen',
          source: 'StuPa',
          gremiumIds: ['g-1'],
          mine: true,
          myAnswer: 'accept',
        }),
      );
      expect(entryOf(a, [], null).source).toBeNull();
    });
  });

  describe('form', () => {
    const form = { ...emptyForm('2026-11-11'), title: ' Klausur ' };

    it('starts all-day on the picked day', () => {
      expect(emptyForm('2026-11-11')).toMatchObject({ allDay: true, startsOn: '2026-11-11', endsOn: '2026-11-11' });
    });

    it('refuses a form without a title, with an end before the start or without times', () => {
      expect(formError(form)).toBeNull();
      expect(formError({ ...form, title: '  ' })).toBe('title');
      expect(formError({ ...form, endsOn: '2026-11-10' })).toBe('days');
      expect(formError({ ...form, startsOn: '' })).toBe('days');
      expect(formError({ ...form, endsOn: '' })).toBe('days');
      expect(formError({ ...form, allDay: false })).toBeNull();
      expect(formError({ ...form, allDay: false, endTime: '' })).toBe('times');
      expect(formError({ ...form, allDay: false, startTime: '' })).toBe('times');
      expect(formError({ ...form, allDay: false, endTime: '09:00' })).toBe('times');
      expect(formError({ ...form, allDay: false, endsOn: '2026-11-12', endTime: '08:00' })).toBeNull();
    });

    it('builds the request body', () => {
      expect(toInput(form, ['g-1'], ['p-1'])).toEqual({
        title: 'Klausur',
        startsOn: '2026-11-11',
        endsOn: '2026-11-11',
        startTime: null,
        endTime: null,
        place: null,
        description: null,
        forAll: false,
        public: false,
        gremiumIds: ['g-1'],
        principalIds: ['p-1'],
      });
      expect(
        toInput({ ...form, allDay: false, place: ' Aula ', description: ' Text ', forAll: true }, [], []),
      ).toMatchObject({ startTime: '09:00:00', endTime: '10:00:00', place: 'Aula', description: 'Text', forAll: true });
    });
  });
});
