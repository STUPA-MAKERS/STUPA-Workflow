import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { KanbanKeyDrag, type KeyDragColumns, type KeyDragPosition } from './kanban-key-drag';

const key = (k: string) => new KeyboardEvent('keydown', { key: k, cancelable: true });
/** Three columns with 3, 1 and 0 cards; the held card counts in its own column. */
const COLS: KeyDragColumns = {
  count: 3,
  length: (col) => [3, 1, 0][col] + 1,
  others: (col) => [3, 1, 0][col],
};
const lift = (): KeyDragPosition => ({ cardId: 'c1', col: 0, index: 1, fromCol: 0, fromIndex: 1 });

describe('KanbanKeyDrag', () => {
  /** Another card does not take keys while one is held. */
  it('lifts a card with Space only', () => {
    const drag = new KanbanKeyDrag<KeyDragPosition>();
    expect(drag.key(key('Enter'), 'c1', lift, COLS)).toEqual({ kind: 'none' });
    const space = key(' ');
    expect(drag.key(space, 'c1', lift, COLS)).toEqual({ kind: 'lift' });
    expect(space.defaultPrevented).toBe(true);
    expect(drag.held()).toMatchObject({ cardId: 'c1', col: 0, index: 1 });
    expect(drag.key(key('ArrowDown'), 'c2', lift, COLS)).toEqual({ kind: 'none' });
  });

  /** Column 1 has one other card, so the card goes to its end. */
  it('moves inside the column and across, and stops at the edges', () => {
    const drag = new KanbanKeyDrag<KeyDragPosition>();
    drag.key(key(' '), 'c1', lift, COLS);
    expect(drag.key(key('ArrowUp'), 'c1', lift, COLS)).toEqual({ kind: 'move' });
    expect(drag.held()?.index).toBe(0);
    drag.key(key('ArrowUp'), 'c1', lift, COLS);
    expect(drag.held()?.index).toBe(0);
    expect(drag.key(key('ArrowLeft'), 'c1', lift, COLS)).toEqual({ kind: 'none' });
    drag.key(key('ArrowDown'), 'c1', lift, COLS);
    drag.key(key('ArrowDown'), 'c1', lift, COLS);
    drag.key(key('ArrowRight'), 'c1', lift, COLS);
    expect(drag.held()).toMatchObject({ col: 1, index: 1 });
    drag.key(key('ArrowRight'), 'c1', lift, COLS);
    expect(drag.held()).toMatchObject({ col: 2, index: 0 });
    expect(drag.key(key('ArrowRight'), 'c1', lift, COLS)).toEqual({ kind: 'none' });
  });

  it('drops with Space or Enter and keeps the card held until the caller ends the drag', () => {
    const drag = new KanbanKeyDrag<KeyDragPosition>();
    drag.key(key(' '), 'c1', lift, COLS);
    drag.key(key('ArrowRight'), 'c1', lift, COLS);
    const step = drag.key(key('Enter'), 'c1', lift, COLS);
    expect(step).toEqual({ kind: 'drop', at: expect.objectContaining({ col: 1, fromCol: 0 }) });
    expect(drag.held()).not.toBeNull();
  });

  it('cancels with Escape (focus stays) and with Tab (focus leaves)', () => {
    const drag = new KanbanKeyDrag<KeyDragPosition>();
    drag.key(key(' '), 'c1', lift, COLS);
    const esc = key('Escape');
    expect(drag.key(esc, 'c1', lift, COLS)).toEqual({ kind: 'cancel', refocus: true });
    expect(esc.defaultPrevented).toBe(true);
    expect(drag.held()).toBeNull();
    drag.key(key(' '), 'c1', lift, COLS);
    const tab = key('Tab');
    expect(drag.key(tab, 'c1', lift, COLS)).toEqual({ kind: 'cancel', refocus: false });
    expect(tab.defaultPrevented).toBe(false);
  });

  it('swallows the keyup of the Space that lifted or dropped a card', () => {
    const drag = new KanbanKeyDrag<KeyDragPosition>();
    const free = new KeyboardEvent('keyup', { key: ' ', cancelable: true });
    drag.keyUp(free);
    expect(free.defaultPrevented).toBe(false);
    drag.key(key(' '), 'c1', lift, COLS);
    drag.held.set(null);
    const up = new KeyboardEvent('keyup', { key: ' ', cancelable: true });
    drag.keyUp(up);
    expect(up.defaultPrevented).toBe(true);
  });

  it('shares the preview of the item in the hand through one partial', () => {
    const app = join(__dirname, '../..');
    for (const scss of [
      'pages/todos/board-view/todo-board-view.component.scss',
      'pages/todos/board-rows/todo-board-rows.component.scss',
      'features/meetings/agenda-pane/agenda-pane.component.scss',
    ]) {
      const src = readFileSync(join(app, scss), 'utf8');
      expect(src).toMatch(/@include dp\.lift\(\d+deg\);/);
      expect(src).toContain('@include dp.smooth-edge;');
    }
  });
});
