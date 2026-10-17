import { ChangeDetectionStrategy, Component, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoLinkKind, type TodoLinkedCard } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AvatarStackComponent } from '@shared/ui/avatar/avatar.component';
import { IconComponent } from '@stupa-makers/ui-kit';
import { personName, type Translate } from '../todos.util';
import { TodoLinkedRefresh, linkedKey } from './todo-linked-refresh';

/**
 * The back-reference "To-Dos" of an object (an application, an agenda item, a vote, an
 * invoice, a booking): the cards
 * linked to it that the viewer may read (`GET /todos/linked`), each with its board, its
 * column, the due date and the people. A row opens the card on its board.
 *
 * Nothing linked, or the read fails: the component shows nothing.
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

  readonly cards = signal<TodoLinkedCard[]>([]);
  private seq = 0;

  constructor() {
    effect(() => {
      const kind = this.kind();
      const id = this.targetId();
      untracked(() => this.load(kind, id, false));
    });
    // A card linked to this target elsewhere on the page: read again, keeping the list shown.
    const seen = this.refresh.last();
    effect(() => {
      const change = this.refresh.last();
      if (!change || change === seen) return;
      untracked(() => {
        if (change.keys.has(linkedKey(this.kind(), this.targetId()))) this.load(this.kind(), this.targetId(), true);
      });
    });
  }

  private load(kind: Exclude<TodoLinkKind, 'todo'>, id: Uuid, keep: boolean): void {
    const seq = ++this.seq;
    if (!keep) this.cards.set([]);
    this.api.linked(kind, id).subscribe({
      next: (cards) => {
        if (seq === this.seq) this.cards.set(cards);
      },
      error: () => undefined,
    });
  }

  sub(card: TodoLinkedCard): string {
    const parts = [card.boardName, card.columnName];
    if (card.dueDate) parts.push(this.t('todos.linked.due', { date: this.shortDate(card.dueDate) }));
    return parts.join(' · ');
  }

  names(card: TodoLinkedCard): string[] {
    return card.assignees.map((a) => personName(a, this.t));
  }

  ids(card: TodoLinkedCard): (string | null)[] {
    return card.assignees.map((a) => a.principalId);
  }

  /** `YYYY-MM-DD` as "17.10.". */
  private shortDate(date: string): string {
    const [y, m, d] = date.split('-').map(Number);
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), { day: '2-digit', month: '2-digit' }).format(
      new Date(y, m - 1, d),
    );
  }
}
