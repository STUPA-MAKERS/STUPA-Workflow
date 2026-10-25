import { fireEvent, render, screen } from '@testing-library/angular';
import { MEDIA } from '@stupa-makers/ui-kit';
import { BOARDS, asPhone } from '../../../../testing/todo-fixtures';
import { ALL_ICON, BOARD_ICON, TodoBoardPickerComponent } from './todo-board-picker.component';

async function setup(inputs: Record<string, unknown> = {}) {
  const picked = jest.fn();
  const view = await render(TodoBoardPickerComponent, {
    inputs: { boards: BOARDS, current: 'b-1', ...inputs },
    on: { picked },
  });
  const flush = async () => {
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  return { ...view, picked, cmp: view.fixture.componentInstance, flush };
}

describe('TodoBoardPickerComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.restoreAllMocks());

  it('names the current board and lists the boards in sections', async () => {
    const { flush } = await setup();
    const chip = screen.getByRole('button', { name: 'Board: Studierendenparlament' });
    expect(chip).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(chip);
    await flush();
    expect(chip).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('group', { name: 'Board wählen' })).toBeInTheDocument();
    expect(screen.getByText('Persönlich')).toBeInTheDocument();
    expect(screen.getByText('Gremien')).toBeInTheDocument();
    expect(screen.getByText('Team')).toBeInTheDocument();
    expect(screen.getByText('1 offen · nur du')).toBeInTheDocument();
    expect(screen.getByText('6 offen · für ticket.manage')).toBeInTheDocument();
    expect(screen.getByText('4 offen')).toBeInTheDocument();
    const current = screen.getByRole('button', { name: /^Studierendenparlament/ });
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(document.activeElement).toBe(current);
    expect(BOARD_ICON.team).toBe('ticket');
  });

  /** "Alle" counts the open cards of every board: 1 + 2 + 4 + 6. */
  it('lists the meta-board "Alle" directly under "Meine To-Dos" and picks it', async () => {
    const { picked, flush } = await setup({ allId: 'alle' });
    fireEvent.click(screen.getByRole('button', { name: /Board:/ }));
    await flush();
    const rows = Array.from(document.querySelectorAll<HTMLElement>('.bp__row'));
    expect(rows[0].textContent).toContain('Meine To-Dos');
    expect(rows[1]).toBe(screen.getByTestId('bp-all'));
    expect(rows[1].textContent).toContain('Alle');
    expect(rows[1].textContent).toContain('13 offen');
    expect(rows[1].textContent).not.toContain('alle Boards');
    expect(rows[1]).not.toHaveAttribute('aria-current');
    fireEvent.click(rows[1]);
    expect(picked).toHaveBeenCalledWith('alle');
    expect(ALL_ICON).toBe('grid');
  });

  /** Without an id the meta-board is not offered. */
  it('names "Alle" in the chip when it is the current one, also without a personal board', async () => {
    const { picked, flush, fixture } = await setup({ allId: 'alle', current: 'alle', boards: BOARDS.slice(1) });
    const chip = screen.getByRole('button', { name: 'Board: Alle' });
    fireEvent.click(chip);
    await flush();
    expect(screen.getByText('Persönlich')).toBeInTheDocument();
    const all = screen.getByTestId('bp-all');
    expect(all).toHaveAttribute('aria-current', 'true');
    fireEvent.click(all);
    expect(picked).not.toHaveBeenCalled();
    fixture.componentRef.setInput('compact', true);
    await flush();
    expect(screen.getByRole('button', { name: 'Alle' })).toBeInTheDocument();
    fixture.componentRef.setInput('allId', null);
    fixture.componentInstance.pickAll();
    expect(picked).not.toHaveBeenCalled();
  });

  it('picks another board, and the current one only closes', async () => {
    const { picked, cmp, flush } = await setup();
    fireEvent.click(screen.getByRole('button', { name: /Board:/ }));
    await flush();
    fireEvent.click(screen.getByRole('button', { name: /^Studierendenparlament/ }));
    expect(picked).not.toHaveBeenCalled();
    expect(cmp.open()).toBe(false);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Board:/ }));
    fireEvent.click(screen.getByRole('button', { name: /Board:/ }));
    fireEvent.click(screen.getByRole('button', { name: /^Fachschaft Informatik/ }));
    expect(picked).toHaveBeenCalledWith('b-2');
  });

  /** When closed, Escape and the arrows do nothing. */
  it('moves with the arrows and closes with Escape and a click outside', async () => {
    const { cmp, flush, fixture } = await setup();
    const chip = screen.getByRole('button', { name: /Board:/ });
    fireEvent.click(chip);
    await flush();
    const rows = Array.from(document.querySelectorAll<HTMLElement>('.bp__row'));
    fireEvent.keyDown(rows[1], { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rows[2]);
    fireEvent.keyDown(rows[2], { key: 'ArrowDown' });
    fireEvent.keyDown(rows[3], { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rows[3]);
    fireEvent.keyDown(rows[3], { key: 'ArrowUp' });
    expect(document.activeElement).toBe(rows[2]);
    rows[0].focus();
    fireEvent.keyDown(rows[0], { key: 'ArrowUp' });
    expect(document.activeElement).toBe(rows[0]);
    fireEvent.keyDown(rows[0], { key: 'Tab' });
    fireEvent.keyDown(rows[0], { key: 'Escape' });
    expect(cmp.open()).toBe(false);
    expect(document.activeElement).toBe(chip);
    fireEvent.keyDown(chip, { key: 'Escape' });
    fireEvent.keyDown(chip, { key: 'ArrowDown' });
    expect(cmp.open()).toBe(false);

    fireEvent.click(chip);
    fixture.detectChanges();
    fireEvent.pointerDown(rows[0].isConnected ? document.querySelector('.bp__row')! : chip);
    expect(cmp.open()).toBe(true);
    fireEvent.pointerDown(document.body);
    expect(cmp.open()).toBe(false);
    fireEvent.pointerDown(document.body);
    expect(cmp.open()).toBe(false);
  });

  it('asks for a board without a current one and is short when compact', async () => {
    const none = await setup({ current: 'nope', boards: [BOARDS[0]] });
    expect(screen.getByRole('button', { name: 'Board wählen' })).toBeInTheDocument();
    expect(none.cmp.chipIcon()).toBe('landmark');
    fireEvent.click(screen.getByRole('button', { name: 'Board wählen' }));
    await none.flush();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /^Meine To-Dos/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Board wählen' }));
    none.fixture.componentRef.setInput('current', 'b-0');
    none.fixture.componentRef.setInput('compact', true);
    none.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Meine To-Dos' })).toBeInTheDocument();
    expect(none.cmp.sections().map((s) => s.kind)).toEqual(['personal']);
  });

  it('opens an empty list without a focus target', async () => {
    const { flush, cmp } = await setup({ boards: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Board wählen' }));
    await flush();
    expect(cmp.open()).toBe(true);
    fireEvent.keyDown(screen.getByRole('button', { name: 'Board wählen' }), { key: 'ArrowDown' });
    expect(cmp.sections()).toEqual([]);
  });

  /** A tap outside does not close the sheet; the sheet closes itself. */
  it('uses the bottom sheet on the phone', async () => {
    asPhone(MEDIA.phone);
    const { cmp, picked, fixture } = await setup();
    fireEvent.click(screen.getByRole('button', { name: /Board:/ }));
    fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Board wählen' })).toBeInTheDocument();
    expect(document.querySelector('.bp__pop')).toBeNull();
    fireEvent.pointerDown(document.body);
    expect(cmp.open()).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /^Fachschaft Informatik/ }));
    expect(picked).toHaveBeenCalledWith('b-2');
    cmp.open.set(true);
    fixture.detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(cmp.open()).toBe(false);
  });
});
