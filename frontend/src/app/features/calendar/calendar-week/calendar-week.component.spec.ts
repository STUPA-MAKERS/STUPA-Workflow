import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { calendarEntry } from '../../../../testing/calendar-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { weekOf } from '../calendar-grid.util';
import { CalendarWeekComponent } from './calendar-week.component';

const DAYS = weekOf('2026-11-11', new Date(2026, 10, 11));
const TIMED = calendarEntry('timed', { title: 'Jour fixe', startTime: '14:00:00', endTime: '15:30:00' });
const CARD = calendarEntry('card', { kind: 'card', title: 'Angebot einholen' });
const EVENT = calendarEntry('event', {
  kind: 'event',
  title: 'Infoabend',
  startsOn: '2026-11-13',
  endsOn: '2026-11-13',
  startTime: '19:00:00',
});
const SHORT = calendarEntry('short', { title: 'Abgleich', startTime: '14:30:00', endTime: '14:45:00' });

async function setup(entries = [TIMED, CARD, EVENT, SHORT]) {
  const on = { selectDay: jest.fn(), openEntry: jest.fn() };
  const view = await render(CalendarWeekComponent, {
    inputs: { days: DAYS, entries, selectedDay: '2026-11-11', label: 'Woche' },
    on,
  });
  const column = (index: number) => view.container.querySelectorAll<HTMLElement>('.cw__col')[index];
  const allDay = (index: number) => view.container.querySelectorAll<HTMLElement>('.cw__cell')[index];
  return { ...view, on, column, allDay };
}

describe('CalendarWeekComponent', () => {
  it('shows the seven days from Monday to Sunday with the hours from 08:00 to 21:00', async () => {
    const view = await setup();
    const heads = Array.from(view.container.querySelectorAll<HTMLElement>('.cw__day'));
    expect(heads.map((h) => h.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Mo9', 'Di10', 'Mi11', 'Do12', 'Fr13', 'Sa14', 'So15',
    ]);
    expect(screen.getByRole('button', { name: /11\. November 2026/ })).toBe(heads[2]);
    expect(heads[2]).toHaveAttribute('aria-pressed', 'true');
    expect(heads[2]).toHaveAttribute('aria-current', 'date');
    expect(heads[2].querySelector('.cw__num')).toHaveClass('cw__num--today');
    const hours = Array.from(view.container.querySelectorAll('.cw__hours .cw__hour')).map((h) => h.textContent);
    expect(hours[0]).toBe('08:00');
    expect(hours).toHaveLength(13);
    expect(hours.at(-1)).toBe('20:00');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  /** § 000728: a timed Termin is a block in the column of its day, a due card is above the hours. */
  it('draws a timed Termin as a block at its time and a due card in the all-day row', async () => {
    const view = await setup();
    const block = within(view.column(2)).getByRole('button', { name: '14:00 – 15:30 Jour fixe' });
    expect(block.style.top).toBe('21rem');
    expect(block.style.height).toBe('5.25rem');
    expect(block.style.width).toBe('50%');
    expect(block).toHaveClass('cw__block--narrow');
    expect(within(view.allDay(2)).getByRole('button', { name: /Angebot einholen/ })).toBeInTheDocument();
    expect(within(view.column(2)).queryByRole('button', { name: /Angebot einholen/ })).toBeNull();
    expect(view.allDay(0).querySelector('button')).toBeNull();
  });

  /** § 000737: a timed Event is a block at its time, like a Termin. */
  it('draws a timed Event as a block at its time', async () => {
    const view = await setup();
    const block = within(view.column(4)).getByRole('button', { name: '19:00 Infoabend' });
    expect(block.style.top).toBe('38.5rem');
    expect(block.style.height).toBe('3.5rem');
    expect(block.style.width).toBe('100%');
    expect(block).not.toHaveClass('cw__block--narrow');
  });

  it('marks a short block and hides the end of a narrow one', async () => {
    const view = await setup();
    const short = within(view.column(2)).getByRole('button', { name: '14:30 – 14:45 Abgleich' });
    expect(short).toHaveClass('cw__block--short');
    expect(short.querySelector('.cw__end')).toBeNull();
    view.fixture.componentRef.setInput('entries', [TIMED]);
    view.fixture.detectChanges();
    const block = within(view.column(2)).getByRole('button', { name: '14:00 – 15:30 Jour fixe' });
    expect(block.querySelector('.cw__end')?.textContent).toBe('–15:30');
  });

  it('widens the axis for an early entry', async () => {
    const view = await setup([calendarEntry('early', { startTime: '06:00:00', endTime: '07:00:00' })]);
    expect(view.container.querySelector('.cw__hours .cw__hour')?.textContent).toBe('06:00');
    expect(within(view.column(2)).getByRole('button', { name: /06:00/ }).style.top).toBe('0rem');
  });

  it('picks a day on its head and opens an entry on a press', async () => {
    const view = await setup();
    await userEvent.click(screen.getByRole('button', { name: /13\. November 2026/ }));
    expect(view.on.selectDay).toHaveBeenCalledWith('2026-11-13');
    await userEvent.click(screen.getByRole('button', { name: '14:00 – 15:30 Jour fixe' }));
    expect(view.on.openEntry).toHaveBeenCalledWith(TIMED);
    await userEvent.click(screen.getByRole('button', { name: /Angebot einholen/ }));
    expect(view.on.openEntry).toHaveBeenCalledWith(CARD);
  });
});
