import { CdkDrag, CdkDragHandle, CdkDropList, moveItemInArray, type CdkDragDrop } from '@angular/cdk/drag-drop';
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
import { HttpErrorResponse } from '@angular/common/http';
import type { Observable } from 'rxjs';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoBoard,
  type TodoColumn,
  type TodoLabel,
  type TodoLabelColor,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SwitchComponent,
  ToastService,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { SelectFieldComponent } from '@shared/ui/select/select.component';
import { LABEL_COLORS, LABEL_COLOR_NAME, sortedColumns } from '../../../features/todos/todos.util';

/** The default archive age when the switch turns on. */
const DEFAULT_ARCHIVE_DAYS = 30;

const ERROR_TEXT: Record<string, TranslationKey> = {
  todo_configure_required: 'todos.settings.error.forbidden',
  column_not_empty: 'todos.settings.error.notEmpty',
  done_column_required: 'todos.settings.error.doneColumn',
  label_exists: 'todos.settings.error.labelExists',
};

/**
 * "Board-Einstellungen" (frame 9, `todo.configure`): the name, the columns (rename,
 * order by drag or by the menu, the done column, add, delete), the labels (name and
 * colour from the fixed palette) and the archive of done cards. Every change saves at
 * once; `changed` gives the board to the page.
 */
