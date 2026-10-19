import { type Signal, signal } from '@angular/core';

/** The open rows of a list of rows that open one by one. Make it with {@link expandSet}. */
export interface ExpandSet<K> {
  /** The keys of the open rows. */
  readonly ids: Signal<ReadonlySet<K>>;
  /** The row is open. Reads the signal, so a template or a computed follows it. */
  has(key: K): boolean;
  /** Open a closed row, close an open one. Returns `true` when the row is open now. */
  toggle(key: K): boolean;
  /** Open the row; an open row stays open. */
  open(key: K): void;
  /** Close every row. */
  clear(): void;
}

/**
 * The set of the open rows of an admin list (Gremien, roles, the audit log): each row
 * opens and closes on its own, several rows can be open at once.
 *
 * ```ts
 * protected readonly expanded = expandSet<string>();
 * protected toggle(id: string): void {
 *   if (this.expanded.toggle(id)) this.loadDetails(id);
 * }
 * ```
 */
export function expandSet<K>(): ExpandSet<K> {
  const ids = signal<ReadonlySet<K>>(new Set());
  return {
    ids: ids.asReadonly(),
    has: (key) => ids().has(key),
    toggle: (key) => {
      const next = new Set(ids());
      const open = !next.has(key);
      if (open) next.add(key);
      else next.delete(key);
      ids.set(next);
      return open;
    },
    open: (key) => {
      if (!ids().has(key)) ids.set(new Set(ids()).add(key));
    },
    clear: () => ids.set(new Set()),
  };
}
