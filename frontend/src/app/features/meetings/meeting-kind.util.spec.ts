import { lateInviteDays } from './meeting-kind.util';

const PERIODS = { inviteDaysOrdinary: 7, inviteDaysExtraordinary: 3 };
const TODAY = new Date(2026, 10, 14);

/** § 000918 */
describe('lateInviteDays', () => {
  it('gives the period of an ordinary meeting when the date is nearer', () => {
    expect(lateInviteDays('2026-11-20', 'ordinary', PERIODS, TODAY)).toBe(7);
    expect(lateInviteDays('2026-11-21', 'ordinary', PERIODS, TODAY)).toBeNull();
  });

  it('uses the short period for every other kind, a repeat meeting too', () => {
    expect(lateInviteDays('2026-11-16', 'repeat', PERIODS, TODAY)).toBe(3);
    expect(lateInviteDays('2026-11-17', 'repeat', PERIODS, TODAY)).toBeNull();
    expect(lateInviteDays('2026-11-16', 'extraordinary', PERIODS, TODAY)).toBe(3);
  });

  it('gives nothing without the periods and nothing without a date', () => {
    expect(lateInviteDays('2026-11-15', 'ordinary', null, TODAY)).toBeNull();
    expect(lateInviteDays('', 'ordinary', PERIODS, TODAY)).toBeNull();
  });
});
