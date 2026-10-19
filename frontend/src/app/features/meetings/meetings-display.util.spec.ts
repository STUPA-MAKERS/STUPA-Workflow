import type { AgendaItem, Meeting, MeetingVote } from '@core/api/models';
import {
  voteMetaLine,
  voteRulesParts,
  guestComposition,
  majorityLabel,
  quorumLabel,
  secrecyLabel,
  assembleProtocolMarkdown,
  meetingDay,
  meetingTimeText,
  attendanceBadgeVariant,
  attendanceButtonVariant,
  attendanceIcon,
  attendanceKey,
  countEntries,
  liveOpenedVote,
  meetingLine,
  meetingStatusKey,
  meetingTimeSuffix,
  meetingStatusVariant,
  memberAttendanceBadgeVariant,
  memberAttendanceKey,
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
  status: 'draft',
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
    expect(voteStatusVariant('draft')).toBe('warning');
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
      ...(['draft', 'open', 'closed', 'cancelled'] as const).map(voteStatusVariant),
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
    expect(attendanceIcon('absent')).toBe('x');
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

  it('labels vote options, falling back to the raw key when untranslated', () => {
    const translate = (key: string): string => (key === 'vote.option.yes' ? 'Ja' : key);
    expect(voteOptionLabel('yes', translate)).toBe('Ja');
    expect(voteOptionLabel('maybe', translate)).toBe('maybe');
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

  it('names the meeting with its date and a short weekday', () => {
    const m = { title: '35. Sitzung', date: '2026-10-13' } as Parameters<typeof meetingLine>[0];
    expect(meetingLine(m, 'de-DE')).toBe('35. Sitzung · Di, 13.10.2026');
    expect(meetingLine({ ...m, date: null }, 'de-DE')).toBe('35. Sitzung');
    expect(meetingLine({ ...m, date: 'kein Datum' }, 'de-DE')).toBe('35. Sitzung');
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
    expect(vote.secret).toBeUndefined();
    expect(vote.openedAt).toEqual(expect.any(String));
    expect(liveOpenedVote({ type: 'vote_opened', voteId: 'v-8', options: [], closesAt: null, secret: true }).secret).toBe(true);
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

describe('voteMetaLine', () => {
  const base: MeetingVote = {
    id: 'v-1', applicationId: null, agendaItemId: null, title: null, question: null,
    options: [], status: 'open', result: null, counts: null, leading: null, closesAt: null,
    voted: 0, present: 0, revealed: false, failedReason: null,
  };
  const t = (key: string, params?: Record<string, string | number>) =>
    params ? `${key}(${Object.values(params).join(',')})` : key;

  it('joins rule, secrecy, quorum and the open time', () => {
    const line = voteMetaLine(
      { ...base, majorityRule: 'two_thirds', secret: false, quorum: { type: 'count', value: 12 }, openedAt: '2026-10-15T16:48:00Z' },
      t as never,
      'de',
    );
    expect(line).toMatch(/^vote\.majority\.two_thirds · meetings\.vote\.publicShort · meetings\.vote\.quorumCount\(12\) · meetings\.vote\.since\(\d\d:48\)$/);
  });

  it('names a secret vote, a percentage quorum and the end of a closed or cancelled vote', () => {
    expect(
      voteMetaLine({ ...base, status: 'closed', secret: true, quorum: { type: 'percent', value: 50 }, closedAt: '2026-10-15T17:02:00Z' }, t as never, 'de'),
    ).toMatch(/^meetings\.vote\.secretShort · meetings\.vote\.quorumPercent\(50\) · meetings\.vote\.endedAt\(\d\d:02\)$/);
    expect(voteMetaLine({ ...base, status: 'cancelled', closedAt: null }, t as never, 'de')).toBe('');
  });

  it('leaves out what a live event did not bring yet', () => {
    expect(voteMetaLine(base, t as never, 'de')).toBe('');
    expect(voteMetaLine({ ...base, status: 'draft', majorityRule: 'simple' }, t as never, 'de')).toBe('vote.majority.simple');
  });
});

describe('voteRulesParts', () => {
  const t = (key: string, params?: Record<string, string | number>) =>
    params ? `${key}(${Object.values(params).join(',')})` : key;

  it('lists majority, secrecy and quorum in the one order', () => {
    expect(
      voteRulesParts({ majorityRule: 'simple', secret: false, quorum: { type: 'count', value: 12 } }, t as never),
    ).toEqual(['vote.majority.simple', 'meetings.vote.publicShort', 'meetings.vote.quorumCount(12)']);
    expect(voteRulesParts({ majorityRule: 'absolute', secret: true, quorum: { type: 'percent', value: 50 } }, t as never)).toEqual([
      'vote.majority.absolute',
      'meetings.vote.secretShort',
      'meetings.vote.quorumPercent(50)',
    ]);
  });

  it('gives the ballot form: the quorum first, only a secret vote named', () => {
    const rules = { majorityRule: 'absolute', secret: true, quorum: { type: 'count' as const, value: 12 } };
    expect(voteRulesParts(rules, t as never, { ballot: true })).toEqual([
      'vote.majority.absolute',
      'meetings.vote.quorumCount(12)',
      'meetings.vote.secretShort',
    ]);
    expect(voteRulesParts({ ...rules, secret: false }, t as never, { ballot: true })).toEqual([
      'vote.majority.absolute',
      'meetings.vote.quorumCount(12)',
    ]);
  });

  it('names the majority of the cast votes for a vote with guests', () => {
    expect(voteRulesParts({ majorityRule: 'simple', guestsVote: true }, t as never)).toEqual(['vote.majorityCast.simple']);
    expect(majorityLabel('two_thirds', false, t as never)).toBe('vote.majority.two_thirds');
  });

  it('leaves out the parts without data', () => {
    expect(voteRulesParts({}, t as never)).toEqual([]);
    expect(voteRulesParts({ majorityRule: null, quorum: null, secret: true }, t as never)).toEqual([
      'meetings.vote.secretShort',
    ]);
    expect(secrecyLabel(false, t as never)).toBe('meetings.vote.publicShort');
    expect(quorumLabel({ type: 'count', value: 3 }, t as never)).toBe('meetings.vote.quorumCount(3)');
  });
});

describe('guestComposition', () => {
  const t = (key: string, params?: Record<string, string | number>) =>
    params ? `${key}(${Object.values(params).join(',')})` : key;

  it('names members and guests, or nothing while a count is unknown', () => {
    expect(guestComposition(19, 7, t as never)).toBe('guests.vote.composition(19,7)');
    expect(guestComposition(19, null, t as never)).toBeNull();
    expect(guestComposition(undefined, 7, t as never)).toBeNull();
  });
});
