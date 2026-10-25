import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoLinkKind, type TodoLinkedCard } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate } from '@core/i18n/translations';
import { dayMonth } from '@shared/date-format';
import {
  type AvatarSize,
  AvatarStackComponent,
  IconComponent,
} from '@stupa-makers/ui-kit';
import { TodoLinkedRefresh, linkedKey } from './todo-linked-refresh';
import { personName } from '@shared/person-label.util';

/**
 * The back-reference "To-Dos" of an object (an application, an agenda item, a vote, an
 * invoice, a booking): the cards
 * linked to it that the viewer may read (`GET /todos/linked`), each with its board, its
 * column, the due date and the people. A row opens the card on its board.
 *
 * Nothing linked, or the read fails: the component shows nothing.
 *
 * A page that needs the cards itself (the ticket page counts the open ones) passes them
 * as `items`; the list then reads nothing.
 */
@Component({
  selector: 'app-todo-linked-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, AvatarStackComponent, IconComponent],
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

  sub(card: TodoLinkedCard): string {
    const parts = [card.boardName, card.columnName];
    if (card.dueDate) parts.push(this.t('todos.linked.due', { date: dayMonth(card.dueDate, this.i18n.formatLocale()) }));
    return parts.join(' · ');
  }

  names(card: TodoLinkedCard): string[] {
    return card.assignees.map((a) => personName(a, this.t));
  }

  ids(card: TodoLinkedCard): (string | null)[] {
    return card.assignees.map((a) => a.principalId);
  }
}
