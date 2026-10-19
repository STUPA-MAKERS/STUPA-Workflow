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
import { TodosApiService, type TodoBoard, type TodoBoardKind, type TodoBoardSummary } from '@core/api/todos.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  SelectFieldComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { canTransfer, sortedColumns } from '../todos.util';

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
 * the API, and without the personal board when the card is on a shared board
 * (`canTransfer`). The column starts as the first one of the chosen board; a board that
 * does not load shows the transfer error. Each open drops the answers of the open before
 * it. The dialog only picks: the card detail sends the transfer and sets `busy` while it
 * runs.
 */
@Component({
  selector: 'app-todo-transfer-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, DialogComponent, EmptyStateComponent, SelectFieldComponent],
  templateUrl: './todo-transfer-dialog.component.html',
  styleUrl: './todo-transfer-dialog.component.scss',
})
export class TodoTransferDialogComponent {
  private readonly api = inject(TodosApiService);

  readonly open = model(false);
  /** The board that holds the card now; it is not a target. */
  readonly boardId = input.required<Uuid>();
  /** The kind of that board: a card of a shared board does not go into a personal one. */
  readonly boardKind = input.required<TodoBoardKind>();
  /** True while the transfer runs. */
  readonly busy = input(false);
  readonly transferred = output<TodoTransferTarget>();

  readonly boards = signal<TodoBoardSummary[]>([]);
  readonly loaded = signal(false);
  readonly selectedBoard = signal<Uuid>('');
  readonly board = signal<TodoBoard | null>(null);
  readonly column = signal<Uuid>('');
  /** The board list or the chosen board did not load. */
  readonly failed = signal(false);
  /** Counts the opens: a board list of an earlier open is dropped. */
  private openSeq = 0;
  /** Counts the board picks: the columns of an earlier pick are dropped. */
  private seq = 0;

  readonly targets = computed(() =>
    this.boards().filter((b) => b.canWrite && b.id !== this.boardId() && canTransfer(this.boardKind(), b.kind)),
  );
  readonly boardOptions = computed<SelectOption[]>(() => this.targets().map((b) => ({ value: b.id, label: b.name })));
  readonly columnOptions = computed<SelectOption[]>(() =>
    sortedColumns(this.board()?.columns ?? []).map((c) => ({ value: c.id, label: c.name })),
  );
  readonly none = computed(() => this.loaded() && !this.failed() && this.targets().length === 0);
  /** The board list did not load: the dialog shows the error alone. */
  readonly unloadable = computed(() => this.loaded() && this.failed() && this.targets().length === 0);
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
    const open = ++this.openSeq;
    this.seq++;
    this.loaded.set(false);
    this.boards.set([]);
    this.selectedBoard.set('');
    this.board.set(null);
    this.column.set('');
    this.failed.set(false);
    this.api.boards().subscribe({
      next: (boards) => {
        if (open !== this.openSeq) return;
        this.boards.set(boards);
        this.loaded.set(true);
        const first = this.targets()[0];
        if (first) this.setBoard(first.id);
      },
      error: () => {
        if (open !== this.openSeq) return;
        this.failed.set(true);
        this.loaded.set(true);
      },
    });
  }

  setBoard(id: Uuid): void {
    const seq = ++this.seq;
    this.selectedBoard.set(id);
    this.board.set(null);
    this.column.set('');
    this.failed.set(false);
    this.api.board(id).subscribe({
      next: (board) => {
        if (seq !== this.seq) return;
        this.board.set(board);
        this.column.set(sortedColumns(board.columns)[0]?.id ?? '');
      },
      error: () => {
        if (seq !== this.seq) return;
        this.board.set(null);
        this.failed.set(true);
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
