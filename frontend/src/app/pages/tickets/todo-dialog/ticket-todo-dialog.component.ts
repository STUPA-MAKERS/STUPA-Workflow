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
import type { TicketDetail } from '@core/api/tickets.service';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardSummary,
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
  type IconName,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { SelectFieldComponent } from '@shared/ui/select/select.component';
import { TodoLinkPickerComponent, linkKey } from '../../../features/todos/link-picker/todo-link-picker.component';
import { LINK_ICON, LINK_KIND_LABEL } from '../../../features/todos/todos.util';

/** A further link of the new card, picked in the dialog. */
interface ExtraLink {
  kind: TodoLinkKind;
  targetId: Uuid;
  kindLabel: string;
  title: string;
}

/** The most characters of a card title (server rule). */
const MAX_TITLE = 300;

/**
 * "To-Do aus Ticket anlegen" (frame 33): a card that links the ticket.
 *
 * The title starts as the title of the ticket. The board starts as the team board (the
 * board "Plattform" of `ticket.manage`), else the personal board; the column as the
 * first column. The person and the due date are optional. The link to the ticket goes
 * along; the reporter never sees it (one-way). "Verknüpfen" adds further links with the
 * picker of the card drawer.
 */
@Component({
  selector: 'app-ticket-todo-dialog',
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
    SelectFieldComponent,
    TodoLinkPickerComponent,
  ],
  templateUrl: './ticket-todo-dialog.component.html',
  styleUrl: './ticket-todo-dialog.component.scss',
})
export class TicketTodoDialogComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly ticket = input.required<TicketDetail>();
  readonly open = model(false);
  /** The card was created. */
  readonly created = output<void>();

  readonly title = signal('');
  readonly boards = signal<TodoBoardSummary[]>([]);
  readonly boardId = signal<Uuid>('');
  readonly board = signal<TodoBoard | null>(null);
  readonly columnId = signal<Uuid>('');
  readonly members = signal<TodoMember[]>([]);
  readonly assigneeId = signal<Uuid>('');
  readonly dueDate = signal('');
  /** The link to the ticket; the reporter can take it off. */
  readonly linked = signal(true);
  /** The links picked in the dialog, after the ticket. */
  readonly links = signal<ExtraLink[]>([]);
  readonly pickerOpen = signal(false);
  readonly linkedKeys = computed(() => {
    const keys = new Set(this.links().map((l) => linkKey(l.kind, l.targetId)));
    if (this.linked()) keys.add(linkKey('ticket', this.ticket().id));
    return keys;
  });
  readonly saving = signal(false);
  /** The boards did not load, or no board can take a card. */
  readonly noBoard = signal(false);
  private boardSeq = 0;

  readonly boardOptions = computed<SelectOption[]>(() =>
    this.boards()
      .filter((b) => b.canWrite)
      .map((b) => ({ value: b.id, label: b.name })),
  );
  readonly columnOptions = computed<SelectOption[]>(() =>
    (this.board()?.columns ?? []).map((c) => ({ value: c.id, label: c.name })),
  );
  readonly memberOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('tickets.todo.nobody') },
    ...this.members().map((m) => ({
      value: m.principalId,
      label: m.displayName ?? this.i18n.translate('chat.deletedPerson'),
    })),
  ]);

  readonly titleError = computed(() =>
    this.title().trim().length > MAX_TITLE ? this.i18n.translate('tickets.todo.titleTooLong', { max: MAX_TITLE }) : '',
  );
  readonly canSave = computed(
    () => !!this.title().trim() && !this.titleError() && !!this.boardId() && !this.saving(),
  );

  constructor() {
    // Each opening starts from the ticket and reads the boards again.
    effect(() => {
      if (!this.open()) return;
      untracked(() => this.start());
    });
  }

  private start(): void {
    const t = this.ticket();
    this.title.set(t.title);
    this.assigneeId.set('');
    this.dueDate.set('');
    this.linked.set(true);
    this.links.set([]);
    this.pickerOpen.set(false);
    this.saving.set(false);
    this.noBoard.set(false);
    this.api.boards().subscribe({
      next: (boards) => {
        this.boards.set(boards);
        const writable = boards.filter((b) => b.canWrite);
        const pick =
          writable.find((b) => b.kind === 'team') ?? writable.find((b) => b.kind === 'personal') ?? writable[0];
        if (!pick) {
          this.noBoard.set(true);
          return;
        }
        this.setBoard(pick.id);
      },
      error: () => this.noBoard.set(true),
    });
  }

  setBoard(id: Uuid): void {
    const seq = ++this.boardSeq;
    this.boardId.set(id);
    this.board.set(null);
    this.columnId.set('');
    this.members.set([]);
    this.assigneeId.set('');
    this.api.board(id).subscribe({
      next: (board) => {
        if (seq !== this.boardSeq) return;
        this.board.set(board);
        const first = [...board.columns].sort((a, b) => a.position - b.position)[0];
        this.columnId.set(first?.id ?? '');
      },
      error: () => {
        if (seq === this.boardSeq) this.board.set(null);
      },
    });
    this.api.members(id).subscribe({
      next: (list) => {
        if (seq === this.boardSeq) this.members.set(list);
      },
      error: () => {
        if (seq === this.boardSeq) this.members.set([]);
      },
    });
  }

  icon(kind: TodoLinkKind): IconName {
    return LINK_ICON[kind];
  }

  /** A pick in the picker adds the target; a linked one goes off again. */
  pickLink(hit: TodoLinkTarget): void {
    const key = linkKey(hit.kind, hit.targetId);
    if (hit.kind === 'ticket' && hit.targetId === this.ticket().id) {
      this.linked.update((on) => !on);
      return;
    }
    if (this.linkedKeys().has(key)) {
      this.links.update((list) => list.filter((l) => linkKey(l.kind, l.targetId) !== key));
      return;
    }
    const kindLabel = this.i18n.translate(LINK_KIND_LABEL[hit.kind]);
    this.links.update((list) => [...list, { kind: hit.kind, targetId: hit.targetId, kindLabel, title: hit.title }]);
  }

  unlink(link: ExtraLink): void {
    this.links.update((list) => list.filter((l) => l !== link));
  }

  cancel(): void {
    this.open.set(false);
  }

  save(): void {
    if (!this.canSave()) return;
    const t = this.ticket();
    this.saving.set(true);
    this.api
      .createCard({
        boardId: this.boardId(),
        columnId: this.columnId() || undefined,
        title: this.title().trim(),
        dueDate: this.dueDate() || null,
        assigneeIds: this.assigneeId() ? [this.assigneeId()] : [],
        links: [
          ...(this.linked() ? [{ kind: 'ticket' as const, targetId: t.id }] : []),
          ...this.links().map((l) => ({ kind: l.kind, targetId: l.targetId })),
        ],
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.open.set(false);
          this.toast.success(this.i18n.translate('tickets.todo.created'));
          this.created.emit();
        },
        error: (err: { error?: { code?: string } }) => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate(this.errorKey(err?.error?.code)));
        },
      });
  }

  private errorKey(code: string | undefined): TranslationKey {
    if (code === 'assignee_not_allowed') return 'tickets.todo.error.assignee';
    return 'tickets.todo.error.save';
  }
}
