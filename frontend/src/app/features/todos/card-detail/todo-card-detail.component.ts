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
import { RouterLink } from '@angular/router';
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
import type { TranslationKey } from '@core/i18n/translations';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { ChatOutbox, draftDropper, sendErrorKey } from '@shared/ui/chat/chat-outbox';
import { ChatComponent } from '@shared/ui/chat/chat.component';
import type { ChatEdit, ChatEvent, ChatMessage, ChatRef, ChatSend } from '@shared/ui/chat/chat.models';
import { toChatAttachments } from '@shared/ui/chat/chat.util';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { SheetBarComponent } from '@shared/ui/sheet-bar/sheet-bar.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import {
  ButtonComponent,
  IconComponent,
  MEDIA,
  TabsComponent,
  ToastService,
  type TabItem,
} from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { TodoDueChipComponent } from '../due-chip/todo-due-chip.component';
import { TodoLinkPickerComponent, linkKey } from '../link-picker/todo-link-picker.component';
import { TodoMoveSheetComponent, type MoveChoice, type MoveColumn } from '../move-sheet/todo-move-sheet.component';
import {
  LINK_ICON,
  eventText,
  isoDay,
  linkSub,
  linkTitle,
  longDay,
  mentionIds,
  personName,
  relativeDays,
  splitUrl,
  type Translate,
} from '../todos.util';

type CardTab = 'details' | 'activity';

/** The error codes of the card routes and their texts. */
const ERROR_TEXT: Record<string, TranslationKey> = {
  card_version_conflict: 'todos.error.cardVersionConflict',
  assignee_not_allowed: 'todos.error.assignee',
  link_exists: 'todos.error.linkExists',
  link_target_not_found: 'todos.error.linkTarget',
  link_self: 'todos.error.linkSelf',
  label_not_on_board: 'todos.error.save',
  mention_not_member: 'todos.error.mention',
};

/**
 * One card with all its fields (frames 2–4, 10, 12–13): the board drawer and the right
 * pane of "Aufgaben" use it.
 *
 * Side by side: "Aktivität" (`app-chat`: the comments and the events) beside the fields
 * Spalte, Zuständig, Fällig, Label, then "Verknüpft" with the link picker,
 * "Beschreibung" and "Checkliste". Phone: the tabs Details | Aktivität and a bar with
 * "Verschieben" (the move sheet) and "Erledigt".
 *
 * Every change goes to the server at once and the answer replaces the card; `changed`
 * gives it to the board. The content edits (title, description, due date) carry the
 * version; a 409 says "Karte wurde geändert" and reads the card again.
 */