@Component({
  selector: 'app-todo-board-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CdkDrag,
    CdkDragHandle,
    CdkDropList,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    RowMenuComponent,
    SelectFieldComponent,
    SwitchComponent,
  ],
  templateUrl: './todo-board-settings.component.html',
  styleUrl: './todo-board-settings.component.scss',
})
export class TodoBoardSettingsComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  readonly board = input.required<TodoBoard>();
  readonly changed = output<TodoBoard>();

  readonly colors = LABEL_COLORS;
  readonly name = signal('');
  readonly days = signal(DEFAULT_ARCHIVE_DAYS);
  readonly busy = signal(false);
  readonly renaming = signal<Uuid | null>(null);
  readonly renameDraft = signal('');
  readonly newColumn = signal<string | null>(null);
  /** The label form: null closed, '' a new label, else the id of the edited label. */
  readonly labelEdit = signal<Uuid | '' | null>(null);
  readonly labelName = signal('');
  readonly labelColor = signal<TodoLabelColor>('green');
  /** A column with cards to delete: the column that takes them. */
  readonly deleting = signal<TodoColumn | null>(null);
  readonly moveTo = signal<Uuid>('');

  readonly columns = computed(() => sortedColumns(this.board().columns));
  readonly archiveOn = computed(() => this.board().archiveAfterDays !== null);
  readonly moveOptions = computed<SelectOption[]>(() =>
    this.columns()
      .filter((c) => c.id !== this.deleting()?.id)
      .map((c) => ({ value: c.id, label: c.name })),
  );

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        const b = this.board();
        this.name.set(b.name);
        this.days.set(b.archiveAfterDays ?? DEFAULT_ARCHIVE_DAYS);
        this.renaming.set(null);
        this.newColumn.set(null);
        this.labelEdit.set(null);
        this.deleting.set(null);
      });
    });
  }

  colorName(color: TodoLabelColor): string {
    return this.i18n.translate(LABEL_COLOR_NAME[color]);
  }

  private run(req: Observable<TodoBoard>, after?: () => void): void {
    this.busy.set(true);
    req.subscribe({
      next: (board) => {
        this.busy.set(false);
        this.changed.emit(board);
        after?.();
      },
      error: (err: unknown) => this.fail(err),
    });
  }

  private fail(err: unknown): void {
    this.busy.set(false);
    const code = err instanceof HttpErrorResponse ? (err.error as { code?: string } | null)?.code : undefined;
    this.toast.error(this.i18n.translate((code && ERROR_TEXT[code]) || 'todos.settings.error.save'));
  }

  saveName(): void {
    const name = this.name().trim();
    if (!name || name === this.board().name) {
      this.name.set(this.board().name);
      return;
    }
    this.run(this.api.patchBoard(this.board().id, { name }));
  }

  setArchive(on: boolean): void {
    this.run(this.api.patchBoard(this.board().id, { archiveAfterDays: on ? this.days() : null }));
  }

  saveDays(): void {
    const n = Math.round(Number(this.days()));
    if (!Number.isFinite(n) || n < 1 || n > 365) {
      this.days.set(this.board().archiveAfterDays ?? DEFAULT_ARCHIVE_DAYS);
      this.toast.error(this.i18n.translate('todos.settings.daysRange'));
      return;
    }
    if (n === this.board().archiveAfterDays) return;
    this.run(this.api.patchBoard(this.board().id, { archiveAfterDays: n }));
  }

  // ------------------------------------------------------------------ columns

  columnMenu(col: TodoColumn, index: number): RowMenuSection[] {
    const t = (key: TranslationKey) => this.i18n.translate(key);
    const items: RowMenuItem[] = [{ id: 'rename', label: t('todos.settings.renameColumn'), icon: 'edit' }];
    if (!col.isDone) items.push({ id: 'done', label: t('todos.settings.makeDone'), icon: 'check' });
    if (index > 0) items.push({ id: 'up', label: t('todos.settings.moveUp'), icon: 'up' });
    if (index < this.columns().length - 1) items.push({ id: 'down', label: t('todos.settings.moveDown'), icon: 'down' });
    return [
      { items },
      {
        items: [
          {
            id: 'delete',
            label: t('todos.settings.deleteColumn'),
            icon: 'trash',
            danger: true,
            disabledReason: col.isDone ? t('todos.settings.error.doneColumn') : null,
          },
        ],
      },
    ];
  }

  onColumnMenu(col: TodoColumn, index: number, item: RowMenuItem): void {
    switch (item.id) {
      case 'rename':
        this.renameDraft.set(col.name);
        this.renaming.set(col.id);
        break;
      case 'done':
        this.run(this.api.patchColumn(this.board().id, col.id, { isDone: true }));
        break;
      case 'up':
      case 'down':
        this.reorder(index, index + (item.id === 'up' ? -1 : 1));
        break;
      case 'delete':
        this.deleteColumn(col);
        break;
    }
  }

  saveRename(col: TodoColumn): void {
    const name = this.renameDraft().trim();
    if (!name || name === col.name) {
      this.renaming.set(null);
      return;
    }
    this.run(this.api.patchColumn(this.board().id, col.id, { name }), () => this.renaming.set(null));
  }

  addColumn(): void {
    const name = (this.newColumn() ?? '').trim();
    if (!name) return;
    this.run(this.api.addColumn(this.board().id, name), () => this.newColumn.set(null));
  }

  drop(event: CdkDragDrop<unknown>): void {
    if (event.previousIndex === event.currentIndex) return;
    this.reorder(event.previousIndex, event.currentIndex);
  }

  private reorder(from: number, to: number): void {
    const ids = this.columns().map((c) => c.id);
    moveItemInArray(ids, from, to);
    this.run(this.api.orderColumns(this.board().id, ids));
  }

  deleteColumn(col: TodoColumn): void {
    if (col.cardCount > 0) {
      this.askMoveTo(col);
      return;
    }
    this.busy.set(true);
    this.api.deleteColumn(this.board().id, col.id).subscribe({
      next: (board) => {
        this.busy.set(false);
        this.changed.emit(board);
      },
      error: (err: unknown) => {
        if (err instanceof HttpErrorResponse && (err.error as { code?: string } | null)?.code === 'column_not_empty') {
          this.busy.set(false);
          this.askMoveTo(col);
          return;
        }
        this.fail(err);
      },
    });
  }

  private askMoveTo(col: TodoColumn): void {
    this.deleting.set(col);
    this.moveTo.set(this.columns().find((c) => c.id !== col.id)?.id ?? '');
  }

  confirmDelete(): void {
    const col = this.deleting();
    if (!col || !this.moveTo()) return;
    this.run(this.api.deleteColumn(this.board().id, col.id, this.moveTo()), () => this.deleting.set(null));
  }

  // ------------------------------------------------------------------ labels

  editLabel(label: TodoLabel | null): void {
    this.labelEdit.set(label?.id ?? '');
    this.labelName.set(label?.name ?? '');
    this.labelColor.set(label?.color ?? 'green');
  }

  saveLabel(): void {
    const id = this.labelEdit();
    const name = this.labelName().trim();
    if (id === null || !name) return;
    const boardId = this.board().id;
    const req = id
      ? this.api.patchLabel(boardId, id, { name, color: this.labelColor() })
      : this.api.addLabel(boardId, { name, color: this.labelColor() });
    this.busy.set(true);
    req.subscribe({
      next: (label) => {
        this.busy.set(false);
        // The board as it is now: a poll during the request may have brought newer cards.
        const now = this.board();
        const labels = id ? now.labels.map((l) => (l.id === id ? label : l)) : [...now.labels, label];
        this.changed.emit({ ...now, labels: labels.sort((a, b) => a.name.localeCompare(b.name)) });
        this.labelEdit.set(null);
      },
      error: (err: unknown) => this.fail(err),
    });
  }

  deleteLabel(): void {
    const id = this.labelEdit();
    if (!id) return;
    this.busy.set(true);
    this.api.deleteLabel(this.board().id, id).subscribe({
      next: () => {
        this.busy.set(false);
        const now = this.board();
        this.changed.emit({
          ...now,
          labels: now.labels.filter((l) => l.id !== id),
          cards: now.cards.map((c) => ({ ...c, labelIds: c.labelIds.filter((x) => x !== id) })),
        });
        this.labelEdit.set(null);
      },
      error: (err: unknown) => this.fail(err),
    });
  }
}
