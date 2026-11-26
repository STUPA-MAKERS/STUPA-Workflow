import { computed, inject, signal } from '@angular/core';
import { EventsApiService, type EventRef } from '@core/api/events.service';
import type { Uuid } from '@core/api/models';
import { TodosApiService } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { type Observable, map, of, switchMap } from 'rxjs';
import { TodoLinkedRefresh } from './linked-list/todo-linked-refresh';
import { eventDays } from './todos.util';

/**
 * The `Veranstaltung` picker of a Buchung (specs 000480, 003033): it lists the open Events
 * of the teams of the person and keeps the one Event that links the booking. The picker
 * writes no field of the booking: `apply` removes the link of the old Event and adds the
 * link of the new one, after the booking is saved, because a new booking has no id before.
 *
 * Construct it in an injection context (a field of a state class or a component).
 */
export class EventLinkState {
  private readonly events = inject(EventsApiService);
  private readonly links = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly refresh = inject(TodoLinkedRefresh);

  /** The Event id, or '' for none. */
  readonly value = signal<Uuid>('');
  /** The Event that links the booking when the form opened. */
  private readonly initial = signal<Uuid>('');
  /** The link between the booking and that Event. */
  private readonly linkId = signal<Uuid | null>(null);
  private readonly refs = signal<readonly EventRef[]>([]);
  /** The current Event when it is not open any more, so it is not in `refs`. */
  private readonly extra = signal<SelectOption | null>(null);

  readonly options = computed<SelectOption[]>(() => {
    const none = { value: '', label: this.i18n.translate('events.picker.none') };
    const list = this.refs().map((e) => ({ value: e.id, label: this.label(e) }));
    const extra = this.extra();
    const missing = extra !== null && !list.some((o) => o.value === extra.value);
    return missing ? [none, extra, ...list] : [none, ...list];
  });

  readonly changed = computed(() => this.value() !== this.initial());

  /** Read the Events, and for an edit the Event that links the booking. */
  load(expenseId: Uuid | null): void {
    this.value.set('');
    this.initial.set('');
    this.linkId.set(null);
    this.extra.set(null);
    this.events.refs().subscribe({
      next: (list) => this.refs.set(list),
      error: () => this.refs.set([]),
    });
    if (!expenseId) return;
    this.links.links('expense', expenseId).subscribe({
      next: (out) => {
        const row = out.links.find((l) => l.kind === 'event');
        if (!row) return;
        this.initial.set(row.targetId);
        this.value.set(row.targetId);
        this.linkId.set(row.id);
        this.extra.set({ value: row.targetId, label: row.title ?? '' });
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
    const old = this.linkId();
    const unlink: Observable<unknown> = from && old ? this.links.unlink(old) : of(null);
    return unlink.pipe(
      switchMap(() =>
        to ? this.links.link({ kind: 'event', id: to }, { kind: 'expense', id: expenseId }) : of(null),
      ),
      map((out) => {
        this.initial.set(to);
        this.linkId.set(out?.links.find((l) => l.kind === 'expense' && l.targetId === expenseId)?.id ?? null);
        this.refresh.touch([
          { kind: 'expense', targetId: expenseId },
          ...(from ? [{ kind: 'event' as const, targetId: from }] : []),
          ...(to ? [{ kind: 'event' as const, targetId: to }] : []),
        ]);
      }),
    );
  }

  /** "Erstiparty · 20.11.2026 · Kultur". */
  private label(e: EventRef): string {
    const days = eventDays(e.startsOn, e.endsOn, this.i18n.formatLocale());
    return [e.title, days, e.teamName].filter(Boolean).join(' · ');
  }
}
