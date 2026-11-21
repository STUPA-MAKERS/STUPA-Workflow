import { ChangeDetectionStrategy, Component, computed, effect, inject, model, output, signal, untracked } from '@angular/core';
import type { Uuid } from '@core/api/models';
import { problemCode } from '@core/api/problem';
import { TodosApiService, type TodoBoardSummary } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  DialogComponent,
  IconComponent,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';

/**
 * "Archivierte Boards" (spec 001068): the archived free boards that the person reads. A
 * manager of a board restores it, an admin deletes it after a question. `changed` tells the
 * page that the list of the boards changed (`restored` names the board).
 */
@Component({
  selector: 'app-todo-archived-boards',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    ButtonComponent,
    ButtonGroupComponent,
    ConfirmDialogComponent,
    DialogComponent,
    IconComponent,
    TranslatePipe,
  ],
  templateUrl: './todo-archived-boards.component.html',
  styleUrl: './todo-archived-boards.component.scss',
})
export class TodoArchivedBoardsComponent {
  private readonly api = inject(TodosApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  readonly restored = output<TodoBoardSummary>();
  /** The list is empty now: the page hides the action. */
  readonly emptied = output<void>();

  readonly boards = signal<readonly TodoBoardSummary[]>([]);
  readonly busy = signal<Uuid | null>(null);
  readonly deleting = signal<TodoBoardSummary | null>(null);
  readonly admin = computed(() => this.auth.isAdmin());

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => this.load());
    });
  }

  private load(): void {
    this.api.archivedBoards().subscribe({
      next: (list) => this.boards.set(list),
      error: () =>
        this.toast.show({
          text: this.i18n.translate('todos.archivedBoards.loadFailed'),
          kind: 'error',
        }),
    });
  }

  private drop(id: Uuid): void {
    this.boards.update((list) => list.filter((b) => b.id !== id));
    if (!this.boards().length) this.emptied.emit();
  }

  restore(board: TodoBoardSummary): void {
    this.busy.set(board.id);
    this.api.restoreBoard(board.id).subscribe({
      next: (summary) => {
        this.busy.set(null);
        this.drop(board.id);
        this.toast.show({
          text: this.i18n.translate('todos.archivedBoards.restored', { name: board.name }),
          kind: 'success',
        });
        this.restored.emit(summary);
      },
      error: () => {
        this.busy.set(null);
        this.toast.show({
          text: this.i18n.translate('todos.archivedBoards.failed'),
          kind: 'error',
        });
      },
    });
  }

  confirmDelete(): void {
    const board = this.deleting();
    if (!board) return;
    this.busy.set(board.id);
    this.api.deleteBoard(board.id).subscribe({
      next: () => {
        this.busy.set(null);
        this.deleting.set(null);
        this.drop(board.id);
        this.toast.show({
          text: this.i18n.translate('todos.archivedBoards.deleted', { name: board.name }),
          kind: 'success',
        });
      },
      error: (err: unknown) => {
        this.busy.set(null);
        this.deleting.set(null);
        this.toast.show({
          text: this.i18n.translate(
            problemCode(err) === 'board_delete_admin_only'
              ? 'todos.archivedBoards.adminOnly'
              : 'todos.archivedBoards.failed',
          ),
          kind: 'error',
        });
      },
    });
  }
}
