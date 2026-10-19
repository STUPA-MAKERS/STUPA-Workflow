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
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardKind,
  type TodoBoardSummary,
  type TodoCardDetail,
  type TodoLinkKind,
  type TodoLinkTarget,
  type TodoMember,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  ToastService,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { MarkdownImageUploadDirective } from '@shared/markdown/markdown-image-upload.directive';
import { SelectFieldComponent, type SelectFieldOption } from '@shared/ui/select/select.component';
import { TodoLinkPickerComponent, linkKey } from '../link-picker/todo-link-picker.component';
import { LINK_ICON, LINK_KIND_LABEL, sortedColumns } from '../todos.util';

/** The most characters of a card title (server rule). */
const MAX_TITLE = 300;

/** A link the new card takes along; `label` is its text in the chip. */
export interface NewTodoLink {
  kind: TodoLinkKind;
  targetId: Uuid;
  label: string;
}

/**
 * "Neues To-Do" (frame 5): the dialog of the board ("+ To-Do"), of the ⋮ of a TOP and
 * of a ticket ("To-Do aus Ticket anlegen", frame 33).
 *
 * Board and column start as the given board (or the board of the given Gremium, or the
 * first board of `boardKinds`), else the first board that takes cards; the column as the
 * given or the first one. The person and the due date are optional. The given links go
 * along, each with a × to take it off, and the picker adds more. The ticket dialog
 * leaves out the description (`withDescription`).
 */
