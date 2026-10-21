import { fireEvent, render, screen } from '@testing-library/angular';
import { TodoMoveSheetComponent, type MoveColumn } from './todo-move-sheet.component';

const COLUMNS: MoveColumn[] = [
  { id: 'c-1', name: 'Offen', count: 5 },
  { id: 'c-2', name: 'In Arbeit', count: 3 },
  { id: 'c-4', name: 'Erledigt', count: null },
];

async function setup(current: string | null = 'c-2', canTransfer = false) {
  const moved = jest.fn();
  const transfer = jest.fn();
  const dismissed = jest.fn();
  const view = await render(TodoMoveSheetComponent, {
    inputs: { open: false, columns: COLUMNS, current, canTransfer },
    on: { moved, transfer, dismissed },
  });
  const openSheet = () => {
    view.fixture.componentRef.setInput('open', true);
    view.fixture.detectChanges();
  };
  return { ...view, moved, transfer, dismissed, openSheet };
}

describe('TodoMoveSheetComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('starts on the column of the card at the top and moves to the chosen place', async () => {
    const { moved, openSheet, fixture } = await setup();
    openSheet();
    expect(screen.getByRole('heading', { name: 'Verschieben' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'In anderes Board verschieben' })).toBeNull();
    expect(screen.getByRole('radio', { name: /In Arbeit/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: /Offen/ })).toHaveTextContent('5');
    expect(screen.getByRole('radio', { name: 'Erledigt' }).querySelector('.ms__count')).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: 'Erledigt' }));
    fixture.componentInstance.setPosition('bottom');
    fixture.detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Verschieben' }));
    expect(moved).toHaveBeenCalledWith({ columnId: 'c-4', position: 'bottom' });
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('opens again at the top, and any other position value means the top', async () => {
    const { openSheet, fixture } = await setup();
    openSheet();
    fixture.componentInstance.setPosition('bottom');
    fixture.componentInstance.setPosition(null);
    expect(fixture.componentInstance.position()).toBe('top');
    fixture.componentInstance.setPosition('bottom');
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    openSheet();
    expect(fixture.componentInstance.position()).toBe('top');
  });

  it('needs a column, and cancel closes without a move', async () => {
    const { moved, openSheet, fixture } = await setup(null);
    openSheet();
    expect(screen.getByRole('button', { name: 'Verschieben' })).toBeDisabled();
    fixture.componentInstance.confirm();
    expect(moved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('offers the other board: the row closes the sheet and emits transfer', async () => {
    const { moved, transfer, dismissed, openSheet, fixture } = await setup('c-2', true);
    openSheet();
    fireEvent.click(screen.getByRole('button', { name: 'In anderes Board verschieben' }));
    expect(transfer).toHaveBeenCalledTimes(1);
    expect(moved).not.toHaveBeenCalled();
    expect(dismissed).not.toHaveBeenCalled();
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('emits dismissed when the sheet closes itself', async () => {
    const { dismissed, openSheet } = await setup();
    openSheet();
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(dismissed).toHaveBeenCalledTimes(1);
  });
});
