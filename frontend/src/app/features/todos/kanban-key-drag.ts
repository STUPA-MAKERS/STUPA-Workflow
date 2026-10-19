import { signal } from '@angular/core';
import type { Uuid } from '@core/api/models';

/** Where a card that the keyboard holds is now, and where it came from. */
export interface KeyDragPosition {
  cardId: Uuid;
  col: number;
  index: number;
  fromCol: number;
  fromIndex: number;
}

/** The columns of the board that holds the card, as the keyboard drag needs them. */
export interface KeyDragColumns {
  /** The number of columns. */
  count: number;
  /** The length of the list of a column, with the held card at its provisional place. */
  length(col: number): number;
  /** The number of cards in a column without the held card. */
  others(col: number, cardId: Uuid): number;
}

/**
 * What a key on a tile did. `lift`: the card is held. `move`: it moved one step. `drop`: it
 * is put down at `at`; the card is still held, because the lists give the place of the move
 * only with the card in them, so the caller reads them and then sets `held` to `null`. `cancel`: the drag has ended without a move;
 * `refocus` is true for Escape, which keeps the focus on the card. `none`: the key is not
 * part of the drag.
 */
export type KeyDragStep<T extends KeyDragPosition> =
  | { kind: 'lift' }
  | { kind: 'move' }
  | { kind: 'drop'; at: T }
  | { kind: 'cancel'; refocus: boolean }
  | { kind: 'none' };

/**
 * The keyboard drag of a kanban board: Space lifts a card, the arrows move it inside its
 * column and across the columns, Space or Enter puts it down, Escape and Tab cancel. The
 * board view and the board rows of the to-dos share it; each one says the step aloud,
 * moves the card and puts the focus back.
 */
export class KanbanKeyDrag<T extends KeyDragPosition> {
  /** The held card, or `null`. */
  readonly held = signal<T | null>(null);
  /** The keydown of Space lifted or put down a card, so its keyup must not click the tile. */
  private spaceTaken = false;

  /**
   * A button activates on the keyup of Space (Firefox does so even after a prevented
   * keydown), so the keyup after a lift or a put-down would open the card and the drawer
   * would end the drag. The keydown handles Space.
   */
  keyUp(event: KeyboardEvent): void {
    if (event.key !== ' ' || (!this.spaceTaken && !this.held())) return;
    this.spaceTaken = false;
    event.preventDefault();
  }

  /**
   * A keydown on the tile of `cardId`. `lift` gives the position of a card that Space
   * lifts now.
   */
  key(event: KeyboardEvent, cardId: Uuid, lift: () => T, columns: KeyDragColumns): KeyDragStep<T> {
    const kb = this.held();
    if (!kb) {
      if (event.key !== ' ') return { kind: 'none' };
      event.preventDefault();
      this.spaceTaken = true;
      this.held.set(lift());
      return { kind: 'lift' };
    }
    if (kb.cardId !== cardId) return { kind: 'none' };
    switch (event.key) {
      case 'ArrowUp':
      case 'ArrowDown': {
        event.preventDefault();
        const len = columns.length(kb.col);
        const step = event.key === 'ArrowUp' ? -1 : 1;
        this.held.set({ ...kb, index: Math.max(0, Math.min(len - 1, kb.index + step)) });
        return { kind: 'move' };
      }
      case 'ArrowLeft':
      case 'ArrowRight': {
        event.preventDefault();
        const col = Math.max(0, Math.min(columns.count - 1, kb.col + (event.key === 'ArrowLeft' ? -1 : 1)));
        if (col === kb.col) return { kind: 'none' };
        this.held.set({ ...kb, col, index: Math.min(kb.index, columns.others(col, kb.cardId)) });
        return { kind: 'move' };
      }
      case ' ':
      case 'Enter':
        event.preventDefault();
        this.spaceTaken = event.key === ' ';
        return { kind: 'drop', at: kb };
      case 'Escape':
      case 'Tab':
        this.held.set(null);
        // Tab leaves the card the native way; only Escape keeps the focus on it.
        if (event.key === 'Escape') event.preventDefault();
        return { kind: 'cancel', refocus: event.key === 'Escape' };
      default:
        return { kind: 'none' };
    }
  }
}
