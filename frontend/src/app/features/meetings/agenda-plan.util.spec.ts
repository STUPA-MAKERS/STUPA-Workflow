import { agendaPlan, minutesInvalid, parseMinutes, planClock } from './agenda-plan.util';

const PLANNED = { date: '2026-06-19', startTime: '17:30:00', endTime: null, status: 'planned' };

function items(...minutes: (number | null)[]) {
  return minutes.map((m, i) => ({ id: `t-${i + 1}`, estimatedMinutes: m }));
}

describe('agendaPlan', () => {
  it('planChain: adds the starts up in agenda order, and an item without a duration adds 0 (§ 001141)', () => {
    const plan = agendaPlan(items(5, 60, null, 10), PLANNED);
    expect(plan.rows.map((r) => (r.start === null ? null : planClock(r.start)))).toEqual([
      '17:30',
      '17:35',
      '18:35',
      '18:35',
    ]);
    expect(plan.rows.map((r) => r.minutes)).toEqual([5, 60, null, 10]);
    expect(planClock(plan.end ?? 0)).toBe('18:45');
    expect(plan.total).toBe(75);
    expect(plan.overrun).toBe(false);
  });

  it('planNone: shows no plan for an agenda without any duration (§ 001141)', () => {
    const plan = agendaPlan(items(null, null), PLANNED);
    expect(plan.rows.every((r) => r.start === null)).toBe(true);
    expect(plan.end).toBeNull();
    expect(plan.total).toBeNull();
  });

  it('planNoStart: gives only the durations and the sum without a start time (§ 001142)', () => {
    const plan = agendaPlan(items(5, null, 10), { ...PLANNED, startTime: null });
    expect(plan.rows.every((r) => r.start === null)).toBe(true);
    expect(plan.end).toBeNull();
    expect(plan.total).toBe(15);
  });

  it('planOverrun: marks a planned end after the end time of the meeting (§ 001144)', () => {
    expect(agendaPlan(items(60, 45), { ...PLANNED, endTime: '18:30:00' }).overrun).toBe(true);
    expect(agendaPlan(items(60), { ...PLANNED, endTime: '18:30:00' }).overrun).toBe(false);
  });

  it('planLive: starts the next item of a live meeting at the later of now and the end of the current one (§ 001143)', () => {
    const live = { ...PLANNED, date: '2026-06-12', startTime: '18:00:00', status: 'live', currentAgendaItemId: 't-2' };
    const rows = [
      { id: 't-1', estimatedMinutes: 5, startedAt: '2026-06-12T16:04:00Z' },
      { id: 't-2', estimatedMinutes: 20, startedAt: '2026-06-12T16:16:00Z' },
      { id: 't-3', estimatedMinutes: 15 },
      { id: 't-4', estimatedMinutes: 10 },
    ];
    const late = agendaPlan(rows, live, new Date('2026-06-12T16:40:00Z'));
    expect(late.rows.map((r) => [planClock(r.start ?? 0), r.actual])).toEqual([
      ['18:04', true],
      ['18:16', true],
      ['18:40', false],
      ['18:55', false],
    ]);
    const early = agendaPlan(rows, live, new Date('2026-06-12T16:20:00Z'));
    expect(planClock(early.rows[2].start ?? 0)).toBe('18:36');
    const otherDay = agendaPlan(rows, live, new Date('2026-06-13T16:40:00Z'));
    expect(planClock(otherDay.rows[2].start ?? 0)).toBe('18:36');
  });

  it('ignores the recorded times of a planned meeting', () => {
    const plan = agendaPlan([{ id: 't-1', estimatedMinutes: 5, startedAt: '2026-06-19T15:00:00Z' }], PLANNED);
    expect(plan.rows[0]).toEqual({ start: 17 * 60 + 30, actual: false, minutes: 5 });
  });
});

describe('minutes field', () => {
  it('minutesField: takes whole minutes from 1 to 480 and an empty field (§ 001140)', () => {
    expect(parseMinutes('15')).toBe(15);
    expect(parseMinutes(480)).toBe(480);
    expect(parseMinutes('')).toBeNull();
    expect(parseMinutes(null)).toBeNull();
    expect(parseMinutes(undefined)).toBeNull();
    expect(minutesInvalid(undefined)).toBe(false);
    expect(minutesInvalid('')).toBe(false);
    expect(minutesInvalid(null)).toBe(false);
    for (const bad of [0, 481, '2.5', 'abc', -3]) {
      expect(minutesInvalid(bad)).toBe(true);
      expect(parseMinutes(bad)).toBeNull();
    }
  });

  it('wraps a clock past midnight', () => {
    expect(planClock(24 * 60 + 15)).toBe('00:15');
  });
});
