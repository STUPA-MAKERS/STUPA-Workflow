import type { CdkDragDrop } from '@angular/cdk/drag-drop';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import type { TodoBoard } from '@core/api/todos.service';
import { cardsOf } from '../../../features/todos/todos.util';
import { TODAY, board, tile } from '../../../../testing/todo-fixtures';
import { DONE_PREVIEW, TodoBoardViewComponent } from './todo-board-view.component';

const OUTPUTS = ['openCard', 'moveCard', 'quickAdd', 'addIn', 'settings', 'archive'] as const;

function mapOf(b: TodoBoard) {
  return new Map(b.columns.map((c) => [c.id, cardsOf(b, c.id)]));
}

async function setup(b: TodoBoard = board(), extra: { phone?: boolean } = {}) {
  const on = Object.fromEntries(OUTPUTS.map((n) => [n, jest.fn()])) as Record<(typeof OUTPUTS)[number], jest.Mock>;
  const view = await render(TodoBoardViewComponent, {
    inputs: { board: b, cards: mapOf(b), labels: new Map(b.labels.map((l) => [l.id, l])), today: TODAY, ...extra },
    on,
  });
  const cmp = view.fixture.componentInstance;
  const item = (title: string) => screen.getByRole('button', { name: title }).closest('.bv__item') as HTMLElement;
  const key = async (title: string, k: string, opts: Record<string, unknown> = {}) => {
    fireEvent.keyDown(item(title), { key: k, ...opts });
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  return { ...view, on, cmp, item, key };
}

function dropEvent(cardId: string, from: string, to: string, previousIndex: number, currentIndex: number) {
  return {
    item: { data: cardId },
    container: { data: to },
    previousContainer: { data: from },
    previousIndex,
    currentIndex,
  } as unknown as CdkDragDrop<string>;
}

describe('TodoBoardViewComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the columns with their counts, the done tag and the cards', async () => {
    const { on } = await setup();
    const open = screen.getByRole('heading', { name: /^Offen/ });
    expect(open).toHaveTextContent('2');
    expect(screen.getByText('Erledigt-Spalte')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Offen' })).getAllByRole('listitem')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Raum buchen' }));
    expect(on.openCard).toHaveBeenCalledWith('k-1');
  });

  it('shows the newest done cards and opens the rest and the archive', async () => {
    const done = Array.from({ length: DONE_PREVIEW + 2 }, (_, i) => tile({ id: `d-${i}`, columnId: 'c-4', title: `Fertig ${i}` }));
    const { on, cmp, fixture } = await setup(board({ cards: done, archivedCount: 4 }));
    expect(within(screen.getByRole('list', { name: 'Erledigt' })).getAllByRole('listitem')).toHaveLength(DONE_PREVIEW);
    fireEvent.click(screen.getByRole('button', { name: 'Archiv' }));
    expect(on.archive).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '2 weitere' }));
    fixture.detectChanges();
    expect(within(screen.getByRole('list', { name: 'Erledigt' })).getAllByRole('listitem')).toHaveLength(5);
    expect(cmp.more(cmp.columns()[3])).toBe(0);
    expect(screen.queryByRole('button', { name: /weitere/ })).toBeNull();
  });

  it('offers the column menu by right and runs its items', async () => {
    const { cmp, on } = await setup(board({ archivedCount: 2 }));
    const [first, , , done] = cmp.columns();
    expect(cmp.columnMenu(first)[0].items.map((i) => i.id)).toEqual(['add', 'settings']);
    expect(cmp.columnMenu(done)[0].items.map((i) => i.id)).toEqual(['add', 'settings', 'archive']);
    cmp.onColumnMenu(first, { id: 'add', label: '' });
    expect(on.addIn).toHaveBeenCalledWith('c-1');
    cmp.onColumnMenu(first, { id: 'settings', label: '' });
    expect(on.settings).toHaveBeenCalled();
    cmp.onColumnMenu(done, { id: 'archive', label: '' });
    expect(on.archive).toHaveBeenCalled();
    cmp.onColumnMenu(done, { id: 'odd', label: '' });
    expect(screen.getAllByRole('button', { name: /^Aktionen der Spalte/ })).toHaveLength(4);
  });

  it('reads only without the write right', async () => {
    const { cmp } = await setup(board({ canWrite: false, canConfigure: false }));
    expect(cmp.columnMenu(cmp.columns()[0])).toEqual([]);
    expect(screen.queryByRole('button', { name: /Karte hinzufügen/ })).toBeNull();
    const { item } = { item: screen.getByRole('button', { name: 'Raum buchen' }).closest('.bv__item') as HTMLElement };
    fireEvent.keyDown(item, { key: ' ' });
    expect(cmp.kb()).toBeNull();
  });

  it('adds a card with a quick title: Enter, Escape and the buttons', async () => {
    const { cmp, on, fixture } = await setup();
    fireEvent.click(screen.getAllByRole('button', { name: /Karte hinzufügen/ })[0]);
    fixture.detectChanges();
    await fixture.whenStable();
    const field = screen.getByRole('textbox', { name: 'Titel der neuen Karte in Offen' });
    expect(document.activeElement).toBe(field);
    const col = cmp.columns()[0];
    cmp.submitAdd(col);
    expect(on.quickAdd).not.toHaveBeenCalled();
    cmp.draft.set('  Bus  ');
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true });
    expect(on.quickAdd).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: 'a' });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(on.quickAdd).toHaveBeenCalledWith({ columnId: 'c-1', title: 'Bus' });
    expect(cmp.draft()).toBe('');
    fireEvent.keyDown(field, { key: 'Escape' });
    expect(cmp.adding()).toBeNull();
    cmp.startAdd(col);
    fixture.detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(cmp.adding()).toBeNull();
  });

  it('turns a pointer drop into a move with one neighbour', async () => {
    const { cmp, on } = await setup();
    cmp.drop(dropEvent('k-1', 'c-1', 'c-1', 0, 0));
    expect(on.moveCard).not.toHaveBeenCalled();
    cmp.drop(dropEvent('k-3', 'c-4', 'c-1', 0, 1));
    expect(on.moveCard).toHaveBeenLastCalledWith({ cardId: 'k-3', move: { columnId: 'c-1', afterId: 'k-1' } });
    cmp.drop(dropEvent('k-2', 'c-1', 'c-1', 1, 0));
    expect(on.moveCard).toHaveBeenLastCalledWith({ cardId: 'k-2', move: { columnId: 'c-1', beforeId: 'k-1' } });
    cmp.drop(dropEvent('k-1', 'c-1', 'c-2', 0, 0));
    expect(on.moveCard).toHaveBeenLastCalledWith({ cardId: 'k-1', move: { columnId: 'c-2' } });
    const calls = on.moveCard.mock.calls.length;
    cmp.drop(dropEvent('k-1', 'c-1', 'nope', 0, 0));
    cmp.drop(dropEvent('ghost', 'c-1', 'c-2', 0, 0));
    expect(on.moveCard).toHaveBeenCalledTimes(calls);
  });

  it('drags with the keyboard inside and between columns and announces each step', async () => {
    const { cmp, on, key, container } = await setup();
    await key('Raum buchen', 'a');
    expect(cmp.kb()).toBeNull();
    await key('Raum buchen', ' ');
    expect(cmp.kb()).toMatchObject({ cardId: 'k-1', col: 0, index: 0 });
    expect(container.querySelector('[aria-live]')).toHaveTextContent('„Raum buchen“ aufgenommen, Spalte Offen, Position 1 von 2.');
    expect(screen.getByRole('button', { name: 'Raum buchen' }).closest('app-todo-card-tile')).toHaveClass('tt--lifted');
    // Another card ignores the keys while one is held.
    await key('Haushalt Kapitel 3', 'ArrowDown');
    expect(cmp.kb()?.index).toBe(0);
    await key('Raum buchen', 'ArrowDown');
    expect(cmp.kb()?.index).toBe(1);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Raum buchen' }));
    await key('Raum buchen', 'ArrowDown');
    expect(cmp.kb()?.index).toBe(1);
    await key('Raum buchen', 'ArrowUp');
    await key('Raum buchen', 'ArrowUp');
    expect(cmp.kb()?.index).toBe(0);
    await key('Raum buchen', 'ArrowLeft');
    expect(cmp.kb()?.col).toBe(0);
    await key('Raum buchen', 'ArrowRight');
    expect(cmp.kb()).toMatchObject({ col: 1, index: 0 });
    expect(container.querySelector('[aria-live]')).toHaveTextContent('Spalte In Arbeit, Position 1 von 1.');
    await key('Raum buchen', 'x');
    await key('Raum buchen', 'Enter');
    expect(on.moveCard).toHaveBeenCalledWith({ cardId: 'k-1', move: { columnId: 'c-2' } });
    expect(container.querySelector('[aria-live]')).toHaveTextContent('„Raum buchen“ abgelegt in In Arbeit.');
    expect(cmp.kb()).toBeNull();
  });

  it('lets Tab leave a held card: the drag ends and the focus is not pulled back', async () => {
    const { cmp, key } = await setup();
    await key('Raum buchen', ' ');
    const elsewhere = document.createElement('button');
    document.body.appendChild(elsewhere);
    // The browser moves the focus on before the drag ends.
    const card = screen.getByRole('button', { name: 'Raum buchen' });
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    card.dispatchEvent(tab);
    elsewhere.focus();
    await key('Haushalt Kapitel 3', 'a');
    expect(cmp.kb()).toBeNull();
    expect(tab.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(elsewhere);
    elsewhere.remove();
  });

  it('marks the board as a scroll container for the drag', async () => {
    const { container } = await setup();
    expect(container.querySelector('.bv')).toHaveAttribute('cdkScrollable');
  });

  it('puts the card back when it ends where it started, on Escape and on Tab', async () => {
    const { cmp, on, key, container } = await setup();
    await key('Raum buchen', ' ');
    await key('Raum buchen', ' ');
    expect(on.moveCard).not.toHaveBeenCalled();
    expect(container.querySelector('[aria-live]')).toHaveTextContent('Verschieben von „Raum buchen“ abgebrochen.');
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'Escape');
    expect(cmp.kb()).toBeNull();
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'Tab');
    expect(cmp.kb()).toBeNull();
    // Into the done column the whole column shows while the card is held.
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'ArrowRight');
    await key('Raum buchen', 'ArrowRight');
    await key('Raum buchen', 'ArrowRight');
    await key('Raum buchen', 'ArrowRight');
    expect(cmp.kb()?.col).toBe(3);
    await key('Raum buchen', 'ArrowDown');
    await key('Raum buchen', ' ');
    expect(on.moveCard).toHaveBeenCalledWith({ cardId: 'k-1', move: { columnId: 'c-4', afterId: 'k-3' } });
  });

  it('moves into a column that the filters left out of the map', async () => {
    const b = board();
    const { cmp, fixture, key } = await setup(b);
    fixture.componentRef.setInput('cards', new Map([['c-1', cardsOf(b, 'c-1')]]));
    fixture.detectChanges();
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'ArrowRight');
    expect(cmp.kb()).toMatchObject({ col: 1, index: 0 });
  });

  it('ignores a held card that the filters removed', async () => {
    const { cmp, fixture } = await setup();
    cmp.kb.set({ cardId: 'gone', col: 0, index: 0, fromCol: 0, fromIndex: 0 });
    fixture.detectChanges();
    expect(cmp.list(cmp.columns()[0]).map((c) => c.id)).toEqual(['k-1', 'k-2']);
    expect((cmp as unknown as { commit(c: unknown): void }).commit).toBeDefined();
    cmp.kb.set(null);
    (cmp as unknown as { commit(c: unknown): void }).commit(tile());
    expect(cmp.kb()).toBeNull();
  });

  it('counts a column without cards in the map as empty', async () => {
    const b = board();
    const { cmp, fixture } = await setup(b);
    fixture.componentRef.setInput('cards', new Map());
    fixture.detectChanges();
    expect(cmp.count(cmp.columns()[0])).toBe(0);
    expect(cmp.tabs()[0].count).toBe(0);
    expect(cmp.list({ id: 'nope', name: '', position: 9, isDone: false, cardCount: 0 })).toEqual([]);
    expect(cmp.more({ id: 'nope', name: '', position: 9, isDone: false, cardCount: 0 })).toBe(0);
  });

  describe('phone', () => {
    it('shows one column behind tabs, its cards and the dots', async () => {
      const { cmp, on, fixture, container } = await setup(board(), { phone: true });
      expect(screen.getAllByRole('tab').map((t) => t.textContent?.replace(/\s+/g, '').trim())).toEqual([
        'Offen2',
        'InArbeit0',
        'Wartet0',
        'Erledigt1',
      ]);
      expect(within(screen.getByRole('list', { name: 'Offen' })).getAllByRole('listitem')).toHaveLength(2);
      expect(container.querySelectorAll('.bv__dot')).toHaveLength(4);
      fireEvent.click(screen.getByRole('button', { name: 'Haushalt Kapitel 3' }));
      expect(on.openCard).toHaveBeenCalledWith('k-2');
      cmp.selectPhoneColumn('c-2');
      fixture.detectChanges();
      expect(screen.getByText('Keine Karten')).toBeInTheDocument();
      cmp.selectPhoneColumn('nope');
      cmp.selectPhoneColumn(null);
      expect(cmp.phoneCol()?.id).toBe('c-2');
      // No keyboard drag on the phone.
      cmp.onTileKey(new KeyboardEvent('keydown', { key: ' ' }), tile(), 0, 0);
      expect(cmp.kb()).toBeNull();
    });

    it('opens the rest of the done column and has no dots for one column', async () => {
      const done = Array.from({ length: 5 }, (_, i) => tile({ id: `d-${i}`, columnId: 'c-4', title: `Fertig ${i}` }));
      const one = board({
        cards: done,
        columns: [{ id: 'c-4', name: 'Erledigt', position: 0, isDone: true, cardCount: 0 }],
      });
      const { fixture, container } = await setup(one, { phone: true });
      expect(container.querySelector('.bv__dots')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: '2 weitere' }));
      fixture.detectChanges();
      expect(within(screen.getByRole('list', { name: 'Erledigt' })).getAllByRole('listitem')).toHaveLength(5);
    });

    it('shows nothing for a board without columns', async () => {
      const { cmp, container } = await setup(board({ columns: [], cards: [] }), { phone: true });
      expect(cmp.phoneCol()).toBeNull();
      expect(container.querySelector('.bv__phoneCards')).toBeNull();
    });
  });
});
