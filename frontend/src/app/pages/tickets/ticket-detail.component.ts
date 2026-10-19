import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { type Observable, map, tap } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { API_BASE_URL } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import type { PersonRef, ScanState, Uuid } from '@core/api/models';
import {
  TICKET_KINDS,
  TicketsApiService,
  type MyTicketDetail,
  type TicketAttachment,
  type TicketDetail,
  type TicketKind,
  type TicketListItem,
  type TicketNote,
  type TicketPatch,
  type TicketReporter,
  type TicketStatus,
} from '@core/api/tickets.service';
import { TodosApiService, type TodoBoardKind, type TodoLinkedCard } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { ChatOutbox, draftDropper, sendErrorKey } from '@shared/ui/chat/chat-outbox';
import { ChatComponent } from '@shared/ui/chat/chat.component';
import type {
  ChatEdit,
  ChatEvent,
  ChatMessage,
  ChatRef,
  ChatSend,
  ChatVisibility,
} from '@shared/ui/chat/chat.models';
import { ChatDrafts } from '@shared/ui/chat/chat-drafts';
import { chatPeople } from '@shared/ui/chat/chat-mentions';
import { appendOnce, toChatAttachments, withScanStates } from '@shared/ui/chat/chat.util';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FieldGroupComponent,
  FieldRowComponent,
} from '@shared/ui/field-group/field-group.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui/row-menu/row-menu.component';
import {
  SheetBarComponent,
  SheetBarTitleDirective,
} from '@shared/ui/sheet-bar/sheet-bar.component';
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
import { TodoLinkedListComponent } from '../../features/todos/linked-list/todo-linked-list.component';
import {
  TodoNewDialogComponent,
  type NewTodoLink,
} from '../../features/todos/new-dialog/todo-new-dialog.component';
import { mediaQuerySignal } from '../../layout/media-query';
import { TicketsPageService } from './tickets-page.service';
import {
  KIND_ICON,
  KIND_LABEL,
  STATUS_KIND,
  STATUS_LABEL,
  eventText,
  isOpen,
  personName,
  reporterEventText,
  reporterName,
} from './tickets.util';
import { copyToClipboard } from '@shared/clipboard';

type DetailTab = 'log' | 'details';

/** The fragment of a link to one note: `#note-<id>`. */
const NOTE_FRAGMENT = /^note-(.+)$/;
/**
 * The scan state of a report file: the three-state `scanState` of the server, so that
 * a file with a finding shows as quarantined and not as a link. `scanned` alone only
 * says that the scan ended; it is the fallback of a server without `scanState`.
 */
export function reportScanState(a: TicketAttachment): ScanState {
  return a.scanState ?? (a.scanned ? 'clean' : 'scanning');
}

/** The refusals of a block that say why; any other gets the general text. */
const BLOCK_ERROR: Readonly<Record<string, TranslationKey>> = {
  sender_is_self: 'tickets.detail.error.blockSelf',
  ticket_sender_unknown: 'tickets.detail.error.senderUnknown',
};

/** The text of a refused block or unblock. */
export function blockErrorKey(err: unknown): TranslationKey {
  const code =
    err instanceof HttpErrorResponse ? (err.error as { code?: string } | null)?.code : undefined;
  return (code && BLOCK_ERROR[code]) || 'tickets.detail.error.block';
}

/** The id of the ticket body in the thread: it never collides with a note id. */
const BODY_ID = 'ticket-body';

/** The composer of the team on a ticket of an account: internal first, the safe default. */
const TEAM_VISIBILITIES: readonly ChatVisibility[] = ['internal', 'public'];

/**
 * The own ticket of a reporter in the shape of the team detail: no assignee, no
 * context, no to-dos; the events are the status changes without an actor.
 */
export function fromMine(m: MyTicketDetail, reporter: TicketReporter): TicketDetail {
  return {
    id: m.id,
    number: m.number,
    kind: m.kind,
    title: m.title,
    status: m.status,
    reporter,
    assignee: null,
    createdAt: m.createdAt,
    updatedAt: m.updatedAt,
    body: m.body,
    context: {},
    attachments: m.attachments,
    notes: m.notes,
    events: m.events.map((e) => ({ ...e, actor: null })),
    duplicateOf: null,
    contextTarget: null,
    openTodoCount: 0,
    closedAt: m.closedAt,
    anonymizedAt: null,
    senderBlocked: false,
  };
}

