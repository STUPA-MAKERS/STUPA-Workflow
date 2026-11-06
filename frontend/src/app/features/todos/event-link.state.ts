import { computed, inject, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoEventRef } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { type Observable, map, of, switchMap } from 'rxjs';
import { TodoLinkedRefresh } from './linked-list/todo-linked-refresh';
import { eventDays } from './todos.util';

/**
 * The `Veranstaltung` picker of a Buchung (spec 000480): it lists the Events on the boards
 * that the person writes and keeps the one Event that links the booking. The picker writes
 * no field of the booking: `apply` removes the link of the old Event card and adds the link
 * of the new one, after the booking is saved, because a new booking has no id before.
 *
 * Construct it in an injection context (a field of a state class or a component).
 */
export class EventLinkState {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly refresh = inject(TodoLinkedRefresh);

  /** The Event card id, or '' for none. */
  readonly value = signal<Uuid>('');
  /** The Event that links the booking when the form opened. */
  private readonly initial = signal<Uuid>('');
  private readonly events = signal<TodoEventRef[]>([]);
  /** The current Event when the person cannot write its board, so it is not in `events`. */
  private readonly extra = signal<SelectOption | null>(null);

  readonly options = computed<SelectOption[]>(() => {
    const none = { value: '', label: this.i18n.translate('todos.eventCard.none') };
    const list = this.events().map((e) => ({ value: e.id, label: this.label(e) }));
    const extra = this.extra();
    if (extra && !list.some((o) => o.value === extra.value)) list.unshift(extra);
    return [none, ...list];
  });

  readonly changed = computed(() => this.value() !== this.initial());

  /** Read the Events, and for an edit the Event that links the booking. */
  load(expenseId: Uuid | null): void {
    this.value.set('');
    this.initial.set('');
    this.extra.set(null);
    this.api.writableEvents().subscribe({
      next: (list) => this.events.set(list),
      error: () => this.events.set([]),
    });
    if (!expenseId) return;
    this.api.linked('expense', expenseId).subscribe({
      next: (cards) => {
        const event = cards.find((c) => c.event);
        if (!event) return;
        this.initial.set(event.id);
        this.value.set(event.id);
        this.extra.set({ value: event.id, label: `${event.title} · ${event.boardName}` });
      },
      error: () => undefined,
    });
  }

  /**
   * Move the link of the booking from the old Event to the picked one. Nothing goes out
   * when the pick did not change.
   */
  apply(expenseId: Uuid): Observable<void> {
    const from = this.initial();
    const to = this.value();
    if (from === to) return of(undefined);
    const unlink: Observable<unknown> = from
      ? this.api.card(from).pipe(
          switchMap((card) => {
            const link = card.links.find((l) => l.kind === 'expense' && l.targetId === expenseId);
            return link ? this.api.removeLink(from, link.id) : of(null);
          }),
        )
      : of(null);
    return unlink.pipe(
      switchMap(() => (to ? this.api.addLink(to, 'expense', expenseId) : of(null))),
      map(() => {
        this.initial.set(to);
        this.refresh.touch([{ kind: 'expense', targetId: expenseId }]);
      }),
    );
  }

  /** "Erstiparty · 20.11.2026 · AStA". */
  private label(e: TodoEventRef): string {
    const days = eventDays(e.startsOn, e.endsOn, this.i18n.formatLocale());
    return [e.title, days, e.boardName].filter(Boolean).join(' · ');
  }
}
