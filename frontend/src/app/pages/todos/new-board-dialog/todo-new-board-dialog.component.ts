import { ChangeDetectionStrategy, Component, computed, effect, inject, model, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TodosApiService, type TodoBoard, type TodoBoardEntry, type TodoEntryRole } from '@core/api/todos.service';
import { problemCode } from '@core/api/problem';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  InputComponent,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';
import type { PickerHit } from '../../../features/gremien/gremium-person-picker/gremium-person-picker.component';
import { TodoBoardEntriesComponent, entryOf } from '../board-entries/todo-board-entries.component';

/**
 * The dialog "Neues Board" (spec 001061): the name and the members of a free board, the
 * Gremien and persons of the shared picker with their roles. The creator becomes a member
 * with "Verwalten" on the server, so the list does not show them. `created` gives the new
 * board to the page.
 */
@Component({
  selector: 'app-todo-new-board-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    FormsModule,
    ButtonComponent,
    DialogComponent,
    InputComponent,
    TodoBoardEntriesComponent,
    TranslatePipe,
  ],
  templateUrl: './todo-new-board-dialog.component.html',
  styleUrl: './todo-new-board-dialog.component.scss',
})
export class TodoNewBoardDialogComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  readonly created = output<TodoBoard>();

  readonly name = signal('');
  readonly entries = signal<readonly TodoBoardEntry[]>([]);
  readonly saving = signal(false);
  readonly valid = computed(() => this.name().trim().length > 0);

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.name.set('');
        this.entries.set([]);
      });
    });
  }

  add(event: { readonly hit: PickerHit; readonly role: TodoEntryRole }): void {
    this.entries.update((list) => [...list, entryOf(event.hit, event.role)]);
  }

  setRole(event: { readonly entry: TodoBoardEntry; readonly role: TodoEntryRole }): void {
    this.entries.update((list) =>
      list.map((e) => (e.targetId === event.entry.targetId ? { ...e, role: event.role } : e)),
    );
  }

  remove(entry: TodoBoardEntry): void {
    this.entries.update((list) => list.filter((e) => e.targetId !== entry.targetId));
  }

  submit(): void {
    if (!this.valid() || this.saving()) return;
    const entries = this.entries().map((e) =>
      e.kind === 'team' ? { teamId: e.targetId, role: e.role } : { principalId: e.targetId, role: e.role },
    );
    this.saving.set(true);
    this.api.createBoard(this.name().trim(), entries).subscribe({
      next: (board) => {
        this.saving.set(false);
        this.open.set(false);
        this.toast.show(this.i18n.translate('todos.newBoard.created'), 'success');
        this.created.emit(board);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        this.toast.show(
          this.i18n.translate(
            problemCode(err) === 'board_create_required'
              ? 'todos.newBoard.forbidden'
              : 'todos.newBoard.failed',
          ),
          'error',
        );
      },
    });
  }
}
