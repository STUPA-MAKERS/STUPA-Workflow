import type { Attendance } from '@core/api/models';
import { eligibleCount, presentCount } from './present-count.util';

const row = (status: Attendance['status'], canVote: boolean): Attendance => ({
  principalId: `p-${status}-${canVote}`,
  displayName: null,
  email: null,
  status,
  source: null,
  note: null,
  isSelf: false,
  canKeepProtocol: false,
  canVote,
});

/** Spec 000946: one count of present members in the head, the list and the votes. */
describe('presentCount', () => {
  const rows = [row('present', true), row('present', false), row('excused', true), row(null, true)];

  it('counts the present members with a voting right and the pool seats', () => {
    expect(presentCount({ presentSeats: 2 }, rows)).toBe(3);
    expect(presentCount(null, rows)).toBe(1);
    expect(eligibleCount(null, rows)).toBe(3);
  });

  it('counts each present delegate once and no pool seat on top (spec 003151)', () => {
    const lea: Attendance = {
      ...row('present', false),
      principalId: 'lea',
      isMember: false,
      represents: [
        { principalId: 'max', displayName: 'Max' },
        { principalId: 'mia', displayName: 'Mia' },
      ],
    };
    const ole: Attendance = { ...lea, principalId: 'ole', status: 'absent' };
    const plain = rows.map((r) => ({ ...r, represents: [] }));
    expect(presentCount({ presentSeats: 1 }, [...plain, lea, ole])).toBe(2);
  });

  it('shows the values that the close of the meeting fixed', () => {
    const closed = { presentCount: 7, eligibleCount: 9, presentSeats: 0 };
    expect(presentCount(closed, rows)).toBe(7);
    expect(eligibleCount(closed, rows)).toBe(9);
  });
});
