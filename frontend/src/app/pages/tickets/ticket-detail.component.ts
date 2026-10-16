import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type { PersonRef, Uuid } from '@core/api/models';
import {
  TICKET_KINDS,
  TicketsApiService,
  type TicketDetail,
  type TicketKind,
  type TicketListItem,
  type TicketNote,
  type TicketPatch,
  type TicketStatus,
} from '@core/api/tickets.service';
import { TodosApiService, type TodoLinkedCard } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { AvatarStackComponent } from '@shared/ui/avatar/avatar.component';
import { ChatOutbox, sendErrorKey } from '@shared/ui/chat/chat-outbox';
import { ChatComponent } from '@shared/ui/chat/chat.component';
import type { ChatEdit, ChatEvent, ChatMessage, ChatRef, ChatSend } from '@shared/ui/chat/chat.models';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { FieldGroupComponent, FieldRowComponent } from '@shared/ui/field-group/field-group.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { SheetBarComponent, SheetBarKickerDirective } from '@shared/ui/sheet-bar/sheet-bar.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import {
  ButtonComponent,
  CheckboxComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  MEDIA,
  TabsComponent,
  ToastService,
  type TabItem,
} from '@stupa-makers/ui-kit';
import { browserLabel, viewportLabel } from '../../features/help/report-context';
import { mediaQuerySignal } from '../../layout/media-query';
import { TicketTodoDialogComponent } from './todo-dialog/ticket-todo-dialog.component';
import { TicketsPageService } from './tickets-page.service';
import {
  KIND_ICON,
  KIND_LABEL,
  STATUS_KIND,
  STATUS_LABEL,
  eventText,
  isOpen,
  personName,
  reporterName,
} from './tickets.util';

type DetailTab = 'log' | 'details';

/** The id of the ticket body in the thread: it never collides with a note id. */
const BODY_ID = 'ticket-body';

/**
 * The detail of a ticket (frames 18, 19, 30–32, 35, 36) in the geometry of the
 * application detail: a header with the state, the kind and the assignee and the main
 * actions ("Erledigt", "Ablehnen"), then side by side the thread "Verlauf" (`app-chat`:
 * the report, the internal notes and the events) and "Details" (reporter, assignee, kind,
 * the linked to-dos, the technical context). One pane at a time the two are tabs.
 *
 * Every note is internal, so the composer has no visibility switch and no attachments.
 * Closing a ticket with open to-dos asks "Offene To-Dos mit erledigen?" (default yes).
 */
@Component({
  selector: 'app-ticket-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    AvatarStackComponent,
    ButtonComponent,
    ChatComponent,
    CheckboxComponent,
    DialogComponent,
    EmptyStateComponent,
    FieldGroupComponent,
    FieldRowComponent,
    FilterSelectComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    RowMenuComponent,
    SheetBarComponent,
    SheetBarKickerDirective,
    SkeletonComponent,
    StatusTextComponent,
    TabsComponent,
    TicketTodoDialogComponent,
  ],
  templateUrl: './ticket-detail.component.html',
  styleUrl: './ticket-detail.component.scss',
})
export class TicketDetailComponent {
  private readonly api = inject(TicketsApiService);
  private readonly todosApi = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(TicketsPageService, { optional: true });

  readonly split = computed(() => this.page?.split() ?? false);
  readonly phone = mediaQuerySignal(MEDIA.phone);

