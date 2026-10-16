import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoBoard, type TodoBoardSummary } from '@core/api/todos.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SelectFieldComponent } from '@shared/ui/select/select.component';
import { ButtonComponent, DialogComponent, type SelectOption } from '@stupa-makers/ui-kit';
import { sortedColumns } from '../todos.util';

/** The target that the person picked in the dialog. */
export interface TodoTransferTarget {
  boardId: Uuid;
  columnId: Uuid;
  boardName: string;
}

/**
 * "In anderes Board verschieben": pick a board and a column for a card.
 *
 * The boards are every board with `canWrite` except the current one, in the order of
 * the API; the column starts as the first one of the chosen board. The dialog only
 * picks: the card detail sends the transfer and sets `busy` while it runs.
 */
@Component({
  selector: 'app-todo-transfer-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, DialogComponent, NoteComponent, SelectFieldComponent],
  templateUrl: './todo-transfer-dialog.component.html',
  styleUrl: './todo-transfer-dialog.component.scss',
})
export class TodoTransferDialogComponent {
  private readonly api = inject(TodosApiService);

  readonly open = model(false);
  /** The board that holds the card now; it is not a target. */
  readonly boardId = input.required<Uuid>();
  readonly cardTitle = input('');
  /** True while the transfer runs. */
  readonly busy = input(false);
  readonly transferred = output<TodoTransferTarget>();

  readonly boards = signal<TodoBoardSummary[]>([]);
  readonly loaded = signal(false);
  readonly selectedBoard = signal<Uuid>('');
  readonly board = signal<TodoBoard | null>(null);
  readonly column = signal<Uuid>('');
  private seq = 0;

  readonly targets = computed(() => this.boards().filter((b) => b.canWrite && b.id !== this.boardId()));
  readonly boardOptions = computed<SelectOption[]>(() => this.targets().map((b) => ({ value: b.id, label: b.name })));
  readonly columnOptions = computed<SelectOption[]>(() =>
    sortedColumns(this.board()?.columns ?? []).map((c) => ({ value: c.id, label: c.name })),
  );
  readonly none = computed(() => this.loaded() && this.targets().length === 0);
  readonly canConfirm = computed(
    () => !!this.selectedBoard() && this.board()?.id === this.selectedBoard() && !!this.column() && !this.busy(),
  );

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => this.start());
    });
  }

  private start(): void {
    this.seq++;
    this.loaded.set(false);
    this.boards.set([]);
    this.selectedBoard.set('');
    this.board.set(null);
    this.column.set('');
    this.api.boards().subscribe({
      next: (boards) => {
        this.boards.set(boards);
        this.loaded.set(true);
        const first = this.targets()[0];
        if (first) this.setBoard(first.id);
      },
      error: () => this.loaded.set(true),
    });
  }

  setBoard(id: Uuid): void {
    const seq = ++this.seq;
    this.selectedBoard.set(id);
    this.board.set(null);
    this.column.set('');
    this.api.board(id).subscribe({
      next: (board) => {
        if (seq !== this.seq) return;
        this.board.set(board);
        this.column.set(sortedColumns(board.columns)[0]?.id ?? '');
      },
      error: () => {
        if (seq === this.seq) this.board.set(null);
      },
    });
  }

  cancel(): void {
    this.open.set(false);
  }

  confirm(): void {
    const board = this.board();
    if (!this.canConfirm() || !board) return;
    this.transferred.emit({ boardId: board.id, columnId: this.column(), boardName: board.name });
  }
}
