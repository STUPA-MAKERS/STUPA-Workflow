import { gridRange, monthGrid, monthOf, shiftDay, shiftMonth, weekOf, weekdayNames } from './calendar-grid.util';

describe('calendar-grid.util', () => {
  it('runs the month grid from the Monday before the first to the Sunday after the last day', () => {
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

  it('moves months and days across the year', () => {
    expect(shiftMonth({ year: 2026, month: 11 }, 1)).toEqual({ year: 2027, month: 0 });
    expect(shiftMonth({ year: 2026, month: 0 }, -1)).toEqual({ year: 2025, month: 11 });
    expect(monthOf(new Date(2026, 9, 13))).toEqual({ year: 2026, month: 9 });
    expect(shiftDay('2026-12-31', 1)).toBe('2027-01-01');
    expect(shiftDay('2026-03-01', -1)).toBe('2026-02-28');
    expect(shiftDay('no day', 3)).toBe('no day');
  });

  it('gives the week from Monday to Sunday that holds a day', () => {
    const today = new Date(2026, 10, 11);
    const week = weekOf('2026-11-15', today);
    expect(week.map((d) => d.iso)).toEqual([
      '2026-11-09',
      '2026-11-10',
      '2026-11-11',
      '2026-11-12',
      '2026-11-13',
      '2026-11-14',
      '2026-11-15',
    ]);
    expect(week[2]).toEqual({ iso: '2026-11-11', day: 11, inMonth: true, isToday: true });
    expect(gridRange([week])).toEqual({ from: '2026-11-09', to: '2026-11-15' });
    expect(weekOf('2026-11-09', today)[0].iso).toBe('2026-11-09');
    expect(weekOf('', today)[0].iso).toBe('2026-11-09');
  });

  it('names the weekdays', () => {
    expect(weekdayNames('de-DE')).toEqual(['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']);
    expect(weekdayNames('en-GB')[0]).toBe('Mon');
  });
});
