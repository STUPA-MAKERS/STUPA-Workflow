import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import type { Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoBoard,
  type TodoCardDetail,
  type TodoCardMove,
  type TodoCardPatch,
  type TodoCheckItem,
  type TodoComment,
  type TodoLink,
  type TodoLinkTarget,
  type TodoMember,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import { TodoLiveService, batchPings } from '@core/ws/todo-live.service';
import type { TodoPing } from '@core/ws/ws-messages';
import { MarkdownImageUploadDirective } from '@shared/markdown/markdown-image-upload.directive';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { ChatOutbox, draftDropper, sendErrorKey } from '@shared/ui/chat/chat-outbox';
import { ChatComponent } from '@shared/ui/chat/chat.component';
import { ChatDrafts } from '@shared/ui/chat/chat-drafts';
import type { ChatEdit, ChatEvent, ChatMessage, ChatRef, ChatSend } from '@shared/ui/chat/chat.models';
import { appendOnce, toChatAttachments, withScanStates } from '@shared/ui/chat/chat.util';
import { chatPeople } from '@shared/ui/chat/chat-mentions';
import {
  AvatarComponent,
  ButtonComponent,
  ChipComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  MEDIA,
  mediaQuery,
  NoteComponent,
  RowMenuComponent,
  ScrollFadeDirective,
  type RowMenuItem,
  type RowMenuSection,
  SegBarComponent,
  shareOrCopy,
  SheetBarComponent,
  SheetBarTitleDirective,
  SideSheetComponent,
  SkeletonComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { TodoDueChipComponent } from '../due-chip/todo-due-chip.component';
import { TodoLinkPickerComponent, linkKey } from '../link-picker/todo-link-picker.component';
import { TodoMoveSheetComponent, type MoveChoice, type MoveColumn } from '../move-sheet/todo-move-sheet.component';
import { TodoCacheService } from '../todo-cache.service';
import { TodoTransferDialogComponent, type TodoTransferTarget } from '../transfer-dialog/todo-transfer-dialog.component';
import {
  LINK_ICON,
  eventText,
  linkSub,
  linkTitle,
  relativeDays,
  sheetMove,
  splitUrl,
} from '../todos.util';
import { isoDay, weekdayDate } from '@shared/date-format';
import { personName } from '@shared/person-label.util';

/** The error codes of the card routes and their texts. */
const ERROR_TEXT: Record<string, TranslationKey> = {
  card_version_conflict: 'todos.error.cardVersionConflict',
  assignee_not_allowed: 'todos.error.assignee',
  link_exists: 'todos.error.linkExists',
  link_target_not_found: 'todos.error.linkTarget',
  link_self: 'todos.error.linkSelf',
  label_not_on_board: 'todos.error.save',
  mention_not_member: 'todos.error.mention',
  transfer_same_board: 'todos.error.transfer',
  card_moved: 'todos.error.transfer',
  card_archived: 'todos.error.transfer',
  column_not_on_board: 'todos.error.transfer',
  transfer_to_personal: 'todos.error.transferToPersonal',
  todo_write_required: 'todos.error.readOnly',
};

/**
 * One card with all its fields: the board drawer and the right
 * pane of "Aufgaben" use it.
 *
 * Side by side: the thread (`app-chat`: the comments and the events, with no heading of its
 * own; its column is labelled "Aktivität") beside the fields
 * Spalte, Zuständig, Fällig, Label, then "Verknüpft" with the link picker,
 * "Beschreibung" and "Checkliste". Phone: the fields, a bar with "Verschieben" (the move
 * sheet) and "Erledigt", and a chat button with the comment count in the sheet bar that
 * opens the activity in a sheet from the bottom, as the comments of an application. In
 * the board drawer of a phone the sheet bar docks into the bar of the drawer
 * (`app-list-detail-bar`), as in the pane of "Aufgaben".
 *
 * Every change goes to the server at once and the answer replaces the card; `changed`
 * gives it to the board. The content edits (title, description, due date) carry the
 * version; a 409 says "Karte wurde geändert" and reads the card again.
 *
 * Live: a ping of this card (or a `board` ping of its board) from `TodoLiveService` reads
 * the card in the background and takes the server copy, comments included. While a field
 * is in edit (title, description, a checklist item), the transfer dialog is open or a
 * write is in flight, the read waits and runs when that ends. A read that a local change
 * overtook is dropped; a 404 says the card is gone. Nothing goes out: the page takes its
 * own pings.
 *
 * The activity chat exists only while its sheet shows, so a hidden chat does not mark the thread as
 * seen. The phone and the wide layout render the chat in two branches. The page provides
 * `ChatDrafts` and owns the composer files, so a breakpoint change keeps them.
 */
@Component({
  selector: 'app-todo-card-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ChipComponent,
    FormsModule,
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    AvatarComponent,
    ButtonComponent,
    ChatComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    IconComponent,
    MarkdownImageUploadDirective,
    MarkdownViewComponent,
    NoteComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    SegBarComponent,
    SheetBarComponent,
    SheetBarTitleDirective,
    SideSheetComponent,
    SkeletonComponent,
    TodoDueChipComponent,
    TodoLinkPickerComponent,
    TodoMoveSheetComponent,
    TodoTransferDialogComponent,
  ],
  providers: [ChatDrafts],
  host: { '[class.cd--phone]': 'phone()', '[class.cd--pane]': "mode() === 'pane'" },
  templateUrl: './todo-card-detail.component.html',
  styleUrl: './todo-card-detail.component.scss',
})
export class TodoCardDetailComponent {
  private readonly api = inject(TodosApiService);
  private readonly files = inject(ApiClient);
  private readonly apiBase = inject(API_BASE_URL);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  private readonly live = inject(TodoLiveService);
  private readonly router = inject(Router);
  /** The reads of the to-do page, the details read ahead too; absent on other pages. */
  private readonly cache = inject(TodoCacheService, { optional: true });
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly cardId = input.required<Uuid>();
  /** `drawer`: over the board, with a close button. `pane`: the detail of "Aufgaben". */
  readonly mode = input<'drawer' | 'pane'>('drawer');
  /**
   * The pane is a sheet beside the list (wide). Only then the sheet bar bleeds into the
   * padding of the sheet; one pane at a time the detail lies on the page with its gutter.
   */
  readonly split = input(false);
  /** The board around the card, when the page has it: counts and the first card of a column. */
  readonly board = input<TodoBoard | null>(null);

  /** Close the drawer (× or "Zum Board"). */
  readonly closed = output<void>();
  /** The card changed on the server. */
  readonly changed = output<TodoCardDetail>();
  /**
   * The comments of the card changed. Only the count goes out, because the drawer's copy of
   * the rest of the card can be older than the board's: a full card would move it back.
   */
  readonly commentsChanged = output<{ id: Uuid; commentCount: number }>();
  /** The card went into the archive. */
  readonly archived = output<Uuid>();
  /**
   * The card moved to another board (the card menu "In anderes Board verschieben"): the
   * card on its new board and the id of the board it left. It goes out before `changed`,
   * so the page knows that a card new to its board came over and was not restored.
   */
  readonly transferred = output<{ card: TodoCardDetail; fromBoardId: Uuid }>();

  readonly phone = mediaQuery(MEDIA.phone);
  readonly card = signal<TodoCardDetail | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);
  readonly members = signal<TodoMember[]>([]);
  /** Phone: the sheet with the activity (the comments and the events) is open. */
  readonly activityOpen = signal(false);
  readonly busy = signal(false);

  readonly editingTitle = signal(false);
  readonly titleDraft = signal('');
  readonly editingDesc = signal(false);
  readonly descDraft = signal('');
  readonly showDone = signal(false);
  readonly addingItem = signal(false);
  readonly itemDraft = signal('');
  readonly editingItem = signal<Uuid | null>(null);
  readonly itemEditDraft = signal('');
  readonly pickerOpen = signal(false);
  readonly moveOpen = signal(false);
  readonly transferOpen = signal(false);
  readonly transferring = signal(false);

  private seq = 0;
  /** Counts the fresh loads: a write answer from before the card changed is dropped. */
  private gen = 0;
  /** The patches that wait for the answer of the one in flight, which carries the next version. */
  private patchQueue: ((version: number) => void)[] = [];
  private patching = false;
  private membersOf: Uuid | null = null;
  /** Counts the local changes of the card: a background read from before one is dropped. */
  private localSeq = 0;
  /** A ping came while the card could not take a read: read it when that ends. */
  private readonly stale = signal(false);
  /** The board of the shown card, for its pings. */
  private readonly liveBoard = computed(() => this.card()?.boardId ?? null);
  /** A field is in edit or a write is in flight: a background read would overwrite it. */
  readonly editing = computed(
    () =>
      this.editingTitle() ||
      this.editingDesc() ||
      this.addingItem() ||
      this.editingItem() !== null ||
      this.transferOpen() ||
      this.busy(),
  );

  readonly today = signal(isoDay(new Date()));

  readonly outbox = new ChatOutbox<TodoComment>(
    (req) => this.postComment(req),
    (comment) =>
      this.patchComments((c) => ({
        ...c,
        comments: appendOnce(c.comments, comment),
        commentCount: c.commentCount + (c.comments.some((x) => x.id === comment.id) ? 0 : 1),
      })),
    (err) => this.toast.error(this.t(sendErrorKey(err, 'todos.error.comment'))),
    draftDropper(this.files),
  );

  constructor() {
    effect(() => {
      const id = this.cardId();
      untracked(() => this.load(id, true));
    });
    effect(() => {
      const c = this.card();
      if (c) untracked(() => this.cache?.putCard(c));
    });
    effect((onCleanup) => {
      const boardId = this.liveBoard();
      if (!boardId) return;
      const sub = untracked(() =>
        this.live
          .changes$([boardId])
          .pipe(batchPings())
          .subscribe((pings) => this.onPings(pings)),
      );
      onCleanup(() => sub.unsubscribe());
    });
    effect(() => {
      if (this.editing() || !this.stale()) return;
      untracked(() => this.liveRead());
    });
  }

  /**
   * The board of the page when it holds this card, else null. The page also opens the
   * cards of the rows of other boards, and its board must not name or count those.
   */
  readonly pageBoard = computed(() => {
    const b = this.board();
    if (!b) return null;
    const c = this.card();
    if (c && c.id === this.cardId()) return c.boardId === b.id ? b : null;
    const id = this.cardId();
    return b.cards.some((x) => x.id === id) ? b : null;
  });

  /**
   * The line under the title: "Angelegt von <name>" and the day. Each part is one segment
   * that wraps as a whole, so a narrow sheet breaks the line between them, never inside the
   * date.
   */
  readonly createdParts = computed<string[]>(() => {
    const c = this.card();
    if (!c) return [];
    const day = weekdayDate(c.createdAt, this.i18n.formatLocale());
    const by = this.t('todos.card.createdBy', { name: personName(c.createdBy, this.t) });
    return day ? [by, day] : [by];
  });

  readonly archivedLine = computed(() => {
    const at = this.card()?.archivedAt;
    if (!at) return null;
    return weekdayDate(at, this.i18n.formatLocale()) || null;
  });

  readonly canWrite = computed(() => {
    const c = this.card();
    return !!c && c.canWrite && !c.archivedAt;
  });

  readonly isDone = computed(() => {
    const c = this.card();
    return !!c && !!c.columns.find((col) => col.id === c.columnId)?.isDone;
  });

  readonly columnOptions = computed<FilterSelectOption[]>(() =>
    (this.card()?.columns ?? []).map((col) => ({ value: col.id, label: col.name })),
  );

  readonly columnName = computed(() => {
    const c = this.card();
    return c?.columns.find((col) => col.id === c.columnId)?.name ?? '';
  });

  readonly memberOptions = computed<FilterSelectOption[]>(() => {
    const assigned = new Set((this.card()?.assignees ?? []).map((a) => a.principalId));
    return this.members()
      .filter((m) => !assigned.has(m.principalId))
      .map((m) => {
        const label = m.displayName ?? this.t('chat.deletedPerson');
        return { value: m.principalId, label, person: { name: label, principalId: m.principalId } };
      });
  });

  readonly labelOptions = computed<FilterSelectOption[]>(() => {
    const c = this.card();
    if (!c) return [];
    const on = new Set(c.labels.map((l) => l.id));
    return c.boardLabels.filter((l) => !on.has(l.id)).map((l) => ({ value: l.id, label: l.name }));
  });

  readonly dueRelative = computed(() => {
    const day = this.card()?.dueDate;
    return day ? relativeDays(day, this.today(), this.t) : '';
  });

  readonly items = computed(() => [...(this.card()?.checklistItems ?? [])].sort((a, b) => a.position - b.position));
  readonly openItems = computed(() => this.items().filter((i) => !i.done));
  readonly doneItems = computed(() => this.items().filter((i) => i.done));

  readonly linkedKeys = computed(
    () => new Set((this.card()?.links ?? []).map((l) => linkKey(l.kind, l.targetId))),
  );

  /**
   * An own comment changes only on a board that the person writes: a reader of the board
   * (`todo.read_all`) gets 403 `todo_write_required`. An archived card keeps the edit.
   */
  readonly messages = computed<ChatMessage[]>(() => {
    const writes = !!this.card()?.canWrite;
    const comments = (this.card()?.comments ?? []).map<ChatMessage>((c) => ({
      id: c.id,
      author: c.author,
      body: c.body,
      at: c.at,
      editedAt: c.editedAt,
      own: c.isOwn,
      canEdit: c.isOwn && writes,
      attachments: toChatAttachments(this.apiBase, c.attachments),
      mentions: c.mentions,
    }));
    return [...comments, ...this.outbox.messages()];
  });

  /** The "@" list of the comments: the members of the board. */
  readonly mentionables = computed(() => chatPeople(this.members()));

  readonly events = computed<ChatEvent[]>(() =>
    (this.card()?.events ?? []).map((e) => ({
      id: e.id,
      at: e.at,
      text: eventText(e, this.i18n.formatLocale(), this.t),
    })),
  );

  /**
   * The ⋮ menu. In the pane of "Aufgaben" on a phone it also holds "Im Board öffnen": the
   * header of a phone keeps the title and one action, so the link leaves the kicker line.
   */
  readonly menuSections = computed<RowMenuSection[]>(() => {
    const c = this.card();
    if (!c) return [];
    const open: RowMenuSection[] =
      this.mode() === 'pane' && this.phone()
        ? [{ items: [{ id: 'openInBoard', label: this.t('todos.card.openInBoard'), icon: 'kanban' }] }]
        : [];
    if (!c.canWrite) return open;
    if (c.archivedAt) return [...open, { items: [{ id: 'restore', label: this.t('todos.card.restore'), icon: 'undo' }] }];
    return [
      ...open,
      {
        items: [
          { id: 'rename', label: this.t('todos.card.rename'), icon: 'edit' },
          { id: 'transfer', label: this.t('todos.card.transfer'), icon: 'arrow' },
        ],
      },
      { items: [{ id: 'archive', label: this.t('todos.card.archive'), icon: 'archive', danger: true }] },
    ];
  });

  /** The columns of the move sheet, with the counts of the board when the page has it. */
  readonly moveColumns = computed<MoveColumn[]>(() => {
    const c = this.card();
    if (!c) return [];
    const counts = new Map((this.pageBoard()?.columns ?? []).map((col) => [col.id, col.cardCount]));
    return c.columns.map((col) => ({ id: col.id, name: col.name, count: counts.get(col.id) ?? null }));
  });

  readonly boardLink = computed(() => {
    const c = this.card();
    return c ? ['/todos', c.boardId] : null;
  });

  name(ref: { displayName: string | null } | null): string {
    return personName(ref as never, this.t);
  }

  linkIcon(link: TodoLink) {
    return LINK_ICON[link.kind];
  }

  linkTitle(link: TodoLink): string {
    return linkTitle(link, this.t);
  }

  route(url: string) {
    return splitUrl(url);
  }

  linkSub(link: TodoLink): string {
    return linkSub(link, this.i18n.formatLocale(), this.i18n.uiLocale(), this.t);
  }

  /** Read the card again (after a refusal, or from outside). */
  reload(): void {
    this.load(this.cardId(), false);
  }

  /**
   * Read the comments again in the background, for the scan state of their files. Only
   * their scan states change, so a field in edit keeps its text and a comment sent,
   * edited or deleted while the read was in flight stays as it is; a failure changes
   * nothing.
   */
  refreshComments(): void {
    const id = this.cardId();
    const gen = this.gen;
    this.api.card(id).subscribe({
      next: (card) => {
        if (id !== this.cardId() || gen !== this.gen) return;
        this.patchComments((c) => ({ ...c, comments: withScanStates(c.comments, card.comments) }));
      },
      error: () => undefined,
    });
  }

  private onPings(pings: readonly TodoPing[]): void {
    const id = this.cardId();
    if (!pings.some((p) => p.type === 'board' || p.cardId === id)) return;
    if (this.editing()) this.stale.set(true);
    else this.liveRead();
  }

  /** Read the card in the background after a ping; see the class comment. */
  private liveRead(): void {
    this.stale.set(false);
    const id = this.cardId();
    const gen = this.gen;
    const local = this.localSeq;
    this.api.card(id).subscribe({
      next: (card) => {
        if (id !== this.cardId() || gen !== this.gen || local !== this.localSeq) return;
        if (this.editing()) {
          this.stale.set(true);
          return;
        }
        this.card.set(card);
        this.loadMembers(card.boardId);
      },
      error: (err: unknown) => {
        if (id !== this.cardId() || gen !== this.gen || local !== this.localSeq) return;
        if (err instanceof HttpErrorResponse && err.status === 404) {
          this.notFound.set(true);
          this.card.set(null);
        }
      },
    });
  }

  private load(id: Uuid, fresh: boolean): void {
    const seq = ++this.seq;
    if (fresh) {
      this.stale.set(false);
      this.gen++;
      this.patchQueue = [];
      this.patching = false;
      this.busy.set(false);
      this.loading.set(true);
      this.card.set(null);
      this.outbox.clear();
      this.editingTitle.set(false);
      this.editingDesc.set(false);
      this.addingItem.set(false);
      this.editingItem.set(null);
      this.showDone.set(false);
      this.activityOpen.set(false);
    }
    this.notFound.set(false);
    this.error.set(false);
    this.today.set(isoDay(new Date()));
    const held = fresh ? this.cache?.card(id) : null;
    if (held) {
      this.card.set(held);
      this.loading.set(false);
      this.loadMembers(held.boardId);
    }
    const local = this.localSeq;
    this.api.card(id, { detail: fresh }).subscribe({
      next: (card) => {
        if (seq !== this.seq) return;
        if (held && (this.editing() || local !== this.localSeq)) {
          this.stale.set(this.editing());
          return;
        }
        this.card.set(card);
        this.loading.set(false);
        this.loadMembers(card.boardId);
      },
      error: (err: unknown) => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) {
          this.card.set(null);
          this.notFound.set(true);
        } else if (!held) this.error.set(true);
      },
    });
  }

  private loadMembers(boardId: Uuid): void {
    if (this.membersOf === boardId) return;
    this.membersOf = boardId;
    const held = this.cache?.members(boardId);
    if (held) this.members.set(held);
    this.api.members(boardId, { detail: true }).subscribe({
      next: (list) => this.members.set(list),
      error: () => {
        this.membersOf = null;
        this.members.set([]);
      },
    });
  }

  /**
   * Run a write that answers with the card; the answer replaces it. `cardRoute` says the
   * route is the card itself, so its 404 means the card is gone; a 404 of a
   * sub-resource (a checklist item, a link …) reads the card again instead.
   */
  private write(
    req: Observable<TodoCardDetail>,
    after?: (card: TodoCardDetail) => void,
    cardRoute = false,
    failed?: () => void,
  ): void {
    const current = this.current();
    this.busy.set(true);
    req.subscribe({
      next: (card) => {
        if (!current()) return;
        this.busy.set(false);
        this.apply(card);
        after?.(card);
      },
      error: (err: unknown) => {
        if (!current()) return;
        failed?.();
        this.fail(err, cardRoute);
      },
    });
  }

  /**
   * Patch the card with the version it has when the patch goes out. The server raises
   * the version on every patch, so a second patch waits for the answer of the first;
   * sent at once, it would carry the old version and the server would refuse it with 409.
   */
  private patch(c: TodoCardDetail, body: Omit<TodoCardPatch, 'version'>, after?: () => void): void {
    const run = (version: number) => {
      this.patching = true;
      this.write(
        this.api.patchCard(c.id, { ...body, version }),
        (card) => {
          after?.();
          this.patching = false;
          this.patchQueue.shift()?.(card.version);
        },
        true,
        () => {
          this.patching = false;
          this.patchQueue = [];
        },
      );
    };
    if (this.patching) this.patchQueue.push(run);
    else run(c.version);
  }

  /** True while the card that was shown when the request started is still shown. */
  private current(): () => boolean {
    const gen = this.gen;
    return () => gen === this.gen;
  }

  private apply(card: TodoCardDetail): void {
    this.localSeq++;
    this.card.set(card);
    this.changed.emit(card);
  }

  private patchLocal(fn: (c: TodoCardDetail) => TodoCardDetail): void {
    const c = this.card();
    if (!c) return;
    this.apply(fn(c));
  }

  /** Change only the comments: the drawer takes the card, the page only the count. */
  private patchComments(fn: (c: TodoCardDetail) => TodoCardDetail): void {
    const c = this.card();
    if (!c) return;
    const next = fn(c);
    this.localSeq++;
    this.card.set(next);
    this.commentsChanged.emit({ id: next.id, commentCount: next.commentCount });
  }

  private fail(err: unknown, cardRoute: boolean): void {
    this.busy.set(false);
    const e = err instanceof HttpErrorResponse ? err : null;
    const code = (e?.error as { code?: string } | null)?.code;
    if (cardRoute && e?.status === 404) {
      this.notFound.set(true);
      this.card.set(null);
      return;
    }
    this.toast.error(this.t((code && ERROR_TEXT[code]) || 'todos.error.save'));
    this.reload();
  }

  private move(body: TodoCardMove): void {
    const c = this.card();
    if (!c) return;
    const current = this.current();
    this.busy.set(true);
    this.api.moveCard(c.id, body).subscribe({
      next: (tile) => {
        if (!current()) return;
        this.busy.set(false);
        this.patchLocal((cur) => ({ ...cur, ...tile }));
      },
      error: (err: unknown) => {
        if (current()) this.fail(err, true);
      },
    });
  }

  setColumn(columnId: string): void {
    const c = this.card();
    if (!c || columnId === c.columnId) return;
    this.move({ columnId });
  }

  /** The phone sheet: the column and its top or its end. */
  moveTo(choice: MoveChoice): void {
    const c = this.card();
    if (!c) return;
    if (choice.position === 'bottom') {
      this.move({ columnId: choice.columnId });
      return;
    }
    const go = (board: TodoBoard) => this.move(sheetMove(board.cards, c.id, choice.columnId, choice.position));
    const board = this.board();
    if (board && board.id === c.boardId) {
      go(board);
      return;
    }
    const current = this.current();
    this.api.board(c.boardId).subscribe({
      next: (b) => {
        if (current()) go(b);
      },
      error: (err: unknown) => {
        if (current()) this.fail(err, false);
      },
    });
  }

  /** "Erledigt": the end of the done column; on a done card "Wieder öffnen": the first column. */
  toggleDone(): void {
    const c = this.card();
    if (!c) return;
    const target = this.isDone() ? c.columns.find((col) => !col.isDone) : c.columns.find((col) => col.isDone);
    if (target) this.move({ columnId: target.id });
  }

  addAssignee(principalId: string): void {
    const c = this.card();
    if (!c || !principalId) return;
    this.write(this.api.addAssignee(c.id, principalId));
  }

  removeAssignee(principalId: Uuid | null): void {
    const c = this.card();
    if (!c || !principalId) return;
    this.write(this.api.removeAssignee(c.id, principalId));
  }

  setDue(day: string | null): void {
    const c = this.card();
    if (!c) return;
    this.patch(c, { dueDate: day });
  }

  addLabel(labelId: string): void {
    const c = this.card();
    if (!c || !labelId) return;
    this.write(this.api.addCardLabel(c.id, labelId));
  }

  removeLabel(labelId: Uuid): void {
    const c = this.card();
    if (!c) return;
    this.write(this.api.removeCardLabel(c.id, labelId));
  }

  startTitle(): void {
    this.titleDraft.set(this.card()?.title ?? '');
    this.editingTitle.set(true);
  }

  saveTitle(): void {
    const c = this.card();
    const title = this.titleDraft().trim();
    if (!c || !title) return;
    if (title === c.title) {
      this.editingTitle.set(false);
      return;
    }
    this.patch(c, { title }, () => this.editingTitle.set(false));
  }

  /**
   * Move the focus to the element `selector` finds after the next render. An inline editor
   * replaces the button that had the focus, and the focus must stay inside the drawer.
   */
  private focusSoon(...selectors: string[]): void {
    afterNextRender(
      () => {
        const root = this.host.nativeElement;
        for (const sel of selectors) {
          const el = root.querySelector<HTMLElement>(sel);
          if (el) {
            el.focus();
            return;
          }
        }
      },
      { injector: this.injector },
    );
  }

  startDesc(): void {
    this.descDraft.set(this.card()?.descriptionMd ?? '');
    this.editingDesc.set(true);
    this.focusSoon('[data-focus="desc-input"]');
  }

  cancelDesc(): void {
    this.editingDesc.set(false);
    this.focusSoon('[data-focus="desc-edit"] button');
  }

  saveDesc(): void {
    const c = this.card();
    if (!c) return;
    const text = this.descDraft().trim();
    this.patch(c, { descriptionMd: text || null }, () => this.cancelDesc());
  }

  toggleItem(item: TodoCheckItem): void {
    const c = this.card();
    if (!c || !this.canWrite()) return;
    this.write(this.api.patchCheckItem(c.id, item.id, { done: !item.done }));
  }

  addItem(): void {
    const c = this.card();
    const text = this.itemDraft().trim();
    if (!c || !text) return;
    this.write(this.api.addCheckItem(c.id, text), () => this.itemDraft.set(''));
  }

  startAddItem(): void {
    this.addingItem.set(true);
    this.focusSoon('[data-focus="item-new"]');
  }

  cancelItem(): void {
    this.addingItem.set(false);
    this.itemDraft.set('');
    this.focusSoon('[data-focus="item-add"]');
  }

  startItem(item: TodoCheckItem): void {
    this.itemEditDraft.set(item.text);
    this.editingItem.set(item.id);
    this.focusSoon('[data-focus="item-edit"]');
  }

  cancelRename(item: TodoCheckItem): void {
    this.editingItem.set(null);
    this.focusSoon(`[data-rename="${item.id}"] button`);
  }

  renameItem(item: TodoCheckItem): void {
    const c = this.card();
    const text = this.itemEditDraft().trim();
    if (!c || !text || text === item.text) {
      this.cancelRename(item);
      return;
    }
    this.write(this.api.patchCheckItem(c.id, item.id, { text }), () => this.cancelRename(item));
  }

  /** The focus goes to the next item, else the previous one, else the add toggle. */
  deleteItem(item: TodoCheckItem): void {
    const c = this.card();
    if (!c) return;
    const shown = [...(this.showDone() ? this.doneItems() : []), ...this.openItems()];
    const at = shown.findIndex((x) => x.id === item.id);
    const near = shown[at + 1] ?? shown[at - 1];
    this.write(this.api.deleteCheckItem(c.id, item.id), () =>
      this.focusSoon(
        ...(near ? [`[data-item="${near.id}"]`] : []),
        '[data-focus="item-add"]',
        '[data-focus="item-new"]',
      ),
    );
  }

  /** A pick in the link picker: link the target, or take a linked one off. */
  pickLink(hit: TodoLinkTarget): void {
    const c = this.card();
    if (!c) return;
    const link = c.links.find((l) => l.kind === hit.kind && l.targetId === hit.targetId);
    if (link) this.write(this.api.removeLink(c.id, link.id));
    else this.write(this.api.addLink(c.id, hit.kind, hit.targetId));
  }

  removeLink(link: TodoLink): void {
    const c = this.card();
    if (!c) return;
    this.write(this.api.removeLink(c.id, link.id));
  }

  onMenu(item: RowMenuItem): void {
    if (item.id === 'openInBoard') this.openInBoard();
    else if (item.id === 'rename') this.startTitle();
    else if (item.id === 'transfer') this.transferOpen.set(true);
    else if (item.id === 'archive') this.archive();
    else if (item.id === 'restore') this.restore();
  }

  /** Open the card in the drawer of its board ("Im Board öffnen" of the phone menu). */
  openInBoard(): void {
    const c = this.card();
    if (!c) return;
    void this.router.navigate(['/todos', c.boardId], { queryParams: { card: c.id } });
  }

  /**
   * Move the card to another board. The answer is the card on its new board: the page
   * takes it through `changed`, and the people come from the new board.
   */
  transfer(target: TodoTransferTarget): void {
    const c = this.card();
    if (!c) return;
    const current = this.current();
    this.busy.set(true);
    this.transferring.set(true);
    this.api.transferCard(c.id, { boardId: target.boardId, columnId: target.columnId }).subscribe({
      next: (card) => {
        if (!current()) return;
        this.busy.set(false);
        this.transferring.set(false);
        this.transferOpen.set(false);
        this.transferred.emit({ card, fromBoardId: c.boardId });
        this.apply(card);
        this.loadMembers(card.boardId);
        this.toast.success(this.t('todos.card.transferred', { board: target.boardName }));
      },
      error: (err: unknown) => {
        if (!current()) return;
        this.transferring.set(false);
        this.transferOpen.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) {
          this.busy.set(false);
          this.toast.error(this.t('todos.error.transfer'));
          this.reload();
          return;
        }
        this.fail(err, false);
      },
    });
  }

  archive(): void {
    const c = this.card();
    if (!c) return;
    const current = this.current();
    this.busy.set(true);
    this.api.archiveCard(c.id).subscribe({
      next: () => {
        if (!current()) return;
        this.busy.set(false);
        this.toast.success(this.t('todos.card.archived'));
        this.archived.emit(c.id);
      },
      error: (err: unknown) => {
        if (current()) this.fail(err, true);
      },
    });
  }

  restore(): void {
    const c = this.card();
    if (!c) return;
    this.write(this.api.restoreCard(c.id), undefined, true);
  }

  /**
   * The link names the card only, so it stays valid when the card moves to another board. On a
   * phone the share sheet is its own feedback, and a closed sheet is no failure.
   */
  copyLink(): void {
    const c = this.card();
    if (!c) return;
    const url = `${location.origin}/todos?card=${c.id}`;
    void shareOrCopy({ url, title: c.title }).then((outcome) => {
      if (outcome === 'copied') this.toast.success(this.t('todos.card.linkCopied'));
      else if (outcome === 'failed') this.toast.error(this.t('todos.card.linkFailed'));
    });
  }

  private postComment(req: ChatSend): Observable<TodoComment> {
    return this.api.addComment(this.cardId(), req.body, req.mentions ?? [], req);
  }

  sendComment(req: ChatSend): void {
    this.outbox.send(req);
  }

  retryComment(ref: ChatRef): void {
    this.outbox.retry(ref.id);
  }

  discardComment(ref: ChatRef): void {
    this.outbox.discard(ref.id);
  }

  editComment(edit: ChatEdit): void {
    const c = this.card();
    if (!c) return;
    const current = this.current();
    this.api.editComment(c.id, edit.id, edit.body, edit.mentions ?? []).subscribe({
      next: (comment) => {
        if (!current()) return;
        this.patchComments((cur) => ({
          ...cur,
          comments: cur.comments.map((x) => (x.id === comment.id ? comment : x)),
        }));
      },
      error: () => {
        if (!current()) return;
        edit.restore?.();
        this.toast.error(this.t('todos.error.comment'));
      },
    });
  }

  deleteComment(ref: ChatRef): void {
    const c = this.card();
    if (!c) return;
    const current = this.current();
    this.api.deleteComment(c.id, ref.id).subscribe({
      next: () => {
        if (!current()) return;
        this.patchComments((cur) => ({
          ...cur,
          comments: cur.comments.filter((x) => x.id !== ref.id),
          commentCount: Math.max(0, cur.commentCount - 1),
        }));
      },
      error: () => {
        if (current()) this.toast.error(this.t('todos.error.comment'));
      },
    });
  }
}
