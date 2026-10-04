import type { AgendaItem, Meeting, MeetingVote } from '@core/api/models';
import {
  assembleProtocolMarkdown,
  clockTime,
  errorCode,
  meetingDay,
  meetingTimeText,
  attendanceBadgeVariant,
  attendanceButtonVariant,
  attendanceIcon,
  attendanceKey,
  countEntries,
  errorDetail,
  liveOpenedVote,
  longDate,
  meetingStatusKey,
  meetingTimeSuffix,
  meetingStatusVariant,
  memberAttendanceBadgeVariant,
  memberAttendanceKey,
  pickBeamerVote,
  resolveI18n,
  shortTime,
  voteOptionLabel,
  voteOptionsFor,
  voteResultKey,
  voteResultVariant,
  voteStatusKey,
  voteStatusVariant,
} from './meetings-display.util';

const VOTE = (over: Partial<MeetingVote> = {}): MeetingVote => ({
  id: 'v-1',
  applicationId: null,
  agendaItemId: null,
  title: null,
  question: null,
  options: [],
  status: 'pending',
  result: null,
  counts: null,
  leading: null,
  closesAt: null,
  voted: 0,
  present: 0,
  revealed: true,
  failedReason: null,
  ...over,
});

describe('meetings-display.util', () => {
  it('maps meeting status to badge variants and keys', () => {
    expect(meetingStatusVariant('live')).toBe('success');
    expect(meetingStatusVariant('closed')).toBe('info');
    expect(meetingStatusVariant('planned')).toBe('info');
    expect(meetingStatusKey('live')).toBe('meetings.status.live');
  });

  it('maps vote status and results', () => {
    expect(voteStatusVariant('open')).toBe('success');
    expect(voteStatusVariant('closed')).toBe('info');
    expect(voteStatusVariant('cancelled')).toBe('danger');
    expect(voteStatusVariant('pending')).toBe('warning');
    expect(voteStatusKey('open')).toBe('meetings.voteStatus.open');
    expect(voteResultKey('passed')).toBe('vote.result.passed');
    expect(voteResultKey(null)).toBe('vote.result.tie');
    expect(voteResultVariant('passed')).toBe('success');
    expect(voteResultVariant('rejected')).toBe('danger');
    expect(voteResultVariant('tie')).toBe('info');
  });

  it('never maps a status to the neutral tag variant', () => {
    // `neutral` is a tag (a grey plate). A status shows as coloured text only.
    const variants = [
      ...(['planned', 'live', 'closed'] as const).map(meetingStatusVariant),
      ...(['pending', 'open', 'closed', 'cancelled'] as const).map(voteStatusVariant),
      ...['passed', 'rejected', 'tie', null, undefined, 'unknown'].map(voteResultVariant),
      ...(['present', 'excused', 'absent'] as const).flatMap((s) => [
        attendanceBadgeVariant(s),
        memberAttendanceBadgeVariant(s),
      ]),
    ];
    expect(variants).not.toContain('neutral');
    expect(variants).not.toContain('accent');
  });

  it('maps attendance to keys, variants and icons', () => {
    expect(attendanceKey('present')).toBe('meetings.attendance.present');
    expect(attendanceButtonVariant('present')).toBe('primary');
    expect(attendanceButtonVariant('excused')).toBe('secondary');
    expect(attendanceButtonVariant('absent')).toBe('danger');
    expect(attendanceIcon('present')).toBe('check');
    expect(attendanceIcon('excused')).toBe('half');
    expect(attendanceIcon('absent')).toBe('remove');
    expect(attendanceBadgeVariant('present')).toBe('success');
    expect(attendanceBadgeVariant('excused')).toBe('warning');
    expect(attendanceBadgeVariant('absent')).toBe('danger');
  });

  it('gives a member only the labels "Anwesend" and "Abwesend" (Z2)', () => {
    expect(memberAttendanceKey('present')).toBe('meetings.attendance.selfPresent');
    expect(memberAttendanceKey('excused')).toBe('meetings.attendance.selfExcused');
    expect(memberAttendanceKey('absent')).toBe('meetings.attendance.selfExcused');
    expect(memberAttendanceBadgeVariant('present')).toBe('success');
    expect(memberAttendanceBadgeVariant('excused')).toBe('warning');
    expect(memberAttendanceBadgeVariant('absent')).toBe('warning');
  });

  it('lists tally entries and vote options with the count-key fallback', () => {
    const vote = VOTE({ counts: { yes: 3, no: 1 } });
    expect(countEntries(vote)).toEqual([
      { key: 'yes', value: 3 },
      { key: 'no', value: 1 },
    ]);
    expect(voteOptionsFor(vote)).toEqual(['yes', 'no']);
    expect(voteOptionsFor(VOTE({ options: ['a'], counts: { b: 1 } }))).toEqual(['a']);
    expect(countEntries(VOTE())).toEqual([]);
  });

  it('resolves i18n maps with locale → de → first-value → empty fallbacks', () => {
    expect(resolveI18n({ en: 'Open', de: 'Offen' }, 'en')).toBe('Open');
    expect(resolveI18n({ de: 'Offen' }, 'en')).toBe('Offen');
    expect(resolveI18n({ fr: 'Ouvert' }, 'en')).toBe('Ouvert');
    expect(resolveI18n({}, 'en')).toBe('');
    expect(resolveI18n(null, 'en')).toBe('');
  });

  it('labels vote options, falling back to the raw key when untranslated', () => {
    const translate = (key: string): string => (key === 'vote.option.yes' ? 'Ja' : key);
    expect(voteOptionLabel('yes', translate)).toBe('Ja');
    expect(voteOptionLabel('maybe', translate)).toBe('maybe');
  });

  it('extracts the problem+json detail from an HTTP error', () => {
    expect(errorDetail({ error: { detail: 'nope' } })).toBe('nope');
    expect(errorDetail({ error: {} })).toBe('');
    expect(errorDetail(null)).toBe('');
  });

  it('assembles protocol markdown with heading, antrag ref and body', () => {
    const agenda = [
      { title: 'TOP A', applicationId: 'app-1', body: 'Text' },
      { title: '  ', applicationId: null, body: null },
    ] as unknown as AgendaItem[];
    expect(assembleProtocolMarkdown(agenda)).toBe(
      '# TOP A\n\n:::antrag{#app-1}\n:::\n\nText\n\n# Tagesordnungspunkt',
    );
  });

  it('picks the beamer vote: open first, else last closed, else null', () => {
    const open = VOTE({ id: 'open', status: 'open' });
    const c1 = VOTE({ id: 'c1', status: 'closed' });
    const c2 = VOTE({ id: 'c2', status: 'closed' });
    expect(pickBeamerVote([c1, open, c2])?.id).toBe('open');
    expect(pickBeamerVote([c1, c2])?.id).toBe('c2');
    expect(pickBeamerVote([VOTE()])).toBeNull();
  });

  it('formats long dates per locale and passes invalid input through', () => {
    expect(longDate('2026-06-14', 'de')).toBe('14. Juni 2026');
    // en-GB puts the day before the month name.
    expect(longDate('2026-06-14', 'en')).toBe('14 June 2026');
    expect(longDate('not-a-date', 'de')).toBe('not-a-date');
  });

  it('shortens a clock time to HH:MM and keeps 24 h', () => {
    // The API sends the SQL `time` as `HH:MM:SS`. Only hours and minutes are shown.
    expect(shortTime('18:00:00')).toBe('18:00');
    expect(shortTime('08:05:30.5')).toBe('08:05');
    expect(shortTime('18:00')).toBe('18:00');
    expect(shortTime('9:05')).toBe('09:05');
    expect(shortTime('')).toBe('');
    expect(shortTime(null)).toBe('');
    expect(shortTime(undefined)).toBe('');
    // Text that is not a time stays as it is. Garbage is better than a wrong time.
    expect(shortTime('bald')).toBe('bald');
    expect(shortTime('25:00:00')).toBe('25:00:00');
  });

  it('builds the ", HH:MM" suffix of a meeting date, or nothing', () => {
    expect(meetingTimeSuffix('18:00:00')).toBe(', 18:00');
    expect(meetingTimeSuffix('18:00')).toBe(', 18:00');
    expect(meetingTimeSuffix(null)).toBe('');
    expect(meetingTimeSuffix('  ')).toBe('');
  });

  it('builds a placeholder vote from a live vote_opened message', () => {
    const vote = liveOpenedVote({
      type: 'vote_opened',
      voteId: 'v-9',
      applicationId: null,
      agendaItemId: 't-1',
      question: 'Q?',
      options: ['yes', 'no'],
      closesAt: null,
    });
    expect(vote).toMatchObject({
      id: 'v-9',
      agendaItemId: 't-1',
      question: 'Q?',
      options: ['yes', 'no'],
      status: 'open',
      revealed: false,
    });
  });

  it('reads the stable problem+json code of an HTTP error', () => {
    expect(errorCode({ error: { code: 'open_vote' } })).toBe('open_vote');
    expect(errorCode({ error: { code: 7 } })).toBe('');
    expect(errorCode(null)).toBe('');
  });

  it('prints the clock time of a timestamp in local time, 24 h', () => {
    const local = new Date(2026, 8, 29, 18, 4).toISOString();
    expect(clockTime(local, 'de')).toBe('18:04');
    expect(clockTime(local, 'en')).toBe('18:04');
    expect(clockTime(null, 'de')).toBe('');
    expect(clockTime('kaputt', 'de')).toBe('');
  });

  describe('meetingTimeText', () => {
    const base = {
      status: 'planned',
      startTime: '18:00:00',
      endTime: null,
      startedAt: null,
      closedAt: null,
    } as unknown as Meeting;
    const at = (h: number, m: number) => new Date(2026, 8, 29, h, m).toISOString();

    it('shows the planned start, and the end when there is one', () => {
      expect(meetingTimeText(base, 'de')).toEqual({ text: '18:00', since: false });
      expect(meetingTimeText({ ...base, startTime: '17:30', endTime: '19:00' }, 'de')).toEqual({
        text: '17:30–19:00',
        since: false,
      });
      expect(meetingTimeText({ ...base, startTime: null }, 'de')).toEqual({ text: '', since: false });
    });

    it('shows a live meeting as "since" its real start (O9)', () => {
      const live = { ...base, status: 'live', startedAt: at(18, 4) } as Meeting;
      expect(meetingTimeText(live, 'de')).toEqual({ text: '18:04', since: true });
      // Started before the real start was stored: the planned start.
      expect(meetingTimeText({ ...live, startedAt: null }, 'de')).toEqual({ text: '18:00', since: false });
    });

    it('shows a closed meeting from the real start to the close', () => {
      const closed = { ...base, status: 'closed', startedAt: at(18, 4), closedAt: at(21, 40) } as Meeting;
      expect(meetingTimeText(closed, 'de')).toEqual({ text: '18:04–21:40', since: false });
      expect(meetingTimeText({ ...closed, closedAt: null }, 'de')).toEqual({ text: '18:04', since: false });
      expect(meetingTimeText({ ...closed, startedAt: null }, 'de').text).toBe('18:00');
    });
  });

  it('gives the date block a local midnight, or null without a date', () => {
    expect(meetingDay({ date: '2026-10-13' } as Meeting)).toBe('2026-10-13T00:00:00');
    expect(meetingDay({ date: null } as Meeting)).toBeNull();
  });
});
