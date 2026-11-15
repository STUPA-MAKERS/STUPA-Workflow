import type { I18nService } from '@core/i18n/i18n.service';
import { firstMeetingLink, firstMeetingOptions, lateInviteDays } from './meeting-kind.util';

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

/** §F/meetings/meetings/000940 */
describe('first meeting of a repeat meeting', () => {
  const MEETINGS = [
    { id: 'a', title: '34. Sitzung', date: '2026-11-03' },
    { id: 'b', title: '35. Sitzung', date: '2026-11-10' },
    { id: 'c', title: 'Ohne Datum', date: null },
  ];

  it('offers the other meetings that are not after the day', () => {
    expect(firstMeetingOptions(MEETINGS, 'de-DE', '2026-11-10', 'b')).toEqual([
      { value: 'a', label: '34. Sitzung · 03.11.2026' },
      { value: 'c', label: 'Ohne Datum' },
    ]);
    expect(firstMeetingOptions(MEETINGS, 'de-DE', '2026-11-05').map((o) => o.value)).toEqual(['a', 'c']);
    expect(firstMeetingOptions(MEETINGS, 'de-DE', ' ').map((o) => o.value)).toEqual(['a', 'b', 'c']);
  });

  it('links the first meeting, and nothing without one', () => {
    const i18n = { translate: (key: string) => key } as unknown as I18nService;
    expect(firstMeetingLink({ repeatOfId: 'a' }, i18n)).toEqual({ label: 'meetings.repeatOf.label', to: '/meetings/a' });
    expect(firstMeetingLink({ repeatOfId: null }, i18n)).toBeNull();
    expect(firstMeetingLink({}, i18n)).toBeNull();
  });
});
