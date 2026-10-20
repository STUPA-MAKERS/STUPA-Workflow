import {
  calendarDaysSince,
  clock,
  dayMonth,
  dayMonthYear,
  daysUntil,
  isoDay,
  localToday,
  longDate,
  monthShort,
  monthYear,
  parseDay,
  shortDay,
  shortTime,
  weekdayDate,
  weekdayName,
} from './date-format';

describe('date-format', () => {
  describe('days', () => {
    it('writes the local calendar day', () => {
      expect(isoDay(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05');
      expect(localToday(new Date(2026, 0, 5, 0, 1))).toBe('2026-01-05');
      expect(localToday()).toBe(isoDay(new Date()));
    });

    it('parses a day and a month as local noon, anything else as a moment', () => {
      const day = parseDay('2026-10-16');
      expect(day?.getDate()).toBe(16);
      expect(day?.getHours()).toBe(12);
      expect(parseDay('2026-10')?.getDate()).toBe(1);
      expect(parseDay('2026-10')?.getMonth()).toBe(9);
      expect(parseDay('2026-10-20T10:00:00Z')?.toISOString()).toBe('2026-10-20T10:00:00.000Z');
      const at = new Date(2026, 1, 3);
      expect(parseDay(at)).toBe(at);
      expect(parseDay(at.getTime())?.getTime()).toBe(at.getTime());
    });

    it('gives null for no or an invalid value', () => {
      for (const bad of [null, undefined, '', 'nope', '16.10.2026', new Date(NaN)]) {
        expect(parseDay(bad)).toBeNull();
      }
    });

    it('counts calendar days, not blocks of 24 hours', () => {
      expect(daysUntil('2026-10-20', '2026-10-16')).toBe(4);
      expect(daysUntil('2026-10-12', '2026-10-16')).toBe(-4);
      expect(daysUntil('2026-03-30', '2026-03-28')).toBe(2);
      expect(daysUntil('bad', '2026-10-16')).toBeNull();
      expect(daysUntil('2026-10-16', 'bad')).toBeNull();
      expect(daysUntil('2026-10-08', new Date(2026, 9, 5, 23, 30))).toBe(3);
      expect(daysUntil(isoDay(new Date()))).toBe(0);
    });

    it('counts the calendar days since a moment, never below 0', () => {
      const now = new Date(2026, 9, 16, 9, 0);
      expect(calendarDaysSince(new Date(2026, 9, 15, 23, 0).toISOString(), now)).toBe(1);
      expect(calendarDaysSince(new Date(2026, 9, 16, 1, 0).toISOString(), now)).toBe(0);
      expect(calendarDaysSince(new Date(2026, 9, 11, 12, 0).toISOString(), now)).toBe(5);
      expect(calendarDaysSince(new Date(2026, 9, 18, 12, 0).toISOString(), now)).toBe(0);
      expect(calendarDaysSince(null, now)).toBeNull();
      expect(calendarDaysSince('nope', now)).toBeNull();
      expect(calendarDaysSince(new Date().toISOString())).toBe(0);
    });
  });

  describe('texts', () => {
    const day = '2026-10-13';

    it('writes the short dates in both locales', () => {
      expect(dayMonth(day, 'de-DE')).toBe('13.10.');
      expect(dayMonth(day, 'en-GB')).toBe('13/10');
      expect(dayMonthYear(day, 'de-DE')).toBe('13.10.2026');
      expect(dayMonthYear(day, 'en-GB')).toBe('13/10/2026');
      expect(dayMonthYear('2026-10-02T10:00:00Z', 'de-DE')).toBe('02.10.2026');
      expect(dayMonth(null, 'de-DE')).toBe('');
      expect(dayMonthYear('nope', 'de-DE')).toBe('');
    });

    it('adds the closing dot when ICU leaves it out', () => {
      // The formats are made once and kept, so the spy sits on the shared prototype.
      const format = jest.spyOn(Intl.DateTimeFormat.prototype, 'format', 'get').mockReturnValue(() => '13.10');
      expect(dayMonth(day, 'de-DE')).toBe('13.10.');
      expect(dayMonth(day, 'en-GB')).toBe('13.10');
      format.mockRestore();
    });

    it('adds the year only for another year', () => {
      expect(shortDay(day, 'de-DE', '2026-01-01')).toBe('13.10.');
      expect(shortDay(day, 'de-DE', '2025-12-31')).toBe('13.10.2026');
      expect(shortDay('2027-01-05', 'de-DE', '2026-10-16')).toBe('05.01.2027');
      expect(shortDay(day, 'en-GB', '2026-10-16')).toBe('13/10');
      expect(shortDay(day, 'de-DE', 'nope')).toBe('13.10.2026');
      expect(shortDay('', 'de-DE', '2026-01-01')).toBe('');
      expect(shortDay(isoDay(new Date()), 'de-DE')).not.toMatch(/\d{4}$/);
    });

    it('writes the weekday without its dot', () => {
      expect(weekdayName(day, 'de-DE')).toBe('Di');
      expect(weekdayName(day, 'en-GB')).toBe('Tue');
      expect(weekdayName(null, 'de-DE')).toBe('');
      expect(weekdayDate(day, 'de-DE')).toBe('Di, 13.10.2026');
      expect(weekdayDate(day, 'en-GB')).toBe('Tue, 13/10/2026');
      expect(weekdayDate(day, 'de-DE', { year: false })).toBe('Di, 13.10.');
      expect(weekdayDate(day, 'en-GB', { year: false })).toBe('Tue, 13/10');
      expect(weekdayDate('', 'de-DE', { year: false })).toBe('');
      expect(weekdayDate(new Date(2026, 9, 13, 17, 5), 'de-DE', { time: true })).toBe(
        'Di, 13.10.2026, 17:05',
      );
      expect(weekdayDate('nope', 'de-DE')).toBe('');
    });

    it('writes months', () => {
      expect(monthYear('2026-10', 'de-DE')).toBe('Oktober 2026');
      expect(monthYear(day, 'en-GB')).toBe('October 2026');
      expect(monthYear('2026-09-30T23:30:00Z', 'de-DE', { utc: true })).toBe('September 2026');
      expect(monthYear(null, 'de-DE')).toBe('');
      expect(monthShort('2026-10', 'de-DE')).toBe('Okt');
      expect(monthShort('2026-10', 'en-GB')).toBe('Oct');
      expect(monthShort('2026-03', 'de-DE')).toBe('Mär');
      expect(monthShort('2026-09', 'en-GB')).toBe('Sept');
      expect(monthShort('', 'de-DE')).toBe('');
      expect(longDate('2026-06-14', 'de-DE')).toBe('14. Juni 2026');
      expect(longDate('2026-06-14', 'en-GB')).toBe('14 June 2026');
      expect(longDate('nope', 'de-DE')).toBe('');
    });

    it('writes the clock time in 24 h', () => {
      expect(clock(new Date(2026, 9, 13, 18, 4), 'de-DE')).toBe('18:04');
      expect(clock(new Date(2026, 9, 13, 19, 50), 'en-GB')).toBe('19:50');
      expect(clock(new Date(2026, 9, 13, 0, 5), 'en-GB')).toBe('00:05');
      expect(clock(null, 'de-DE')).toBe('');
      expect(clock('nope', 'de-DE')).toBe('');
    });

    it('shortens a SQL time and keeps unreadable text', () => {
      expect(shortTime('18:00:00')).toBe('18:00');
      expect(shortTime('9:05')).toBe('09:05');
      expect(shortTime('18:00:00.123')).toBe('18:00');
      expect(shortTime('08:05:30.5')).toBe('08:05');
      expect(shortTime('')).toBe('');
      expect(shortTime('25:00:00')).toBe('25:00:00');
      expect(shortTime(null)).toBe('');
      expect(shortTime(' abends ')).toBe('abends');
    });
  });
});
