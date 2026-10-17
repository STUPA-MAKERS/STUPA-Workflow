import { CdkDrag, CdkDropList, type CdkDragDrop } from '@angular/cdk/drag-drop';
import { By } from '@angular/platform-browser';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import type { TodoBoard } from '@core/api/todos.service';
import { DROP_ENTER, cardsOf } from '../../../features/todos/todos.util';
import { TODAY, board, tile } from '../../../../testing/todo-fixtures';
import { LONG_PRESS_MS } from '@shared/long-press.directive';
import { DONE_PREVIEW, TodoBoardViewComponent } from './todo-board-view.component';

const OUTPUTS = ['openCard', 'menu', 'moveCard', 'dropIn', 'quickAdd', 'addIn', 'settings', 'archive'] as const;

function mapOf(b: TodoBoard) {
  return new Map(b.columns.map((c) => [c.id, cardsOf(b, c.id)]));
}

async function setup(b: TodoBoard = board(), extra: { phone?: boolean; connectTo?: string[] } = {}) {
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

/**
 * Space on a tile as Firefox does it: the keydown on the focused button, then the keyup,
 * and the keyup clicks the button unless a handler prevented it.
 */
function firefoxSpace(title: string): void {
  const button = screen.getByRole('button', { name: title });
  fireEvent.keyDown(button, { key: ' ' });
  const target = screen.getByRole('button', { name: title });
  const up = new KeyboardEvent('keyup', { key: ' ', bubbles: true, cancelable: true });
  target.dispatchEvent(up);
  if (!up.defaultPrevented) target.click();
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
    expect(screen.queryByRole('button', { name: /To-Do hinzufügen/ })).toBeNull();
    const { item } = { item: screen.getByRole('button', { name: 'Raum buchen' }).closest('.bv__item') as HTMLElement };
    fireEvent.keyDown(item, { key: ' ' });
    expect(cmp.kb()).toBeNull();
  });

  it('adds a card with a quick title: Enter, Escape and the buttons', async () => {
    const { cmp, on, fixture } = await setup();
    fireEvent.click(screen.getAllByRole('button', { name: /To-Do hinzufügen/ })[0]);
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
  });

  it('has no quick field in the done column', async () => {
    await setup();
    expect(screen.getAllByRole('button', { name: /To-Do hinzufügen/ })).toHaveLength(3);
  });

  it('moves the column counts with a pointer drag', async () => {
    const { cmp } = await setup();
    const [open, doing, , done] = cmp.columns();
    const before = [open, doing, done].map((c) => cmp.count(c));
    cmp.onEnter({ container: { data: doing.id } } as never);
    expect(cmp.ptr()).toBeNull();
    cmp.onDragStart(open);
    expect(cmp.count(open)).toBe(before[0]);
    cmp.onEnter({ container: { data: doing.id } } as never);
    expect(cmp.count(open)).toBe(before[0] - 1);
    expect(cmp.count(doing)).toBe(before[1] + 1);
    expect(cmp.count(done)).toBe(before[2]);
    expect(cmp.more(done)).toBe(Math.max(0, before[2] - DONE_PREVIEW));
    cmp.ptr.set(null);
    expect(cmp.count(open)).toBe(before[0]);
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
    cmp.drop(dropEvent('ghost', 'x-1', 'nope', 0, 0));
    expect(on.moveCard).toHaveBeenCalledTimes(calls);
    expect(on.dropIn).not.toHaveBeenCalled();
  });

  it('hands a card of another board to the page with the neighbours of its place', async () => {
    const { cmp, on, fixture } = await setup(board(), { connectTo: ['br-list-x-1'] });
    cmp.drop(dropEvent('ghost', 'x-1', 'c-1', 0, 1));
    expect(on.dropIn).toHaveBeenLastCalledWith({ cardId: 'ghost', move: { columnId: 'c-1', afterId: 'k-1' } });
    cmp.drop(dropEvent('ghost', 'x-1', 'c-2', 0, 0));
    expect(on.dropIn).toHaveBeenLastCalledWith({ cardId: 'ghost', move: { columnId: 'c-2' } });
    expect(on.moveCard).not.toHaveBeenCalled();
    // Every list of a writable board reaches the rows; a read-only board reaches none.
    const lists = fixture.debugElement.queryAll(By.directive(CdkDropList)).map((d) => d.injector.get(CdkDropList));
    expect(lists.every((l) => (l.connectedTo as string[]).includes('br-list-x-1'))).toBe(true);
    fixture.componentRef.setInput('board', board({ canWrite: false }));
    fixture.detectChanges();
    const ro = fixture.debugElement.queryAll(By.directive(CdkDropList)).map((d) => d.injector.get(CdkDropList));
    expect(ro.every((l) => (l.connectedTo as string[]).length === 0)).toBe(true);
  });

  it('lets no card of a shared board into a column of the personal board', async () => {
    const lists = async (b: TodoBoard) => {
      const { fixture } = await setup(b, { connectTo: ['br-list-x-1'] });
      return fixture.debugElement.queryAll(By.directive(CdkDropList)).map((d) => d.injector.get(CdkDropList));
    };
    const from = (kind: string) => {
      const el = document.createElement('div');
      el.dataset['boardKind'] = kind;
      return { dropContainer: { element: { nativeElement: el } } } as unknown as CdkDrag;
    };
    const personal = await lists(board({ kind: 'personal', gremiumId: null }));
    expect(personal.every((l) => l.element.nativeElement.dataset['boardKind'] === 'personal')).toBe(true);
    expect(personal[0].enterPredicate(from('gremium'), personal[0])).toBe(false);
    expect(personal[0].enterPredicate(from('team'), personal[0])).toBe(false);
    expect(personal[0].enterPredicate(from('personal'), personal[0])).toBe(true);
    // A gremium board lets a card of the personal board in.
    const gremium = DROP_ENTER.gremium;
    expect(gremium(from('personal'))).toBe(true);
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
    expect(cmp.count(cmp.columns()[0])).toBe(1);
    expect(cmp.count(cmp.columns()[1])).toBe(1);
    await key('Raum buchen', 'x');
    await key('Raum buchen', 'Enter');
    expect(on.moveCard).toHaveBeenCalledWith({ cardId: 'k-1', move: { columnId: 'c-2' } });
    expect(container.querySelector('[aria-live]')).toHaveTextContent('„Raum buchen“ abgelegt in In Arbeit.');
    expect(cmp.kb()).toBeNull();
  });

  it('lifts and puts down a card with Space without opening it, as Firefox clicks on keyup', async () => {
    const { cmp, on, fixture } = await setup();
    firefoxSpace('Raum buchen');
    fixture.detectChanges();
    expect(cmp.kb()).toMatchObject({ cardId: 'k-1' });
    expect(on.openCard).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Raum buchen' }), { key: 'ArrowDown' });
    fixture.detectChanges();
    firefoxSpace('Raum buchen');
    fixture.detectChanges();
    expect(cmp.kb()).toBeNull();
    expect(on.moveCard).toHaveBeenCalled();
    expect(on.openCard).not.toHaveBeenCalled();
    // A Space keyup without a drag still clicks the tile.
    fireEvent.click(screen.getByRole('button', { name: 'Raum buchen' }));
    expect(on.openCard).toHaveBeenCalledWith('k-1');
  });

  it('lifts a card by touch only after a long press, so a swipe over the board scrolls', async () => {
    const { fixture } = await setup();
    const drags = fixture.debugElement.queryAll(By.directive(CdkDrag));
    expect(drags.length).toBeGreaterThan(0);
    for (const d of drags) expect(d.injector.get(CdkDrag).dragStartDelay).toEqual({ touch: 400, mouse: 0 });
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

  it('ends a keyboard drag when the focus or a pointer goes elsewhere', async () => {
    const { cmp, on, key, fixture, container } = await setup();
    const elsewhere = document.createElement('button');
    document.body.appendChild(elsewhere);
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'ArrowRight');
    expect(cmp.count(cmp.columns()[1])).toBe(1);
    // The refocus after the step lands in the held card and keeps the drag.
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Raum buchen' }));
    expect(cmp.kb()).not.toBeNull();
    elsewhere.focus();
    fixture.detectChanges();
    expect(cmp.kb()).toBeNull();
    expect(cmp.count(cmp.columns()[0])).toBe(2);
    expect(cmp.count(cmp.columns()[1])).toBe(0);
    expect(container.querySelector('[aria-live]')).toHaveTextContent('Verschieben von „Raum buchen“ abgebrochen.');

    await key('Raum buchen', ' ');
    // A pointer on the held card keeps the drag, one on another card ends it.
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Raum buchen' }));
    expect(cmp.kb()).not.toBeNull();
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Haushalt Kapitel 3' }));
    expect(cmp.kb()).toBeNull();
    // Without a drag a pointer or a focus changes nothing.
    fireEvent.pointerDown(document.body);
    expect(on.moveCard).not.toHaveBeenCalled();
    elsewhere.remove();
  });

  it('ends a keyboard drag when a pointer drag starts', async () => {
    const { cmp, key } = await setup();
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'ArrowDown');
    cmp.onDragStart(cmp.columns()[0]);
    expect(cmp.kb()).toBeNull();
    expect(cmp.list(cmp.columns()[0]).map((c) => c.id)).toEqual(['k-1', 'k-2']);
    // A held card that the board no longer holds ends without an announcement.
    cmp.kb.set({ cardId: 'gone', col: 0, index: 0, fromCol: 0, fromIndex: 0 });
    cmp.onDragStart(cmp.columns()[0]);
    expect(cmp.kb()).toBeNull();
  });

  it('marks the board as a scroll container for the drag', async () => {
    const { container } = await setup();
    expect(container.querySelector('.bv')).toHaveAttribute('cdkScrollable');
  });

  it('fills the page by default and takes its natural height when fill is off', async () => {
    const { fixture } = await setup();
    const host = fixture.nativeElement as HTMLElement;
    expect(host).not.toHaveClass('bv-host--natural');
    fixture.componentRef.setInput('fill', false);
    fixture.detectChanges();
    expect(host).toHaveClass('bv-host--natural');
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
    function press(title: string): void {
      const button = screen.getByRole('button', { name: title });
      button.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
      jest.advanceTimersByTime(LONG_PRESS_MS);
      button.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }));
      button.click();
    }

    it('asks for the "Verschieben" sheet on a long press and does not open the card', async () => {
      const { on, container } = await setup(board(), { phone: true });
      expect(container.querySelector('.bv__page')).toHaveAttribute('appScrollFade', 'y');
      jest.useFakeTimers();
      try {
        press('Raum buchen');
        expect(on.menu).toHaveBeenCalledWith(
          expect.objectContaining({ boardId: 'b-1', boardKind: 'gremium', card: expect.objectContaining({ id: 'k-1' }) }),
        );
        expect(on.menu.mock.calls[0][0].columns.map((c: { id: string }) => c.id)).toEqual(['c-1', 'c-2', 'c-3', 'c-4']);
        expect(on.openCard).not.toHaveBeenCalled();
        // A swipe over the tile is no long press.
        const button = screen.getByRole('button', { name: 'Raum buchen' });
        button.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 0 }));
        button.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 40 }));
        jest.advanceTimersByTime(LONG_PRESS_MS);
        expect(on.menu).toHaveBeenCalledTimes(1);
      } finally {
        jest.useRealTimers();
      }
    });

    it('has no long press on a read-only board', async () => {
      const { on } = await setup(board({ canWrite: false }), { phone: true });
      jest.useFakeTimers();
      try {
        press('Raum buchen');
        expect(on.menu).not.toHaveBeenCalled();
        expect(on.openCard).toHaveBeenCalledWith('k-1');
      } finally {
        jest.useRealTimers();
      }
    });

    it('shows one column behind tabs with the ink, and its cards', async () => {
      const { cmp, on, fixture, container } = await setup(board(), { phone: true });
      expect(screen.getAllByRole('tab').map((t) => t.textContent?.replace(/\s+/g, '').trim())).toEqual([
        'Offen2',
        'InArbeit0',
        'Wartet0',
        'Erledigt1',
      ]);
      expect(within(screen.getByRole('list', { name: 'Offen' })).getAllByRole('listitem')).toHaveLength(2);
      expect(container.querySelector('.bv__ink')).not.toBeNull();
      expect(container.querySelector('.bv__dots')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'Haushalt Kapitel 3' }));
      expect(on.openCard).toHaveBeenCalledWith('k-2');
      // Every column is a page of the pager; an empty one says so.
      expect(container.querySelectorAll('.bv__page')).toHaveLength(4);
      expect(container.querySelectorAll('.bv__page--empty')).toHaveLength(2);
      expect(screen.getAllByText('Keine Karten')).toHaveLength(2);
      cmp.selectPhoneColumn('c-2');
      fixture.detectChanges();
      expect(screen.getByRole('tab', { name: /In Arbeit/ })).toHaveAttribute('aria-selected', 'true');
      cmp.selectPhoneColumn('nope');
      cmp.selectPhoneColumn(null);
      expect(cmp.phoneCol()?.id).toBe('c-2');
      // No keyboard drag on the phone.
      cmp.onTileKey(new KeyboardEvent('keydown', { key: ' ' }), tile(), 0, 0);
      expect(cmp.kb()).toBeNull();
    });

    it('opens the rest of the done column', async () => {
      const done = Array.from({ length: 5 }, (_, i) => tile({ id: `d-${i}`, columnId: 'c-4', title: `Fertig ${i}` }));
      const one = board({
        cards: done,
        columns: [{ id: 'c-4', name: 'Erledigt', position: 0, isDone: true, cardCount: 0 }],
      });
      const { fixture } = await setup(one, { phone: true });
      fireEvent.click(screen.getByRole('button', { name: '2 weitere' }));
      fixture.detectChanges();
      expect(within(screen.getByRole('list', { name: 'Erledigt' })).getAllByRole('listitem')).toHaveLength(5);
    });

    it('scrolls the pager to a tapped tab and follows a swipe', async () => {
      const { cmp, fixture, container } = await setup(board(), { phone: true });
      const pager = container.querySelector('.bv__pager') as HTMLElement;
      Object.defineProperty(pager, 'clientWidth', { configurable: true, value: 390 });
      const scrollTo = jest.fn();
      pager.scrollTo = scrollTo as unknown as typeof pager.scrollTo;
      cmp.selectPhoneColumn('c-3');
      expect(scrollTo).toHaveBeenCalledWith({ left: 780, behavior: 'smooth' });
      // On the way to a tapped tab, the tabs between do not light up.
      pager.scrollLeft = 390;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-3');
      pager.scrollLeft = 780;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-3');
      // A swipe: the tab changes at the half way and clamps to the last page.
      pager.scrollLeft = 900;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-3');
      pager.scrollLeft = 1000;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-4');
      pager.scrollLeft = 5000;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-4');
      fixture.detectChanges();
      expect(screen.getByRole('tab', { name: /Erledigt/ })).toHaveAttribute('aria-selected', 'true');
      // A finger on the pager ends the way to a tapped tab.
      cmp.selectPhoneColumn('c-1');
      fireEvent.pointerDown(pager);
      pager.scrollLeft = 400;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-2');
      // A scroll that comes to rest ends the hold of a tapped tab, wherever it rests.
      cmp.selectPhoneColumn('c-4');
      pager.scrollLeft = 790;
      pager.dispatchEvent(new Event('scrollend'));
      expect(cmp.phoneCol()?.id).toBe('c-3');
      // A tab whose page is already there scrolls nothing and holds nothing.
      cmp.selectPhoneColumn('c-3');
      pager.scrollLeft = 400;
      fireEvent.scroll(pager);
      expect(cmp.phoneCol()?.id).toBe('c-2');
      // Without a laid-out pager nothing moves.
      Object.defineProperty(pager, 'clientWidth', { configurable: true, value: 0 });
      cmp.syncPage();
      cmp.selectPhoneColumn('c-1');
      expect(cmp.phoneCol()?.id).toBe('c-1');
      expect(scrollTo).toHaveBeenCalledTimes(3);
    });

    it('jumps without animation under reduced motion and right to left', async () => {
      const { cmp, container } = await setup(board(), { phone: true });
      const pager = container.querySelector('.bv__pager') as HTMLElement;
      Object.defineProperty(pager, 'clientWidth', { configurable: true, value: 300 });
      pager.style.direction = 'rtl';
      const scrollTo = jest.fn();
      pager.scrollTo = scrollTo as unknown as typeof pager.scrollTo;
      const mm = window.matchMedia;
      window.matchMedia = ((q: string) => ({ matches: q.includes('reduce') })) as unknown as typeof window.matchMedia;
      try {
        cmp.selectPhoneColumn('c-2');
      } finally {
        window.matchMedia = mm;
      }
      expect(scrollTo).toHaveBeenCalledWith({ left: -300, behavior: 'auto' });
      pager.scrollLeft = -300;
      cmp.syncPage();
      pager.scrollLeft = -600;
      cmp.syncPage();
      expect(cmp.phoneCol()?.id).toBe('c-3');
    });

    it('moves the ink between two tabs while the pager is between two pages', async () => {
      const { container } = await setup(board(), { phone: true });
      const bar = container.querySelector('.bv__tabBar') as HTMLElement;
      const ink = container.querySelector('.bv__ink') as HTMLElement;
      const pager = container.querySelector('.bv__pager') as HTMLElement;
      const rect = (left: number, width: number) =>
        ({ left, right: left + width, width, top: 0, bottom: 44, height: 44 }) as DOMRect;
      bar.getBoundingClientRect = () => rect(16, 380);
      const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));
      tabs.forEach((t, i) => (t.getBoundingClientRect = () => rect(16 + i * 100, 60 + i * 20)));
      const strip = container.querySelector('[role="tablist"]') as HTMLElement;
      strip.getBoundingClientRect = () => rect(16, 380);
      strip.scrollBy = jest.fn() as unknown as typeof strip.scrollBy;
      Object.defineProperty(pager, 'clientWidth', { configurable: true, value: 400 });
      const frame = jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
        cb(0);
        return 1;
      });
      try {
        pager.scrollLeft = 200;
        fireEvent.scroll(pager);
        expect(ink.style.transform).toBe('translateX(50px)');
        expect(ink.style.width).toBe('70px');
        // Past the last page the ink stays under the last tab.
        pager.scrollLeft = 4000;
        fireEvent.scroll(pager);
        expect(ink.style.transform).toBe('translateX(300px)');
        expect(ink.style.width).toBe('120px');
      } finally {
        frame.mockRestore();
      }
    });

    it('shows the active tab when the tab bar is wider than the screen', async () => {
      const { cmp, fixture, container } = await setup(board(), { phone: true });
      const strip = container.querySelector('[role="tablist"]') as HTMLElement;
      const rect = (left: number, width: number) =>
        ({ left, right: left + width, width, top: 0, bottom: 44, height: 44 }) as DOMRect;
      strip.getBoundingClientRect = () => rect(0, 300);
      const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));
      tabs.forEach((t, i) => (t.getBoundingClientRect = () => rect(-150 + i * 160, 120)));
      const scrollBy = jest.fn();
      strip.scrollBy = scrollBy as unknown as typeof strip.scrollBy;
      // c-1 starts left of the strip, c-4 ends right of it, c-2 lies inside.
      cmp.selectPhoneColumn('c-4');
      fixture.detectChanges();
      await fixture.whenStable();
      expect(scrollBy).toHaveBeenLastCalledWith({ left: 150, behavior: 'smooth' });
      cmp.selectPhoneColumn('c-1');
      fixture.detectChanges();
      await fixture.whenStable();
      expect(scrollBy).toHaveBeenLastCalledWith({ left: -150, behavior: 'smooth' });
      scrollBy.mockClear();
      cmp.selectPhoneColumn('c-2');
      fixture.detectChanges();
      await fixture.whenStable();
      expect(scrollBy).not.toHaveBeenCalled();
    });

    it('places the ink again once the web fonts are in', async () => {
      let loaded = (): void => undefined;
      const ready = new Promise<void>((resolve) => (loaded = resolve));
      Object.defineProperty(document, 'fonts', { configurable: true, value: { ready } });
      try {
        const { cmp } = await setup(board(), { phone: true });
        const place = jest.spyOn(cmp, 'placeInk');
        loaded();
        await ready;
        await Promise.resolve();
        expect(place).toHaveBeenCalled();
      } finally {
        delete (document as { fonts?: unknown }).fonts;
      }
    });

    it('stops a pending ink frame when it goes away', async () => {
      const { container, fixture } = await setup(board(), { phone: true });
      const cancel = jest.spyOn(window, 'cancelAnimationFrame');
      fireEvent.scroll(container.querySelector('.bv__pager') as HTMLElement);
      fixture.destroy();
      expect(cancel).toHaveBeenCalled();
      cancel.mockRestore();
    });

    it('shows nothing for a board without columns', async () => {
      const { cmp, container } = await setup(board({ columns: [], cards: [] }), { phone: true });
      expect(cmp.phoneCol()).toBeNull();
      expect(container.querySelector('.bv__phoneCards')).toBeNull();
    });
  });
});
