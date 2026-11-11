import { signal } from '@angular/core';
import type { FlowGraph } from '../admin.models';

/**
 * Structural signature of a graph, without the layout. Two graphs count as equal when
 * they differ only in node positions. Such a change is not an undo step.
 */
export function structuralKey(g: FlowGraph): string {
  return JSON.stringify([g.states, g.transitions]);
}

const MAX_UNDO = 100;

/** Undo/redo history over graph snapshots. */
export class FlowHistory {
  private undoStack: readonly FlowGraph[] = [];
  private redoStack: readonly FlowGraph[] = [];

  /** Reactive availability for the toolbar buttons. */
  readonly canUndo = signal(false);
  readonly canRedo = signal(false);

  /** Record a structural edit: `prev` becomes the next undo target. */
  record(prev: FlowGraph): void {
    this.undoStack = [...this.undoStack, prev].slice(-MAX_UNDO);
    this.redoStack = [];
    this.sync();
  }

  /** Pop the previous snapshot. `current` becomes redoable. */
  undo(current: FlowGraph): FlowGraph | undefined {
    const prev = this.undoStack.at(-1);
    if (prev === undefined) return undefined;
    this.undoStack = this.undoStack.slice(0, -1);
    this.redoStack = [...this.redoStack, current];
    this.sync();
    return prev;
  }

  redo(current: FlowGraph): FlowGraph | undefined {
    const next = this.redoStack.at(-1);
    if (next === undefined) return undefined;
    this.redoStack = this.redoStack.slice(0, -1);
    this.undoStack = [...this.undoStack, current];
    this.sync();
    return next;
  }

  private sync(): void {
    this.canUndo.set(this.undoStack.length > 0);
    this.canRedo.set(this.redoStack.length > 0);
  }
}