@Component({
  selector: 'app-todo-card-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
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
    MarkdownViewComponent,
    NoteComponent,
    RowMenuComponent,
    SheetBarComponent,
    SkeletonComponent,
    TabsComponent,
    TodoDueChipComponent,
    TodoLinkPickerComponent,
    TodoMoveSheetComponent,
  ],
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
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly cardId = input.required<Uuid>();
  /** `drawer`: over the board, with a close button. `pane`: the detail of "Aufgaben". */
  readonly mode = input<'drawer' | 'pane'>('drawer');
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

  readonly phone = mediaQuerySignal(MEDIA.phone);
  readonly card = signal<TodoCardDetail | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);
  readonly members = signal<TodoMember[]>([]);
  readonly tab = signal<CardTab>('details');
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

  private seq = 0;
  /** Counts the fresh loads: a write answer from before the card changed is dropped. */
  private gen = 0;
  /** The patches that wait for the answer of the one in flight, which carries the next version. */
  private patchQueue: ((version: number) => void)[] = [];
  private patching = false;
  private membersOf: Uuid | null = null;

  readonly today = signal(isoDay(new Date()));

  readonly outbox = new ChatOutbox<TodoComment>(
    (req) => this.postComment(req),
    (comment) =>
      this.patchComments((c) => ({ ...c, comments: [...c.comments, comment], commentCount: c.commentCount + 1 })),
    (err) => this.toast.error(this.t(sendErrorKey(err, 'todos.error.comment'))),
    draftDropper(this.files),
  );

  constructor() {
    effect(() => {
      const id = this.cardId();
      untracked(() => this.load(id, true));
    });
  }

  // ------------------------------------------------------------------ derived

  readonly kicker = computed(() => {
    const c = this.card();
    return c ? this.t('todos.card.kicker', { board: c.boardName }) : '';
  });

  readonly createdLine = computed(() => {
    const c = this.card();
    if (!c) return '';
    const d = new Date(c.createdAt);
    const day = Number.isNaN(d.getTime()) ? '' : longDay(isoDay(d), this.i18n.formatLocale());
    return this.t('todos.card.created', { name: personName(c.createdBy, this.t), date: day });
  });

  readonly archivedLine = computed(() => {
    const at = this.card()?.archivedAt;
    if (!at) return null;
    const d = new Date(at);
    return Number.isNaN(d.getTime()) ? null : longDay(isoDay(d), this.i18n.formatLocale());
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
      .map((m) => ({ value: m.principalId, label: m.displayName ?? this.t('chat.deletedPerson') }));
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
  readonly progress = computed(() => {
    const total = this.items().length;
    return total ? Math.round((this.doneItems().length / total) * 100) : 0;
  });

  readonly linkedKeys = computed(
    () => new Set((this.card()?.links ?? []).map((l) => linkKey(l.kind, l.targetId))),
  );

  readonly messages = computed<ChatMessage[]>(() => {
    const comments = (this.card()?.comments ?? []).map<ChatMessage>((c) => ({
      id: c.id,
      author: c.author,
      body: c.body,
      at: c.at,
      editedAt: c.editedAt,
      own: c.isOwn,
      attachments: toChatAttachments(this.apiBase, c.attachments),
    }));
    return [...comments, ...this.outbox.messages()];
  });

  readonly events = computed<ChatEvent[]>(() =>
    (this.card()?.events ?? []).map((e) => ({
      id: e.id,
      at: e.at,
      text: eventText(e, this.i18n.formatLocale(), this.t),
    })),
  );

  readonly tabs = computed<TabItem[]>(() => [
    { id: 'details', label: this.t('todos.card.details') },
    { id: 'activity', label: this.t('todos.card.activity'), count: this.card()?.comments.length ?? 0 },
  ]);

  readonly menuSections = computed<RowMenuSection[]>(() => {
    const c = this.card();
    if (!c || !c.canWrite) return [];
    if (c.archivedAt) return [{ items: [{ id: 'restore', label: this.t('todos.card.restore'), icon: 'undo' }] }];
    return [
      { items: [{ id: 'rename', label: this.t('todos.card.rename'), icon: 'edit' }] },
      { items: [{ id: 'archive', label: this.t('todos.card.archive'), icon: 'archive', danger: true }] },
    ];
  });

  /** The columns of the move sheet, with the counts of the board when the page has it. */
  readonly moveColumns = computed<MoveColumn[]>(() => {
    const c = this.card();
    if (!c) return [];
    const counts = new Map((this.board()?.columns ?? []).map((col) => [col.id, col.cardCount]));
    return c.columns.map((col) => ({ id: col.id, name: col.name, count: counts.get(col.id) ?? null }));
  });

  readonly boardLink = computed(() => {
    const c = this.card();
    return c ? ['/todos', c.boardId] : null;
  });

  // ------------------------------------------------------------------ helpers for the template

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
    return linkSub(link, this.i18n.formatLocale(), this.i18n.locale(), this.t);
  }

  // ------------------------------------------------------------------ load

  /** Read the card again (after a refusal, or from outside). */
  reload(): void {
    this.load(this.cardId(), false);
  }

  /**
   * Read the comments again in the background, for the scan state of their files. Only
   * the comments change, so a field in edit keeps its text; a failure changes nothing.
   */
  refreshComments(): void {
    const id = this.cardId();
    const gen = this.gen;
    this.api.card(id).subscribe({
      next: (card) => {
        if (id !== this.cardId() || gen !== this.gen) return;
        this.patchComments((c) => ({ ...c, comments: card.comments, commentCount: card.commentCount }));
      },
      error: () => undefined,
    });
  }

  private load(id: Uuid, fresh: boolean): void {
    const seq = ++this.seq;
    if (fresh) {
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
      this.tab.set('details');
    }
    this.notFound.set(false);
    this.error.set(false);
    this.today.set(isoDay(new Date()));
    this.api.card(id).subscribe({
      next: (card) => {
        if (seq !== this.seq) return;
        this.card.set(card);
        this.loading.set(false);
        this.loadMembers(card.boardId);
      },
      error: (err: unknown) => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
  }

  private loadMembers(boardId: Uuid): void {
    if (this.membersOf === boardId) return;
    this.membersOf = boardId;
    this.api.members(boardId).subscribe({
      next: (list) => this.members.set(list),
      error: () => {
        this.membersOf = null;
        this.members.set([]);
      },
    });
  }

  // ------------------------------------------------------------------ writes

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
    const first = (board: TodoBoard) =>
      board.cards.find((x) => x.columnId === choice.columnId && x.id !== c.id)?.id ?? null;
    const go = (board: TodoBoard) => {
      const top = first(board);
      this.move(top ? { columnId: choice.columnId, beforeId: top } : { columnId: choice.columnId });
    };
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
    this.focusSoon(`[data-rename="${item.id}"]`);
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
    if (item.id === 'rename') this.startTitle();
    else if (item.id === 'archive') this.archive();
    else if (item.id === 'restore') this.restore();
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

  copyLink(): void {
    const c = this.card();
    if (!c) return;
    const url = `${location.origin}/todos/${c.boardId}?card=${c.id}`;
    const clip = navigator.clipboard;
    if (!clip) {
      this.toast.error(this.t('todos.card.linkFailed'));
      return;
    }
    clip.writeText(url).then(
      () => this.toast.success(this.t('todos.card.linkCopied')),
      () => this.toast.error(this.t('todos.card.linkFailed')),
    );
  }

  // ------------------------------------------------------------------ comments

  private postComment(req: ChatSend): Observable<TodoComment> {
    return this.api.addComment(this.cardId(), req.body, mentionIds(req.body, this.members()), req);
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
    this.api.editComment(c.id, edit.id, edit.body, mentionIds(edit.body, this.members())).subscribe({
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

  selectTab(id: string): void {
    this.tab.set(id === 'activity' ? 'activity' : 'details');
  }
}
