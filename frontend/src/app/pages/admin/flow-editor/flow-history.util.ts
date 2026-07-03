import { signal } from '@angular/core';
import type { FlowGraph } from '../admin.models';

/**
 * Structural signature (without layout): two graphs are "equal" when they
 * differ only in node positions — such changes are not an undo step.
 */
export function structuralKey(g: FlowGraph): string {
  return JSON.stringify([g.states, g.transitions]);
}

const MAX_UNDO = 100;

/** Undo/redo history over graph snapshots. */
export class FlowHistory {
  private undoStack: FlowGraph[] = [];
  private redoStack: FlowGraph[] = [];

  /** Reactive availability for the toolbar buttons. */
  readonly canUndo = signal(false);
  readonly canRedo = signal(false);

  /** Record a structural edit: `prev` becomes the next undo target. */
  record(prev: FlowGraph): void {
    this.undoStack.push(prev);
    if (this.undoStack.length > MAX_UNDO) this.undoStack.shift();
    this.redoStack = [];
    this.sync();
  }

  /** Pop the previous snapshot; `current` becomes redoable. */
  undo(current: FlowGraph): FlowGraph | undefined {
    const prev = this.undoStack.pop();
    if (prev === undefined) return undefined;
    this.redoStack.push(current);
    this.sync();
    return prev;
  }

  redo(current: FlowGraph): FlowGraph | undefined {
    const next = this.redoStack.pop();
    if (next === undefined) return undefined;
    this.undoStack.push(current);
    this.sync();
    return next;
  }

  private sync(): void {
    this.canUndo.set(this.undoStack.length > 0);
    this.canRedo.set(this.redoStack.length > 0);
  }
}
