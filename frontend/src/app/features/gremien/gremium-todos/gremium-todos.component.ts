import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, map, of, switchMap } from 'rxjs';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoBoard, type TodoLinkedCard } from '@core/api/todos.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent, SkeletonComponent } from '@stupa-makers/ui-kit';
import { TodoLinkedListComponent } from '../../todos/linked-list/todo-linked-list.component';
import { cardsOf, sortedColumns } from '../../todos/todos.util';

/**
 * The tab "To-Dos" of a Gremium (spec 000551): the open cards of the board of the
 * Gremium, in board order (column by column, each by rank). A row opens its card on the
 * board, and the menu of the detail opens the board itself ("Board öffnen"). A card
 * belongs to the Gremium because it is on that board, not because of a link. The detail
 * shows the tab only when the person reads the board.
 */
@Component({
  selector: 'app-gremium-todos',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, EmptyStateComponent, SkeletonComponent, TodoLinkedListComponent],
  templateUrl: './gremium-todos.component.html',
})
export class GremiumTodosComponent {
  private readonly api = inject(TodosApiService);

  readonly gremiumId = input.required<Uuid>();
  readonly boardId = input.required<Uuid>();

  /** `null` while the board loads. */
  readonly cards = toSignal(
    toObservable(this.boardId).pipe(
      switchMap((id) =>
        this.api.board(id).pipe(
          map(openCards),
          catchError(() => of([] as TodoLinkedCard[])),
        ),
      ),
    ),
    { initialValue: null },
  );
}

/** The cards of the board outside its done columns, as rows of the linked list. */
export function openCards(board: TodoBoard): readonly TodoLinkedCard[] {
  return sortedColumns(board.columns.filter((c) => !c.isDone)).flatMap((column) =>
    cardsOf(board, column.id).map((c) => ({
      id: c.id,
      boardId: board.id,
      boardName: board.name,
      title: c.title,
      columnName: column.name,
      isDone: false,
      dueDate: c.dueDate,
      assignees: c.assignees,
      event: c.event,
      balance: null,
    })),
  );
}
