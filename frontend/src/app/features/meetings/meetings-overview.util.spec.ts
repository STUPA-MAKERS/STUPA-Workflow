import type { Attendance, Meeting, MeetingVote } from '@core/api/models';
import { de } from '@core/i18n/translations';
import {
  VIEW_STORAGE_KEY,
  agendaProgress,
  attendanceCounts,
  byStart,
  gridRange,
  isoDay,
  matchesQuery,
  meetingsByDay,
  monthGrid,
  monthLabel,
  monthOf,
  openVoteOf,
  overviewGroups,
  parseDay,
  readStoredView,
  shiftMonth,
  storeView,
  topsLabel,
  weekdayNames,
  weekdayShort,
} from './meetings-overview.util';

function meeting(id: string, over: Partial<Meeting> = {}): Meeting {
  return {
    id,
    title: `Sitzung ${id}`,
    date: '2026-10-13',
    startTime: '18:00',
    endTime: null,
    status: 'planned',
    activeApplicationId: null,
    currentAgendaItemId: null,
    gremiumId: 'g-1',
    gremiumName: 'Studierendenparlament',
    votes: [],
    protocolId: null,
    createdAt: '2026-09-01T00:00:00Z',
    protokollantId: null,
    protokollantName: null,
    isProtokollant: false,
    canControl: false,
    canManage: false,
    canWrite: false,
    canManageVotes: false,
    canVote: false,
    canFinalize: false,
    keeperPeriods: [],
    plannedHandover: null,
    ...over,
  };
}

const t = (key: keyof typeof de, params?: Record<string, string | number>): string =>
  Object.entries(params ?? {}).reduce<string>(
    (text, [k, v]) => text.replace(`{${k}}`, String(v)),
    de[key],
  );

