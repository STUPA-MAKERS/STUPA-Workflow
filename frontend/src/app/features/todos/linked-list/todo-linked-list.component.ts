import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoLinkKind, type TodoLinkedCard } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate } from '@core/i18n/translations';
import { dayMonth } from '@shared/date-format';
import { formatMoney, moneyNumber } from '@shared/format-money';
import { eventDays } from '../todos.util';
import {
  type AvatarSize,
  AvatarStackComponent,
  IconComponent,
  type IconName,
  SectionComponent,
} from '@stupa-makers/ui-kit';
import { TodoLinkedRefresh, linkedKey } from './todo-linked-refresh';
import { personName } from '@shared/person-label.util';

/** A row above the cards in the same look, for the object that the list belongs to. */
export interface LinkedLead {
  readonly icon: IconName;
  readonly title: string;
  readonly sub: string;
  /** The router link. The row opens it in a new tab. */
  readonly link: readonly unknown[];
}

/**
 * The back-reference "To-Dos" of an object (an application, an agenda item, a vote, an
 * invoice, a booking): the cards
 * linked to it that the viewer may read (`GET /todos/linked`), each with its board, its
 * column, the due date and the people. A row opens the card on its board.
 *
 * Nothing linked, or the read fails: the component shows nothing, or only the `lead` row.
 * The TOP sheet puts the application of an application item there, "Antrag · Entwurf ·
 * 1.250,00 €", above the cards of the TOP.
 *
 * A page that needs the cards itself (the ticket page counts the open ones) passes them
 * as `items`; the list then reads nothing.
 */
@Component({
  selector: 'app-todo-linked-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SectionComponent, RouterLink, TranslatePipe, AvatarStackComponent, IconComponent],
  templateUrl: './todo-linked-list.component.html',
  styleUrl: './todo-linked-list.component.scss',
})
export class TodoLinkedListComponent {
  private readonly api = inject(TodosApiService);
  private readonly refresh = inject(TodoLinkedRefresh);
  private readonly i18n = inject(I18nService);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly kind = input.required<Exclude<TodoLinkKind, 'todo'>>();
  readonly targetId = input.required<Uuid>();
  /** The id of the heading, unique on the page. */
  readonly headingId = input('todo-linked');

  /**
   * Show the "To-Dos" heading. The TOP sheet leaves it out, because there the list stands
   * under the TOP title; the section keeps the name for the screen reader.
   */
  readonly showTitle = input(true);
  /** The cards to show, read by the page. `null` reads them here. */
  readonly items = input<readonly TodoLinkedCard[] | null>(null);
  readonly avatarSize = input<AvatarSize>('sm');
  /** The row above the cards. */
  readonly lead = input<LinkedLead | null>(null);

  private readonly loaded = signal<readonly TodoLinkedCard[]>([]);
  readonly cards = computed(() => this.items() ?? this.loaded());
  private seq = 0;

  constructor() {
    effect(() => {
      const kind = this.kind();
      const id = this.targetId();
      if (this.items() !== null) return;
      untracked(() => this.load(kind, id, false));
    });
    const seen = this.refresh.last();
    effect(() => {
      const change = this.refresh.last();
      if (!change || change === seen) return;
      untracked(() => {
        if (this.items() !== null) return;
        if (change.keys.has(linkedKey(this.kind(), this.targetId()))) this.load(this.kind(), this.targetId(), true);
      });
    });
  }

  private load(kind: Exclude<TodoLinkKind, 'todo'>, id: Uuid, keep: boolean): void {
    const seq = ++this.seq;
    if (!keep) this.loaded.set([]);
    this.api.linked(kind, id).subscribe({
      next: (cards) => {
        if (seq === this.seq) this.loaded.set(cards);
      },
      error: () => undefined,
    });
  }

  /** "Veranstaltung · 20.11.–21.11.2026 · AStA": the server puts a linked Event first. */
  eventSub(card: TodoLinkedCard): string {
    const days = eventDays(card.event?.startsOn ?? null, card.event?.endsOn ?? null, this.i18n.formatLocale());
    return days
      ? this.t('todos.eventCard.linkedSub', { dates: days, board: card.boardName })
      : this.t('todos.eventCard.linkedSubNoDate', { board: card.boardName });
  }

  /** The balance of an Event with its sign. */
  money(value: string | null): string {
    return formatMoney(value, this.i18n.formatLocale(), { signed: true });
  }

  negative(value: string | null): boolean {
    return (moneyNumber(value) ?? 0) < 0;
  }

  sub(card: TodoLinkedCard): string {
    const due = card.dueDate
      ? [this.t('todos.linked.due', { date: dayMonth(card.dueDate, this.i18n.formatLocale()) })]
      : [];
    return [card.boardName, card.columnName, ...due].join(' · ');
  }

  names(card: TodoLinkedCard): string[] {
    return card.assignees.map((a) => personName(a, this.t));
  }

  ids(card: TodoLinkedCard): (string | null)[] {
    return card.assignees.map((a) => a.principalId);
  }
}
