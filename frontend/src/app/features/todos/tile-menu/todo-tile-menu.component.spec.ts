import { fireEvent, render, screen, within } from '@testing-library/angular';
import { board, tile } from '../../../../testing/todo-fixtures';
import { TodoTileMenuComponent, type TileMenuRequest } from './todo-tile-menu.component';

function request(over: Partial<TileMenuRequest> = {}): TileMenuRequest {
  const b = board();
  return { card: tile({ columnId: b.columns[0].id }), boardId: b.id, boardKind: b.kind, columns: b.columns, ...over };
}

async function setup(req: TileMenuRequest | null = request()) {
  const column = jest.fn();
  const transfer = jest.fn();
  const view = await render(TodoTileMenuComponent, {
    inputs: { open: true, request: req },
    on: { column, transfer },
  });
  return { ...view, column, transfer };
}

describe('TodoTileMenuComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('marks the column of the card and moves to another one', async () => {
    const req = request();
    const { column, fixture } = await setup(req);
    const sheet = screen.getByRole('dialog', { name: 'Verschieben' });
    expect(within(sheet).getByText(req.card.title)).toBeInTheDocument();
    const here = within(sheet).getByRole('button', { name: req.columns[0].name });
    expect(here).toBeDisabled();
    expect(here).toHaveAttribute('aria-current', 'true');
    fixture.componentInstance.pick(req.columns[0]);
    expect(column).not.toHaveBeenCalled();
    fireEvent.click(within(sheet).getByRole('button', { name: req.columns[1].name }));
    expect(column).toHaveBeenCalledWith(req.columns[1].id);
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('opens the transfer from below the line', async () => {
    const { transfer, fixture } = await setup();
    expect(document.querySelector('.tm__sep')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'In anderes Board verschieben' }));
    expect(transfer).toHaveBeenCalled();
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('has no line without columns', async () => {
    await setup(request({ columns: [] }));
    expect(document.querySelector('.tm__sep')).toBeNull();
    expect(screen.getByRole('button', { name: 'In anderes Board verschieben' })).toBeInTheDocument();
  });

  it('shows nothing without a request', async () => {
    await setup(null);
    expect(document.querySelector('.tm')).toBeNull();
  });
});
