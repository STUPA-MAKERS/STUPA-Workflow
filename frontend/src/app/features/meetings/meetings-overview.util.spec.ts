import type { Attendance, Meeting } from '@core/api/models';
import { de } from '@core/i18n/translations';
import { attendanceCounts, overviewGroups, topsLabel } from './meetings-overview.util';

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
    canDelete: false,
    keeperPeriods: [],
    plannedHandover: null,
    publicJoin: false,
    guestsMode: 'vote',
    joinCode: null,
    admittedGuests: 0,
    pendingGuests: 0,
    publicJoinAllowed: true,
    opensAt: null,
    confirmUntil: null,
    ...over,
  };
}

const t = (key: keyof typeof de, params?: Record<string, string | number>): string =>
  Object.entries(params ?? {}).reduce<string>(
    (text, [k, v]) => text.replace(`{${k}}`, String(v)),
    de[key],
  );

describe('meetings-overview.util', () => {
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