@Component({
  selector: 'app-todo-new-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DatepickerComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    MarkdownImageUploadDirective,
    SelectFieldComponent,
    TodoLinkPickerComponent,
  ],
  templateUrl: './todo-new-dialog.component.html',
  styleUrl: './todo-new-dialog.component.scss',
})
export class TodoNewDialogComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = model(false);
  /** The board to start on. */
  readonly boardId = input<Uuid | null>(null);
  /** Else the board of this Gremium. */
  readonly gremiumId = input<Uuid | null>(null);
  /** The column to start on. */
  readonly columnId = input<Uuid | null>(null);
  /** Else the first board of these kinds, in this order. */
  readonly boardKinds = input<readonly TodoBoardKind[]>([]);
  readonly initialTitle = input('');
  readonly initialLinks = input<readonly NewTodoLink[]>([]);
  /** The title of the dialog. */
  readonly heading = input<TranslationKey>('todos.new.title');
  /** Offer the Markdown description. */
  readonly withDescription = input(true);
  readonly created = output<TodoCardDetail>();

  readonly title = signal('');
  readonly boards = signal<TodoBoardSummary[]>([]);
  readonly board = signal<TodoBoard | null>(null);
  readonly selectedBoard = signal<Uuid>('');
  readonly column = signal<Uuid>('');
  readonly members = signal<TodoMember[]>([]);
  readonly assignee = signal<Uuid>('');
  readonly due = signal('');
  readonly description = signal('');
  readonly links = signal<NewTodoLink[]>([]);
  readonly pickerOpen = signal(false);
  readonly saving = signal(false);
  readonly noBoard = signal(false);
  private seq = 0;

  readonly boardOptions = computed<SelectOption[]>(() =>
    this.boards()
      .filter((b) => b.canWrite)
      .map((b) => ({ value: b.id, label: b.name })),
  );
  readonly columnOptions = computed<SelectOption[]>(() =>
    sortedColumns(this.board()?.columns ?? []).map((c) => ({ value: c.id, label: c.name })),
  );
  readonly memberOptions = computed<SelectFieldOption[]>(() => {
    const nobody = this.i18n.translate('todos.new.nobody');
    return [
      { value: '', label: nobody, person: { name: nobody, icon: 'user' } },
      ...this.members().map((m) => {
        const label = m.displayName ?? this.i18n.translate('chat.deletedPerson');
        return { value: m.principalId, label, person: { name: label, principalId: m.principalId } };
      }),
    ];
  });
  readonly linkedKeys = computed(() => new Set(this.links().map((l) => linkKey(l.kind, l.targetId))));
  readonly titleError = computed(() =>
    this.title().trim().length > MAX_TITLE ? this.i18n.translate('todos.new.titleTooLong', { max: MAX_TITLE }) : '',
  );
  /** The image upload of the description. A card must not be created while an image
   *  uploads, because its placeholder would go into the description. */
  private readonly images = viewChild(MarkdownImageUploadDirective);
  readonly canSave = computed(
    () =>
      !!this.title().trim() &&
      !this.titleError() &&
      !!this.selectedBoard() &&
      !this.saving() &&
      !this.images()?.uploading(),
  );

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => this.start());
    });
  }

  icon(kind: TodoLinkKind) {
    return LINK_ICON[kind];
  }

  private start(): void {
    this.title.set(this.initialTitle());
    this.links.set([...this.initialLinks()]);
    this.assignee.set('');
    this.due.set('');
    this.description.set('');
    this.saving.set(false);
    this.noBoard.set(false);
    this.pickerOpen.set(false);
    this.api.boards().subscribe({
      next: (boards) => {
        this.boards.set(boards);
        const writable = boards.filter((b) => b.canWrite);
        const gid = this.gremiumId();
        const byKind = this.boardKinds()
          .map((kind) => writable.find((b) => b.kind === kind))
          .find((b) => b !== undefined);
        const pick =
          writable.find((b) => b.id === this.boardId()) ??
          (gid ? writable.find((b) => b.gremiumId === gid) : undefined) ??
          byKind ??
          writable[0];
        if (!pick) {
          this.noBoard.set(true);
          return;
        }
        this.setBoard(pick.id, this.columnId());
      },
      error: () => this.noBoard.set(true),
    });
  }

  setBoard(id: Uuid, columnId: Uuid | null = null): void {
    const seq = ++this.seq;
    this.selectedBoard.set(id);
    this.board.set(null);
    this.column.set('');
    this.members.set([]);
    this.assignee.set('');
    this.api.board(id).subscribe({
      next: (board) => {
        if (seq !== this.seq) return;
        this.board.set(board);
        const cols = sortedColumns(board.columns);
        this.column.set(cols.find((c) => c.id === columnId)?.id ?? cols[0]?.id ?? '');
      },
      error: () => {
        if (seq === this.seq) this.board.set(null);
      },
    });
    this.api.members(id).subscribe({
      next: (list) => {
        if (seq === this.seq) this.members.set(list);
      },
      error: () => {
        if (seq === this.seq) this.members.set([]);
      },
    });
  }

  /** A pick in the picker adds the target; a linked one goes off again. */
  pickLink(hit: TodoLinkTarget): void {
    const key = linkKey(hit.kind, hit.targetId);
    if (this.linkedKeys().has(key)) {
      this.links.update((list) => list.filter((l) => linkKey(l.kind, l.targetId) !== key));
      return;
    }
    const label = `${this.i18n.translate(LINK_KIND_LABEL[hit.kind])} · ${hit.title}`;
    this.links.update((list) => [...list, { kind: hit.kind, targetId: hit.targetId, label }]);
  }

  unlink(link: NewTodoLink): void {
    this.links.update((list) => list.filter((l) => l !== link));
  }

  cancel(): void {
    this.open.set(false);
  }

  save(): void {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.api
      .createCard({
        boardId: this.selectedBoard(),
        columnId: this.column() || undefined,
        title: this.title().trim(),
        descriptionMd: this.description().trim() || null,
        dueDate: this.due() || null,
        assigneeIds: this.assignee() ? [this.assignee()] : [],
        links: this.links().map((l) => ({ kind: l.kind, targetId: l.targetId })),
      })
      .subscribe({
        next: (card) => {
          this.saving.set(false);
          this.open.set(false);
          this.toast.success(this.i18n.translate('todos.new.created'));
          this.created.emit(card);
        },
        error: (err: { error?: { code?: string } }) => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate(this.errorKey(err?.error?.code)));
        },
      });
  }

  private errorKey(code: string | undefined): TranslationKey {
    if (code === 'assignee_not_allowed') return 'todos.error.assignee';
    if (code === 'link_target_not_found') return 'todos.error.linkTarget';
    return 'todos.error.create';
  }
}