/**
 * The detail of a ticket (frames 18, 19, 30–32, 35, 36) in the geometry of the
 * application detail: a header with the state, the kind and the assignee and the main
 * actions ("Erledigt", "Ablehnen"), then side by side the thread "Verlauf" (`app-chat`:
 * the report, the internal notes and the events) and "Details" (reporter, assignee, kind,
 * the linked to-dos, the technical context). One pane at a time the two are tabs.
 *
 * A note of the team is internal or public; the composer offers the switch (internal
 * first) when an account reported the ticket, because only an account reads a public
 * note. A note takes up to 5 files (not on an anonymized ticket).
 *
 * Without `ticket.manage` the page is the view of the reporter on an own ticket
 * (`/tickets/mine`): the report, the public notes and the status changes, the own
 * messages, the kind and the report time. No actions, no menu, no assignee, no to-dos,
 * no technical context. A block of the sender hides the composer. Closing a ticket with open to-dos asks "Offene
 * To-Dos mit erledigen?" (default yes). The ⋮ menu blocks or unblocks the sender (frame
 * 19) at once, with a toast (contract 12.8: no question); the own report offers no
 * block. While a file of the report or
 * a note is in the scan, the chat asks for the thread again (`refreshThread`), and only
 * the scan states of that read change the page.
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
    SheetBarTitleDirective,
    SkeletonComponent,
    StatusTextComponent,
    TabsComponent,
    TodoNewDialogComponent,
    TodoLinkedListComponent,
  ],
  // The two layouts re-create the chat; the composer files stay with the page.
  providers: [ChatDrafts],
  templateUrl: './ticket-detail.component.html',
  styleUrl: './ticket-detail.component.scss',
})
export class TicketDetailComponent {
  private readonly api = inject(TicketsApiService);
  private readonly files = inject(ApiClient);
  private readonly apiBase = inject(API_BASE_URL);
  private readonly todosApi = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(TicketsPageService, { optional: true });
  private readonly injector = inject(Injector);
  /** The status buttons: a close or a reopen swaps them, so the focus moves to the new one. */
  private readonly actions = viewChild<ElementRef<HTMLElement>>('actions');

  readonly split = computed(() => this.page?.split() ?? false);
  /** The team view; else the view of the reporter on an own ticket. */
  readonly manager = this.auth.can('ticket.manage');
  /** The reporter may write: false while a block holds back the sender. */
  readonly canReply = signal(true);
  readonly phone = mediaQuerySignal(MEDIA.phone);

  private id: Uuid = '';
  private seq = 0;
  /** The note of the `#note-` link that the log already showed for this ticket. */
  private linkedNote: string | null = null;
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
  /** A to-do of the ticket starts on the team board of `ticket.manage`, else the personal one. */
  readonly todoBoardKinds: readonly TodoBoardKind[] = ['team', 'personal'];
  /** The link of a new to-do to this ticket: "Ticket · T-0040 Titel". */
  readonly todoLinks = computed<NewTodoLink[]>(() => {
    const t = this.ticket();
    if (!t) return [];
    const label = `${this.i18n.translate('todos.linkKind.ticket')} · ${t.number} ${t.title}`;
    return [{ kind: 'ticket', targetId: t.id, label }];
  });
  /** A block or an unblock in flight. */
  readonly blocking = signal(false);

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
    return a
      ? { name: personName(a, this.t), principalId: a.principalId }
      : { name: this.t('tickets.detail.unassigned'), icon: 'user' as const };
  });

  readonly menuSections = computed<RowMenuSection[]>(() => {
    const t = this.ticket();
    if (!t || !this.manager) return [];
    const sections: RowMenuSection[] = [];
    if (t.status !== 'new') {
      sections.push({
        items: [{ id: 'reset', label: this.t('tickets.detail.resetNew'), icon: 'history' }],
      });
    }
    // The closing action and the block stand apart from the status change, behind a rule.
    const apart: RowMenuItem[] = [];
    if (isOpen(t.status))
      apart.push({ id: 'duplicate', label: this.t('tickets.detail.duplicate'), icon: 'copy' });
    // An anonymized ticket has no sender any more, and nobody blocks themselves.
    if (!t.anonymizedAt && !this.ownReport(t.reporter)) {
      apart.push(
        t.senderBlocked
          ? { id: 'unblock', label: this.t('tickets.detail.unblockSender'), icon: 'lock' }
          : { id: 'block', label: this.t('tickets.detail.blockSender'), icon: 'lock' },
      );
    }
    if (apart.length) sections.push({ items: apart });
    // A new ticket can be a duplicate, any other can go back to "Neu": never empty.
    return sections;
  });

  readonly tabs = computed<TabItem[]>(() => [
    { id: 'log', label: this.t('tickets.detail.log') },
    { id: 'details', label: this.t('tickets.detail.details') },
  ]);

  readonly assigneeOptions = computed<FilterSelectOption[]>(() => {
    const nobody = this.t('tickets.detail.unassigned');
    const opts: FilterSelectOption[] = [{ value: '', label: nobody, person: { name: nobody, icon: 'user' } }];
    const seen = new Set<string>();
    const current = this.ticket()?.assignee;
    for (const p of [...this.assignees(), ...(current ? [current] : [])]) {
      if (!p.principalId || seen.has(p.principalId)) continue;
      seen.add(p.principalId);
      const label = personName(p, this.t);
      opts.push({ value: p.principalId, label, person: { name: label, principalId: p.principalId } });
    }
    return opts;
  });

  readonly kindOptions = computed<FilterSelectOption[]>(() =>
    TICKET_KINDS.map((k) => ({ value: k, label: this.t(KIND_LABEL[k]) })),
  );

  /** The visibility switch of the team composer: only an account reads a public note. */
  readonly visibilityOptions = computed<readonly ChatVisibility[]>(() => {
    const t = this.ticket();
    return this.manager && t && t.reporter.principalId && !t.anonymizedAt ? TEAM_VISIBILITIES : [];
  });

  readonly placeholder = computed<TranslationKey>(() =>
    this.visibilityOptions().length || !this.manager
      ? 'chat.placeholder'
      : 'tickets.detail.notePlaceholder',
  );

  /** The report as the first message, then the notes, then the pending ones. */
  private readonly outbox = new ChatOutbox<TicketNote>(
    (req) =>
      this.manager
        ? this.api.addNote(this.id, req.body, req, req.visibility, req.mentions)
        : this.api.addMyNote(this.id, req.body, req),
    (created) => this.notes.update((list) => appendOnce(list, created)),
    (err) =>
      this.toast.error(
        this.t(this.blockedKey(err) ?? sendErrorKey(err, 'tickets.detail.error.note')),
      ),
    draftDropper(this.files),
  );

  /** The "@" list of the staff: the holders of `ticket.manage`. The reporter gets none. */
  readonly mentionables = computed(() => (this.manager ? chatPeople(this.assignees()) : []));

  readonly messages = computed<ChatMessage[]>(() => {
    const t = this.ticket();
    if (!t) return [];
    const body: ChatMessage = {
      id: BODY_ID,
      author: t.reporter.principalId
        ? { principalId: t.reporter.principalId, displayName: t.reporter.displayName }
        : null,
      authorLabel: this.manager ? this.reporter() : null,
      body: t.body,
      at: t.createdAt,
      // The reporter reads the own report on the right, without an edit.
      own: !this.manager,
      canEdit: false,
      visibility: this.visibilityOptions().length ? 'public' : null,
      attachments: t.attachments.map((a) => ({
        id: a.id,
        filename: a.filename,
        mime: a.mime,
        size: a.size,
        url: this.api.attachmentUrl(a.id),
        scanState: reportScanState(a),
      })),
    };
    const notes = this.notes().map<ChatMessage>((n) => ({
      id: n.id,
      author: n.author,
      body: n.body,
      at: n.at,
      editedAt: n.editedAt,
      own: n.isOwn,
      attachments: toChatAttachments(this.apiBase, n.attachments),
      visibility: this.manager ? (n.visibility ?? 'internal') : null,
      mentions: n.mentions,
    }));
    return [body, ...notes, ...this.outbox.messages()];
  });

  readonly events = computed<ChatEvent[]>(() => {
    const t = this.ticket();
    if (!t) return [];
    return t.events.map((e) => ({
      id: e.id,
      at: e.at,
      text: this.manager
        ? eventText(e, this.reporter(), this.t)
        : reporterEventText(e.payload, this.t),
    }));
  });

  /** The rows of "Technische Angaben". */
  readonly contextRows = computed(() => {
    const c = this.ticket()?.context ?? {};
    const rows: { label: TranslationKey; value: string; href?: string }[] = [];
    if (c.url) rows.push({ label: 'tickets.context.page', value: c.url, href: c.url });
    if (c.appVersion) rows.push({ label: 'tickets.context.version', value: c.appVersion });
    if (c.userAgent || c.viewport) {
      const parts = [
        c.userAgent ? browserLabel(c.userAgent) : null,
        c.viewport ? viewportLabel(c.viewport) : null,
      ];
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
    if (!this.manager) return;
    this.api.assignees().subscribe({
      next: (list) => this.assignees.set(list),
      error: () => this.assignees.set([]),
    });
  }

  // --- loading ------------------------------------------------------------

  /** Load the ticket again after a failed load. */
  retry(): void {
    this.loading.set(true);
    this.load(this.id);
  }

  private load(id: Uuid): void {
    const seq = ++this.seq;
    if (id !== this.id) {
      this.id = id;
      this.outbox.clear();
      this.ticket.set(null);
      this.todos.set([]);
      this.loading.set(true);
      this.tab.set('log');
      this.linkedNote = null;
    }
    this.notFound.set(false);
    this.error.set(false);
    this.read(id).subscribe({
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

  /** The ticket: the team detail, or the own ticket of the reporter in the same shape. */
  private read(id: Uuid): Observable<TicketDetail> {
    if (this.manager) return this.api.get(id);
    const me: TicketReporter = {
      principalId: null,
      displayName: this.auth.displayName() || null,
      email: null,
      anonymized: false,
    };
    return this.api.getMine(id).pipe(
      tap((m) => this.canReply.set(m.canReply)),
      map((m) => fromMine(m, me)),
    );
  }

  /**
   * Read the ticket again in the background, for the scan state of its files. Only the
   * scan states change: the read can be older than a note, an edit, a delete or a block
   * that ended while it was in flight. A failure keeps the page as it is; the next read
   * or a reload tries again.
   */
  refreshThread(): void {
    const id = this.id;
    const seq = this.seq;
    this.read(id).subscribe({
      next: (t) => {
        if (id === this.id && seq === this.seq) this.takeScanStates(t);
      },
      error: () => undefined,
    });
  }

  private takeScanStates(fresh: TicketDetail): void {
    const cur = this.ticket();
    if (cur) {
      const report = new Map(fresh.attachments.map((a) => [a.id, a]));
      const attachments = cur.attachments.map((a) => {
        const f = report.get(a.id);
        return f ? { ...a, scanned: f.scanned, scanState: f.scanState } : a;
      });
      this.ticket.set({ ...cur, attachments });
    }
    this.notes.update((list) => withScanStates(list, fresh.notes));
  }

  private show(t: TicketDetail): void {
    this.ticket.set(t);
    this.notes.set(t.notes);
    this.showLinkedNote();
  }

  /**
   * A link to a note (`#note-<id>`, the mention mail) opens the log and scrolls the note
   * into view once the thread rendered. A note that is gone leaves the log at its end.
   * This happens once per ticket: a reload after a change leaves the tab and the scroll.
   */
  private showLinkedNote(): void {
    const id = NOTE_FRAGMENT.exec(this.route.snapshot.fragment ?? '')?.[1];
    if (!id || this.linkedNote === id || !this.notes().some((n) => n.id === id)) return;
    this.linkedNote = id;
    this.tab.set('log');
    afterNextRender(
      () => {
        const el = document.querySelector(`[data-msg-id="${CSS.escape(id)}"]`);
        el?.scrollIntoView?.({ block: 'center' });
      },
      { injector: this.injector },
    );
  }

  loadTodos(): void {
    if (!this.manager) return;
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
    if (item.id === 'block') this.setBlocked(true);
    if (item.id === 'unblock') this.setBlocked(false);
  }

  private setBlocked(block: boolean): void {
    if (this.blocking()) return;
    const id = this.id;
    this.blocking.set(true);
    (block ? this.api.blockSender(id) : this.api.unblockSender(id)).subscribe({
      next: (t) => {
        this.blocking.set(false);
        if (id !== this.id) return;
        this.ticket.set(t);
        this.toast.success(
          this.t(block ? 'tickets.detail.senderBlocked' : 'tickets.detail.senderUnblocked'),
        );
      },
      error: (err: unknown) => {
        this.blocking.set(false);
        this.toast.error(this.t(blockErrorKey(err)));
      },
    });
  }

  /** The viewer filed the report: the e-mail of the report is the own one. */
  private ownReport(reporter: TicketReporter): boolean {
    const own = this.auth.principal()?.email?.trim().toLowerCase();
    return !!own && reporter.email?.trim().toLowerCase() === own;
  }

  /** Copy the link of the ticket. */
  async copyLink(): Promise<void> {
    if (await copyToClipboard(location.href.split('?')[0])) {
      this.toast.success(this.t('tickets.detail.linkCopied'));
    } else {
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
        const wasOpen = this.open();
        this.show(t);
        if (what === 'status' && wasOpen !== this.open()) this.focusActions();
        this.page?.notify(id);
        if (todos) this.loadTodos();
      },
      error: (err: unknown) => {
        this.saving.set(null);
        this.toast.error(this.t(this.patchError(err)));
      },
    });
  }

  /**
   * "Erledigt", "Ablehnen" and "Wieder öffnen" remove the button that has the focus. Give
   * the focus to the button that takes its place, so it does not fall back to the page.
   */
  private focusActions(): void {
    afterNextRender(
      () => this.actions()?.nativeElement.querySelector<HTMLElement>('button')?.focus(),
      {
        injector: this.injector,
      },
    );
  }

  /** A block that the team set while the reporter had the ticket open closes the composer. */
  private blockedKey(err: unknown): TranslationKey | null {
    const code =
      err instanceof HttpErrorResponse ? (err.error as { code?: string } | null)?.code : undefined;
    if (err instanceof HttpErrorResponse && err.status === 403 && code === 'sender_blocked') {
      this.canReply.set(false);
      return 'tickets.detail.error.blocked';
    }
    return null;
  }

  private patchError(err: unknown): TranslationKey {
    const code =
      err instanceof HttpErrorResponse ? (err.error as { code?: string } | null)?.code : undefined;
    if (code === 'assignee_not_allowed') return 'tickets.detail.error.assignee';
    if (code === 'duplicate_invalid') return 'tickets.detail.error.duplicate';
    return 'tickets.detail.error.save';
  }

  // --- notes --------------------------------------------------------------

  sendNote(req: ChatSend): void {
    this.outbox.send(req);
  }

  retryNote(ref: ChatRef): void {
    this.outbox.retry(ref.id);
  }

  discardNote(ref: ChatRef): void {
    this.outbox.discard(ref.id);
  }

  editNote(change: ChatEdit): void {
    if (change.id === BODY_ID) return;
    const edit = this.manager
      ? this.api.editNote(this.id, change.id, change.body, change.mentions)
      : this.api.editMyNote(this.id, change.id, change.body);
    edit.subscribe({
      next: (n) => this.notes.update((list) => list.map((x) => (x.id === n.id ? n : x))),
      error: (err: unknown) => {
        change.restore?.();
        this.toast.error(this.t(this.blockedKey(err) ?? 'tickets.detail.error.note'));
      },
    });
  }

  deleteNote(ref: ChatRef): void {
    if (ref.id === BODY_ID) return;
    const remove = this.manager
      ? this.api.deleteNote(this.id, ref.id)
      : this.api.deleteMyNote(this.id, ref.id);
    remove.subscribe({
      next: () => this.notes.update((list) => list.filter((x) => x.id !== ref.id)),
      error: () => this.toast.error(this.t('tickets.detail.error.note')),
    });
  }

  // --- to-dos -------------------------------------------------------------

  onTodoCreated(): void {
    this.loadTodos();
    this.load(this.id);
  }

  statusOf(status: TicketStatus): string {
    return this.t(STATUS_LABEL[status]);
  }

  // --- formatting ---------------------------------------------------------

  /** "14.10., 21:14". */
  private when(at: string): string {
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(new Date(at));
  }

  reportedAt(t: TicketDetail): string {
    return this.when(t.createdAt);
  }
}
