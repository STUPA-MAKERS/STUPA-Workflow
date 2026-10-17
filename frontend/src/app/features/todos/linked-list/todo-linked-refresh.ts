import { Injectable, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoLinkKind } from '@core/api/todos.service';

/** One change of the links: the targets that gained or lost a card. */
export interface TodoLinkedChange {
  readonly keys: ReadonlySet<string>;
}

export function linkedKey(kind: TodoLinkKind, targetId: Uuid): string {
  return `${kind}:${targetId}`;
}

/**
 * Tells the back-references on screen that a card was linked to their target. The list
 * reads `GET /todos/linked` only when its target changes, so a card created next to it
 * (the TOP menu beside the top sheet) needs this nudge to show up.
 */
@Injectable({ providedIn: 'root' })
export class TodoLinkedRefresh {
  private readonly _last = signal<TodoLinkedChange | null>(null);
  readonly last = this._last.asReadonly();

  touch(links: readonly { kind: TodoLinkKind; targetId: Uuid }[]): void {
    if (!links.length) return;
    this._last.set({ keys: new Set(links.map((l) => linkedKey(l.kind, l.targetId))) });
  }
}
