import { readFileSync } from 'node:fs';
import { join } from 'node:path';
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

describe('spanBlocks (§000744)', () => {
  const SPAN = calendarEntry('span', {
    title: 'Klausur',
    startsOn: '2026-11-10',
    endsOn: '2026-11-12',
    startTime: '14:00:00',
    endTime: '12:00:00',
  });

  it('shows a timed entry over several days as a block on each of its days', async () => {
    const openEntry = jest.fn();
    const { container } = await render(CalendarWeekComponent, {
      inputs: { days: DAYS, entries: [SPAN], selectedDay: '2026-11-11', label: 'Woche' },
      on: { openEntry },
    });
    const blocks = screen.getAllByRole('button', { name: /Klausur/ });
    expect(blocks).toHaveLength(3);
    expect(blocks.map((b) => b.closest('.cw__col'))).toEqual([...container.querySelectorAll('.cw__col')].slice(1, 4));
    expect(blocks[0]).toHaveAccessibleName('Di, 10.11.2026, 14:00 – Do, 12.11.2026, 12:00 Klausur');
    expect(blocks[0]).toHaveClass('cw__block--goesOn');
    expect(blocks[0]).not.toHaveClass('cw__block--fromBefore');
    expect(blocks[1]).toHaveClass('cw__block--fromBefore', 'cw__block--goesOn');
    expect(blocks[2]).toHaveClass('cw__block--fromBefore');
    expect(blocks[2]).not.toHaveClass('cw__block--goesOn');
    expect(blocks[2].querySelector('.cw__time')?.textContent).toBe('–12:00');
    expect(blocks[1].querySelector('.cw__time')?.textContent).toBe('');
    expect(container.querySelector('.cw__chip')).toBeNull();
    await userEvent.click(blocks[1]);
    expect(openEntry).toHaveBeenCalledWith(SPAN);
  });
});

describe('overlap (§000745)', () => {
  it('lays a later entry on the earlier one and keeps the earlier one at the width of the day', async () => {
    await render(CalendarWeekComponent, {
      inputs: {
        days: DAYS,
        entries: [
          calendarEntry('a', { title: 'Jour fixe', startTime: '14:00:00', endTime: '15:30:00' }),
          calendarEntry('b', { title: 'Abgleich', startTime: '14:45:00', endTime: '15:15:00' }),
        ],
        selectedDay: '2026-11-11',
        label: 'Woche',
      },
    });
    const under = screen.getByRole('button', { name: /Jour fixe/ });
    const over = screen.getByRole('button', { name: /Abgleich/ });
    expect([under.style.left, under.style.width, under.style.zIndex]).toEqual(['0%', '100%', '1']);
    expect([over.style.left, over.style.width, over.style.zIndex]).toEqual(['20%', '80%', '2']);
    expect(over).toHaveClass('cw__block--over');
    expect(under).not.toHaveClass('cw__block--over');
  });
});

describe('dayLinesOnPull (§000743)', () => {
  const scss = readFileSync(join(__dirname, 'calendar-week.component.scss'), 'utf8');
  const scroll = /\.cw__scroll\s*\{[^}]*\}/.exec(scss)?.[0] ?? '';

  it('draws the day lines on the scroll area, under the columns', () => {
    expect(scroll).toContain('repeating-linear-gradient(');
    expect(scroll).toContain('var(--color-border)');
    expect(scroll).toContain('var(--cw-gutter)');
  });
});