  private id: Uuid = '';
  private seq = 0;
  readonly ticket = signal<TicketDetail | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);
  readonly notes = signal<TicketNote[]>([]);
  readonly todos = signal<TodoLinkedCard[]>([]);
  readonly assignees = signal<PersonRef[]>([]);
  /** A change in flight: the state, the assignee or the kind. */
  readonly saving = signal<'status' | 'assignee' | 'kind' | null>(null);
  readonly tab = signal<DetailTab>('log');

  /** The done question (frame 35): the state to set, and whether the to-dos go along. */
  readonly closing = signal<'done' | 'rejected' | null>(null);
  readonly completeTodos = signal(true);
  /** The ticket a rejection marks as the original, when the question came from the duplicate pick. */
  private closingDuplicateOf: string | null = null;
  /** "Als Duplikat schließen …": the search and the picked ticket. */
  readonly duplicateOpen = signal(false);
  readonly duplicateHits = signal<TicketListItem[]>([]);
  readonly duplicateSearch = liveSearch({
    run: (q) => this.api.list({ q, limit: 8, offset: 0 }),
    result: (page) => this.duplicateHits.set(page.items.filter((t) => t.id !== this.id)),
    reset: () => this.duplicateHits.set([]),
    error: () => this.duplicateHits.set([]),
  });
  readonly todoOpen = signal(false);

  readonly open = computed(() => {
    const t = this.ticket();
    return !!t && isOpen(t.status);
  });
  readonly openTodos = computed(() => this.todos().filter((c) => !c.isDone));
  /** The open to-dos of the close question: the loaded ones, else the count of the ticket. */
  readonly openTodoN = computed(() => this.openTodos().length || this.ticket()?.openTodoCount || 0);

  private readonly t = (key: TranslationKey, params?: Record<string, string | number>): string =>
    this.i18n.translate(key, params);

  readonly reporter = computed(() => {
    const t = this.ticket();
    return t ? reporterName(t.reporter, this.t) : '';
  });

  /** "Ticket · T-0040 · gemeldet 14.10., 21:14". */
  readonly kicker = computed(() => {
    const t = this.ticket();
    if (!t) return '';
    return this.t('tickets.detail.kicker', { number: t.number, when: this.relativeWhen(t.createdAt) });
  });

  /** The kicker around the ticket number, which the bar sets in mono. */
  readonly kickerParts = computed(() => {
    const text = this.kicker();
    const no = this.ticket()?.number ?? '';
    const at = no ? text.indexOf(no) : -1;
    return at < 0 ? { before: text, number: '', after: '' } : { before: text.slice(0, at), number: no, after: text.slice(at + no.length) };
  });

  readonly statusKind = computed(() => STATUS_KIND[this.ticket()?.status ?? 'new']);
  readonly statusLabel = computed(() => this.t(STATUS_LABEL[this.ticket()?.status ?? 'new']));
  readonly kindLabel = computed(() => this.t(KIND_LABEL[this.ticket()?.kind ?? 'bug']));
  readonly kindIcon = computed(() => KIND_ICON[this.ticket()?.kind ?? 'bug']);
  readonly assigneeName = computed(() => {
    const a = this.ticket()?.assignee;
    return a ? personName(a, this.t) : this.t('tickets.detail.unassigned');
  });
  /** The avatar before the assignee in the select; none while nobody is assigned. */
  readonly assigneePerson = computed(() => {
    const a = this.ticket()?.assignee;
    return a ? { name: personName(a, this.t), principalId: a.principalId } : null;
  });

  readonly menuSections = computed<RowMenuSection[]>(() => {
    const t = this.ticket();
    if (!t) return [];
    const sections: RowMenuSection[] = [];
    if (t.status !== 'new') {
      sections.push({ items: [{ id: 'reset', label: this.t('tickets.detail.resetNew'), icon: 'history' }] });
    }
    // The closing action stands apart from the status change, behind a rule.
    if (isOpen(t.status)) {
      sections.push({ items: [{ id: 'duplicate', label: this.t('tickets.detail.duplicate'), icon: 'copy' }] });
    }
    // A new ticket can be a duplicate, any other can go back to "Neu": never empty.
    return sections;
  });

  readonly tabs = computed<TabItem[]>(() => [
    { id: 'log', label: this.t('tickets.detail.log') },
    { id: 'details', label: this.t('tickets.detail.details') },
  ]);

  readonly assigneeOptions = computed<FilterSelectOption[]>(() => {
    const opts: FilterSelectOption[] = [{ value: '', label: this.t('tickets.detail.unassigned') }];
    const seen = new Set<string>();
    const current = this.ticket()?.assignee;
    for (const p of [...this.assignees(), ...(current ? [current] : [])]) {
      if (!p.principalId || seen.has(p.principalId)) continue;
      seen.add(p.principalId);
      opts.push({ value: p.principalId, label: personName(p, this.t) });
    }
    return opts;
  });

  readonly kindOptions = computed<FilterSelectOption[]>(() =>
    TICKET_KINDS.map((k) => ({ value: k, label: this.t(KIND_LABEL[k]) })),
  );

  /** The report as the first message, then the notes, then the pending ones. */
  private readonly outbox = new ChatOutbox<TicketNote>(
    (req) => this.api.addNote(this.id, req.body),
    (created) => this.notes.update((list) => [...list, created]),
    (err) => this.toast.error(this.t(sendErrorKey(err, 'tickets.detail.error.note'))),
  );

  readonly messages = computed<ChatMessage[]>(() => {
    const t = this.ticket();
    if (!t) return [];
    const body: ChatMessage = {
      id: BODY_ID,
      author: t.reporter.principalId ? { principalId: t.reporter.principalId, displayName: t.reporter.displayName } : null,
      authorLabel: this.reporter(),
      body: t.body,
      at: t.createdAt,
      own: false,
      attachments: t.attachments.map((a) => ({
        id: a.id,
        filename: a.filename,
        mime: a.mime,
        size: a.size,
        url: this.api.attachmentUrl(a.id),
      })),
    };
    const notes = this.notes().map<ChatMessage>((n) => ({
      id: n.id,
      author: n.author,
      body: n.body,
      at: n.at,
      editedAt: n.editedAt,
      own: n.isOwn,
    }));
    return [body, ...notes, ...this.outbox.messages()];
  });

  readonly events = computed<ChatEvent[]>(() => {
    const t = this.ticket();
    if (!t) return [];
    return t.events.map((e) => ({
      id: e.id,
      at: e.at,
      text: eventText(e, this.reporter(), this.t),
    }));
  });

  /** The rows of "Technische Angaben". */
  readonly contextRows = computed(() => {
    const c = this.ticket()?.context ?? {};
    const rows: { label: TranslationKey; value: string; href?: string }[] = [];
    if (c.url) rows.push({ label: 'tickets.context.page', value: c.url, href: c.url });
    if (c.appVersion) rows.push({ label: 'tickets.context.version', value: c.appVersion });
    if (c.userAgent || c.viewport) {
      const parts = [c.userAgent ? browserLabel(c.userAgent) : null, c.viewport ? viewportLabel(c.viewport) : null];
      rows.push({ label: 'tickets.context.browser', value: parts.filter(Boolean).join(' · ') });
    }
    return rows;
  });

  readonly contextLink = computed(() => {
    const target = this.ticket()?.contextTarget;
    if (!target) return null;
    return {
      title: target.title,
      link: target.kind === 'application' ? ['/applications', target.id] : ['/meetings', target.id],
    };
  });

  constructor() {
    // The route is `tickets/:id`, so the id is always there.
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => this.load(pm.get('id')!));
    this.api.assignees().subscribe({
      next: (list) => this.assignees.set(list),
      error: () => this.assignees.set([]),
    });
  }

  // --- loading ------------------------------------------------------------

  private load(id: Uuid): void {
    const seq = ++this.seq;
    if (id !== this.id) {
      this.id = id;
      this.outbox.clear();
      this.ticket.set(null);
      this.todos.set([]);
      this.loading.set(true);
      this.tab.set('log');
    }
    this.notFound.set(false);
    this.error.set(false);
    this.api.get(id).subscribe({
      next: (t) => {
        if (seq !== this.seq) return;
        this.show(t);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        if (seq !== this.seq) return;
        this.loading.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
    this.loadTodos();
  }

  private show(t: TicketDetail): void {
    this.ticket.set(t);
    this.notes.set(t.notes);
  }

  loadTodos(): void {
    const id = this.id;
    this.todosApi.linked('ticket', id).subscribe({
      next: (cards) => {
        if (id === this.id) this.todos.set(cards);
      },
      error: () => {
        if (id === this.id) this.todos.set([]);
      },
    });
  }

  // --- header -------------------------------------------------------------

  selectTab(id: string | null): void {
    if (id === 'log' || id === 'details') this.tab.set(id);
  }

  onMenu(item: RowMenuItem): void {
    if (item.id === 'reset') this.patch({ status: 'new' }, 'status');
    if (item.id === 'duplicate') {
      this.duplicateSearch.clear();
      this.duplicateHits.set([]);
      this.duplicateOpen.set(true);
    }
  }

  /** Copy the link of the ticket. */
  async copyLink(): Promise<void> {
    try {
      await navigator.clipboard.writeText(location.href.split('?')[0]);
      this.toast.success(this.t('tickets.detail.linkCopied'));
    } catch {
      this.toast.error(this.t('tickets.detail.linkFailed'));
    }
  }

  /** "Erledigt" or "Ablehnen". With open to-dos the dialog asks first. */
  close(status: 'done' | 'rejected'): void {
    const t = this.ticket();
    if (!t || this.saving()) return;
    this.closingDuplicateOf = null;
    if (this.hasOpenTodos(t)) {
      this.completeTodos.set(true);
      this.closing.set(status);
      return;
    }
    this.patch({ status }, 'status');
  }

  confirmClose(): void {
    const status = this.closing();
    if (!status) return;
    const duplicateOfId = this.closingDuplicateOf;
    this.closing.set(null);
    this.closingDuplicateOf = null;
    const body: TicketPatch = { status, completeTodos: this.completeTodos() };
    if (duplicateOfId) body.duplicateOfId = duplicateOfId;
    this.patch(body, 'status', true);
  }

  /** Close the question without a change. */
  cancelClose(): void {
    this.closing.set(null);
    this.closingDuplicateOf = null;
  }

  reopen(): void {
    this.patch({ status: 'in_progress' }, 'status');
  }

  pickDuplicate(hit: TicketListItem): void {
    this.duplicateOpen.set(false);
    const t = this.ticket();
    if (!t || this.saving()) return;
    if (this.hasOpenTodos(t)) {
      this.closingDuplicateOf = hit.id;
      this.completeTodos.set(true);
      this.closing.set('rejected');
      return;
    }
    this.patch({ status: 'rejected', duplicateOfId: hit.id }, 'status');
  }

  private hasOpenTodos(t: TicketDetail): boolean {
    return this.openTodos().length > 0 || t.openTodoCount > 0;
  }

  setAssignee(value: string): void {
    const current = this.ticket()?.assignee?.principalId ?? '';
    if (value === current) return;
    this.patch({ assigneeId: value || null }, 'assignee');
  }

  setKind(value: string): void {
    if (!TICKET_KINDS.includes(value as TicketKind) || value === this.ticket()?.kind) return;
    this.patch({ kind: value as TicketKind }, 'kind');
  }

  private patch(body: TicketPatch, what: 'status' | 'assignee' | 'kind', todos = false): void {
    if (this.saving()) return;
    const id = this.id;
    this.saving.set(what);
    this.api.patch(id, body).subscribe({
      next: (t) => {
        this.saving.set(null);
        if (id !== this.id) return;
        this.show(t);
        this.page?.notify(id);
        if (todos) this.loadTodos();
      },
      error: (err: unknown) => {
        this.saving.set(null);
        this.toast.error(this.t(this.patchError(err)));
      },
    });
  }

  private patchError(err: unknown): TranslationKey {
    const code = err instanceof HttpErrorResponse ? (err.error as { code?: string } | null)?.code : undefined;
    if (code === 'assignee_not_allowed') return 'tickets.detail.error.assignee';
    if (code === 'duplicate_invalid') return 'tickets.detail.error.duplicate';
    return 'tickets.detail.error.save';
  }

  // --- notes --------------------------------------------------------------

  sendNote(req: ChatSend): void {
    this.outbox.send({ body: req.body });
  }

  retryNote(ref: ChatRef): void {
    this.outbox.retry(ref.id);
  }

  discardNote(ref: ChatRef): void {
    this.outbox.discard(ref.id);
  }

  editNote(change: ChatEdit): void {
    if (change.id === BODY_ID) return;
    this.api.editNote(this.id, change.id, change.body).subscribe({
      next: (n) => this.notes.update((list) => list.map((x) => (x.id === n.id ? n : x))),
      error: () => {
        change.restore?.();
        this.toast.error(this.t('tickets.detail.error.note'));
      },
    });
  }

  deleteNote(ref: ChatRef): void {
    if (ref.id === BODY_ID) return;
    this.api.deleteNote(this.id, ref.id).subscribe({
      next: () => this.notes.update((list) => list.filter((x) => x.id !== ref.id)),
      error: () => this.toast.error(this.t('tickets.detail.error.note')),
    });
  }

  // --- to-dos -------------------------------------------------------------

  onTodoCreated(): void {
    this.loadTodos();
    this.load(this.id);
  }

  todoSub(card: TodoLinkedCard): string {
    const parts = [card.boardName, card.columnName];
    if (card.dueDate) parts.push(this.t('tickets.todos.due', { date: this.shortDate(card.dueDate) }));
    return parts.join(' · ');
  }

  todoNames(card: TodoLinkedCard): string[] {
    return card.assignees.map((a) => personName(a, this.t));
  }

  todoIds(card: TodoLinkedCard): (string | null)[] {
    return card.assignees.map((a) => a.principalId);
  }

  statusOf(status: TicketStatus): string {
    return this.t(STATUS_LABEL[status]);
  }

  // --- formatting ---------------------------------------------------------

  /** "14.10., 21:14". */
  /** "heute, 08:12", "gestern, 21:14", else "14.10., 21:14". */
  private relativeWhen(at: string): string {
    const d = new Date(at);
    const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.round((day(new Date()) - day(d)) / 86_400_000);
    if (days !== 0 && days !== 1) return this.when(at);
    const time = new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(d);
    return `${this.t(days === 0 ? 'tickets.age.today' : 'tickets.age.yesterday')}, ${time}`;
  }

  private when(at: string): string {
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(new Date(at));
  }

  /** `YYYY-MM-DD` as "17.10.". */
  private shortDate(date: string): string {
    const [y, m, d] = date.split('-').map(Number);
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), { day: '2-digit', month: '2-digit' }).format(
      new Date(y, m - 1, d),
    );
  }

  reportedAt(t: TicketDetail): string {
    return this.when(t.createdAt);
  }
}