describe('meetings-overview.util', () => {
  describe('stored view', () => {
    afterEach(() => {
      localStorage.clear();
      jest.restoreAllMocks();
    });

    it('reads and keeps the view per browser, the list by default', () => {
      expect(readStoredView()).toBe('list');
      storeView('calendar');
      expect(localStorage.getItem(VIEW_STORAGE_KEY)).toBe('calendar');
      expect(readStoredView()).toBe('calendar');
      localStorage.setItem(VIEW_STORAGE_KEY, 'other');
      expect(readStoredView()).toBe('list');
    });

    it('falls back to the list when the storage is blocked', () => {
      jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      expect(readStoredView()).toBe('list');
      expect(() => storeView('calendar')).not.toThrow();
    });
  });

  describe('month grid', () => {
    it('runs from the Monday before the first to the Sunday after the last day', () => {
      const weeks = monthGrid({ year: 2026, month: 8 }, new Date(2026, 8, 29, 18, 50));
      expect(weeks).toHaveLength(5);
      expect(weeks.every((w) => w.length === 7)).toBe(true);
      expect(gridRange(weeks)).toEqual({ from: '2026-08-31', to: '2026-10-04' });
      expect(weeks[0][0]).toEqual({ iso: '2026-08-31', day: 31, inMonth: false, isToday: false });
      expect(weeks[4][1]).toEqual({ iso: '2026-09-29', day: 29, inMonth: true, isToday: true });
    });

    it('has four weeks for a February from Monday to Sunday', () => {
      const weeks = monthGrid({ year: 2027, month: 1 }, new Date(2026, 0, 1));
      expect(weeks).toHaveLength(4);
      expect(gridRange(weeks)).toEqual({ from: '2027-02-01', to: '2027-02-28' });
      expect(weeks.flat().every((d) => d.inMonth && !d.isToday)).toBe(true);
    });

    it('moves months across the year', () => {
      expect(shiftMonth({ year: 2026, month: 11 }, 1)).toEqual({ year: 2027, month: 0 });
      expect(shiftMonth({ year: 2026, month: 0 }, -1)).toEqual({ year: 2025, month: 11 });
      expect(monthOf(parseDay('2026-10-13'))).toEqual({ year: 2026, month: 9 });
      expect(isoDay(new Date(2026, 0, 5))).toBe('2026-01-05');
    });

    it('names the month and the weekdays', () => {
      expect(monthLabel({ year: 2026, month: 9 }, 'de')).toBe('Oktober 2026');
      expect(monthLabel({ year: 2026, month: 9 }, 'en')).toBe('October 2026');
      expect(weekdayNames('de')).toEqual(['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']);
      expect(weekdayNames('en')[0]).toBe('Mon');
      expect(weekdayShort('2026-10-13', 'de')).toBe('Di');
    });
  });

  describe('meetings by day', () => {
    it('sorts each day by the start and skips meetings without a date', () => {
      const late = meeting('a', { startTime: '19:00' });
      const early = meeting('b', { startTime: '17:00' });
      const none = meeting('c', { date: null });
      const map = meetingsByDay([late, none, early]);
      expect([...map.keys()]).toEqual(['2026-10-13']);
      expect(map.get('2026-10-13')?.map((m) => m.id)).toEqual(['b', 'a']);
    });

    it('puts a meeting without a date or a time last, and orders a tie by the title', () => {
      const undated = meeting('u', { date: null });
      const untimed = meeting('n', { startTime: null });
      const a = meeting('x', { title: 'A' });
      const b = meeting('y', { title: 'B' });
      expect([undated, untimed, b, a].sort(byStart).map((m) => m.id)).toEqual(['x', 'y', 'n', 'u']);
    });

    it('matches the search on the title and the Gremium, without case and accents', () => {
      const m = meeting('a', { title: 'Sondersitzung Haushalt', gremiumName: 'Finanzausschuss' });
      expect(matchesQuery(m, '')).toBe(true);
      expect(matchesQuery(m, '  ')).toBe(true);
      expect(matchesQuery(m, 'HAUSHALT')).toBe(true);
      expect(matchesQuery(m, 'finanz')).toBe(true);
      expect(matchesQuery(meeting('b', { title: 'Übergabe', gremiumName: null }), 'uber')).toBe(true);
      expect(matchesQuery(m, 'stupa')).toBe(false);
    });
  });

  describe('groups of the list', () => {
    it('puts the live meetings under "Jetzt", then the months of the coming and the past ones', () => {
      const live = meeting('live', { status: 'live', date: '2026-09-29' });
      const oct1 = meeting('o1', { date: '2026-10-02' });
      const oct2 = meeting('o2', { date: '2026-10-13' });
      const nov = meeting('n1', { date: '2026-11-03' });
      const undated = meeting('u1', { date: null });
      const augOld = meeting('p2', { status: 'closed', date: '2026-08-18' });
      const sep = meeting('p1', { status: 'closed', date: '2026-09-15' });
      const groups = overviewGroups([live, oct1, oct2, nov, undated], [augOld, sep], 'de');
      expect(groups.map((g) => [g.kind, g.month, g.items.map((m) => m.id)])).toEqual([
        ['now', '', ['live']],
        ['upcoming', 'Oktober 2026', ['o1', 'o2']],
        ['upcoming', 'November 2026', ['n1']],
        ['upcoming', '', ['u1']],
        ['past', 'September 2026', ['p1']],
        ['past', 'August 2026', ['p2']],
      ]);
    });

    it('has no "Jetzt" group without a live meeting', () => {
      expect(overviewGroups([], [], 'de')).toEqual([]);
      expect(overviewGroups([meeting('a')], [], 'en')[0].month).toBe('October 2026');
    });
  });

  describe('live facts', () => {
    const vote = (status: MeetingVote['status']): MeetingVote => ({
      id: `v-${status}`,
      applicationId: null,
      agendaItemId: null,
      title: null,
      question: null,
      options: [],
      status,
      result: null,
      counts: null,
      leading: null,
      closesAt: null,
      voted: 14,
      present: 19,
      revealed: false,
      failedReason: null,
    });

    it('computes the progress through the agenda of a live meeting only', () => {
      const live = meeting('a', {
        status: 'live',
        agendaItemCount: 8,
        currentAgendaItem: { position: 3, title: 'Zuschuss' },
      });
      expect(agendaProgress(live)).toEqual({ position: 3, count: 8, percent: 38, title: 'Zuschuss' });
      expect(agendaProgress({ ...live, status: 'planned' })).toBeNull();
      expect(agendaProgress({ ...live, currentAgendaItem: null })).toBeNull();
      expect(agendaProgress({ ...live, agendaItemCount: 0 })).toBeNull();
      expect(agendaProgress({ ...live, agendaItemCount: undefined })).toBeNull();
    });

    it('finds the open vote', () => {
      expect(openVoteOf(meeting('a', { votes: [vote('closed'), vote('open')] }))?.id).toBe('v-open');
      expect(openVoteOf(meeting('a', { votes: [vote('draft')] }))).toBeNull();
    });

    it('counts the roster', () => {
      const row = (status: Attendance['status']): Attendance => ({
        principalId: `p-${Math.random()}`,
        displayName: null,
        email: null,
        status,
        source: null,
        note: null,
        isSelf: false,
      });
      expect(
        attendanceCounts([row('present'), row('present'), row('excused'), row('absent'), row(null)]),
      ).toEqual({ present: 2, excused: 1, absent: 1, open: 1, total: 5 });
    });

    it('names the number of agenda items', () => {
      expect(topsLabel(0, t)).toBe('keine TOPs');
      expect(topsLabel(1, t)).toBe('1 TOP');
      expect(topsLabel(8, t)).toBe('8 TOPs');
    });
  });
});
