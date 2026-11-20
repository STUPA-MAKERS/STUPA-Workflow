import { FeatureService } from '@core/features/feature.service';
import type { EditorMode } from '../top-sheet/top-sheet.component';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  Injector,
  input,
  model,
  output,
  signal,
  type TemplateRef,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { LiveViewer } from '@core/ws/ws-messages';
import type {
  AgendaItem,
  Attendance,
  Meeting,
  MeetingVote,
  Protocol,
  Uuid,
} from '@core/api/models';
import {
  AvatarComponent,
  ButtonComponent,
  EmptyStateComponent,
  ButtonGroupComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  observeElementSize,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SegmentedComponent,
  type SegmentedOption,
  SideSheetComponent,
} from '@stupa-makers/ui-kit';
import { meetingStatus, protocolStatus } from '@shared/status-kind.util';
import { ProtocolBarComponent } from '../protocol-bar/protocol-bar.component';
import { protocolActions, protocolMenuItems } from '../protocol-bar/protocol-actions.util';
import { longDate } from '@shared/date-format';
import {
  type AgendaMove,
  AgendaPaneComponent,
  canChangeAgenda,
  canEditTop,
} from '../agenda-pane/agenda-pane.component';
import {
  type AttendanceChange,
  AttendanceSheetComponent,
} from '../attendance-sheet/attendance-sheet.component';
import { type DockPanel, SessionDockComponent } from '../session-dock/session-dock.component';
import { type SaveState, TopSheetComponent } from '../top-sheet/top-sheet.component';
import { VoteCardComponent } from '../vote-card/vote-card.component';
import { firstMeetingLink } from '../meeting-kind.util';
import { voteSnippet, votesInText } from '../meetings.util';
import { voteOptionLabel } from '../meetings-display.util';
import { openWindowClock, openWindowState, openWindowWhen } from '../open-window.util';
import { JoinQrComponent } from '../public-join/join-qr.component';
import { MeetingHeadComponent } from '../meeting-head/meeting-head.component';
import { topLead } from '../top-application-lead.util';
import { TodoLinkedListComponent } from '../../todos/linked-list/todo-linked-list.component';
import { clock, weekdayDate } from '@shared/date-format';
import { pageItemTitle } from '../../../layout/page-title.service';

/** The ids of the session menu. */
type SessionAction = 'todos' | 'links' | 'open' | 'agenda' | 'settings' | 'attendance' | 'votes' | 'keeper' | 'beamer' | 'qr' | 'close' | 'delete';

/**
 * The session page of the meeting lead and the minute-taker (`/meetings/:id`).
 *
 * The header carries the title, the status, "Gremium · date · seit HH:MM", the session
 * menu and, above the phone width, the main action: "Sitzung eröffnen" of a planned meeting
 * or "Sitzung schließen" of a live one, at the same place (spec 000096). On a phone both are
 * items of the session menu. The opening is disabled with its reason until a minute-taker is
 * set and the open window opens; before the window the button reads "Möglich ab …". Below the header the agenda pane, the sheet of the open item and the
 * cards of its votes. A planned meeting opens on its first agenda item, so the text and
 * the votes can be prepared before the start. The dock at the foot steps through the
 * agenda and holds the attendance and the minute-taker (on a phone before the opening:
 * the session menu).
 *
 * A closed meeting shows the state of its protocol as the status of the header, the
 * finalize or the PDF as the main action, and the other protocol actions as the first
 * section of the session menu (spec 001304). The
 * attendance opens as a side sheet. A minute-taker picked in the dock of a live meeting
 * goes to the handover dialog of `MeetingsComponent`.
 *
 * Wide (>= 1200px): the agenda beside the sheet. Below that the agenda moves into a sheet
 * from the start edge. The vote cards are a side sheet at every width (spec 001460), opened
 * from an icon button of the dock whose number turns to the accent colour while a vote of the
 * item runs (from the session menu while a planned meeting has no item to write and so no
 * dock). Above the phone width the sheet opens by itself once per vote for a person who
 * still has to vote (spec 001462). On a phone the agenda sheet, the attendance and the
 * minute-taker open as bottom sheets, and an open vote of the item takes the place of the
 * text, with a switch back to the text (spec 001461).
 *
 * The reason for a disabled action is visible text, not only a tooltip, because a disabled button
 * takes no focus and no touch. The agenda sheet stays outside the body, because the scroll fade of
 * the body is a mask, and a mask clips the fixed sheet and its scrim to the box of the body.
 */
@Component({
  selector: 'app-meeting-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MeetingHeadComponent,
    ScrollFadeDirective,
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    EmptyStateComponent,
    ButtonGroupComponent,
    IconComponent,
    RowMenuComponent,
    SegmentedComponent,
    SideSheetComponent,
    AgendaPaneComponent,
    SessionDockComponent,
    TopSheetComponent,
    TodoLinkedListComponent,
    VoteCardComponent,
    AttendanceSheetComponent,
    JoinQrComponent,
    AvatarComponent,
    ProtocolBarComponent,
  ],
  templateUrl: './meeting-page.component.html',
  styleUrl: './meeting-page.component.scss',
  host: {
    '[style.--fx-dock-h.px]': 'dockHeight()',
  },
})
export class MeetingPageComponent {
  private readonly i18n = inject(I18nService);
  private readonly dock = viewChild.required(SessionDockComponent, { read: ElementRef });

  /** Three columns from 1200px; below that the agenda is a sheet. */
  protected readonly wide = mediaQuery(MEDIA.wide);
  protected readonly phone = mediaQuery(MEDIA.phone);
  /**
   * Height of the dock. On a phone the dock is fixed to the viewport, so the page keeps
   * this much room below its content.
   */
  protected readonly dockHeight = signal(0);

  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol | null>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The agenda item open in the sheet, plus its 0-based index. */
  readonly top = input.required<AgendaItem | null>();
  readonly topIndex = input.required<number>();
  /**
   * Write the minutes. Once a minute-taker is named only that person edits the text.
   * Everybody else with `canWrite` reads the page.
   */
  readonly canEdit = input.required<boolean>();
  readonly saveState = input.required<SaveState>();
  readonly attendance = input.required<Attendance[]>();
  readonly savingAttendance = input.required<boolean>();
  readonly viewers = input.required<readonly LiveViewer[]>();
  readonly casting = input.required<Uuid | null>();
  readonly deletingVote = input.required<Uuid | null>();
  readonly finalizing = input.required<boolean>();
  /** Own choice per vote id, from this session. */
  readonly choices = input.required<Record<string, string>>();
  readonly savingAgenda = input.required<boolean>();
  readonly renamingTopId = input.required<Uuid | null>();
  readonly renameDraft = model<string>('');
  /** The member whose "present" the server refused (409 `delegation_active`). */
  readonly attendanceConflict = input<Uuid | null>(null);

  /** Leave the session page for the meeting list. */
  readonly back = output<void>();
  readonly selectTop = output<Uuid>();
  /** "Nächster TOP": the next item, and the item that the room leaves (the server ticks it). */
  readonly nextTop = output<{ id: Uuid; from: Uuid }>();
  readonly bodyChange = output<{ itemId: Uuid; body: string }>();
  readonly castVote = output<{ voteId: Uuid; choice: string }>();
  readonly voteOpen = output<Uuid>();
  readonly voteClose = output<Uuid>();
  /** The lot of an election was drawn, or its runoff opened. */
  readonly electionChanged = output<void>();
  readonly voteCancel = output<Uuid>();
  readonly voteDelete = output<Uuid>();
  readonly voteDialog = output<AgendaItem>();
  /** "Bearbeiten" of a prepared vote, or "Erneut abstimmen" of a closed one. */
  readonly voteSource = output<{ mode: 'edit' | 'repeat'; vote: MeetingVote }>();
  readonly startSession = output<void>();
  readonly closeSession = output<void>();
  readonly finalize = output<void>();
  readonly openSettings = output<void>();
  readonly deleteMeeting = output<void>();
  readonly toggleBeamer = output<void>();
  readonly attendanceChange = output<AttendanceChange>();
  readonly attendanceReset = output<Attendance>();
  /** The delegation of the refused member was revoked in the attendance sheet. */
  readonly attendanceConflictResolved = output<Uuid>();
  /** Open "TOP hinzufügen". */
  readonly addTop = output<void>();
  readonly removeFromAgenda = output<Uuid>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly setNonPublic = output<{ item: AgendaItem; nonPublic: boolean }>();
  /** Set or remove the done mark of an item ("TOP abhaken"). */
  readonly setDone = output<{ item: AgendaItem; done: boolean }>();
  /** "Dauer ändern" in the agenda (§ 001140). */
  readonly setDuration = output<{ item: AgendaItem; minutes: number | null }>();
  readonly moveTop = output<AgendaMove>();
  /** Name the minute-taker of a planned meeting. */
  readonly setProtokollant = output<Uuid>();
  /** A member was picked in the dock to take the minutes of a live meeting over. */
  readonly pickHandover = output<Uuid>();
  /** Discard the planned handover. */
  readonly cancelHandover = output<void>();

  /** The dock panel that is open: a popover above the dock, a bottom sheet on a phone. */
  readonly panel = signal<DockPanel>('none');
  /** The large QR code of a public meeting: the header popover or the phone sheet. */
  readonly qrOpen = signal(false);
  /** The agenda sheet below the wide layout. */
  readonly agendaOpen = signal(false);
  /** The side sheet of the vote cards (a bottom sheet on a phone, spec 001460). */
  readonly votesOpen = signal(false);
  /** The votes for which the sheet opened by itself, so it opens only once each (spec 001462). */
  private readonly autoOpened = signal<ReadonlySet<string>>(new Set());
  /** The open vote for which the phone shows the text instead of the card (spec 001461). */
  readonly textShownFor = signal<string | null>(null);
  /** The sheet "To-Dos" with the cards that link the meeting (spec 000551). */
  readonly todosOpen = signal(false);
  protected readonly todoList = viewChild<TodoLinkedListComponent>('todoList');
  /** The side sheet of the linked rows of the open item (a bottom sheet on a phone, spec 001800). */
  readonly linksOpen = signal(false);
  protected readonly topLinks = viewChild<TodoLinkedListComponent>('topLinks');
  /** The list of the people who have the meeting open. */
  protected readonly presenceOpen = signal(false);

  /** Raised by an insert from outside the editor, so the editor loads the new text. */
  protected readonly revision = signal(0);

  constructor() {
    pageItemTitle(() => this.meeting().title);
    // Spec 001462: once per vote, for a person who may still vote, above the phone width.
    effect(() => {
      const v = this.openVote();
      if (!v || this.phone() || !this.meeting().canVote || v.myBallot?.cast) return;
      if (untracked(() => this.autoOpened().has(v.id))) return;
      untracked(() => {
        this.autoOpened.update((ids) => new Set([...ids, v.id]));
        this.votesOpen.set(true);
      });
    });
    observeElementSize(
      () => this.dock().nativeElement,
      (size) => this.dockHeight.set(size.height),
      'border',
    );
  }

  /** The status of the head: the state of the protocol once the meeting is closed (spec 001304). */
  protected readonly status = computed(() => {
    const m = this.meeting();
    const p = this.protocol();
    return m.status === 'closed' && p ? protocolStatus(p) : meetingStatus(m.status);
  });
  /** The protocol part of the head: its action, its dialogs and its menu section. */
  private readonly protocolBar = viewChild(ProtocolBarComponent);
  protected readonly locked = computed(() => this.protocol()?.isLocked ?? false);
  /**
   * The text of the item can be written. A planned meeting has no protocol yet, but its
   * text can be prepared; the start creates the protocol around it.
   */
  /** The view of the protocol text, shared by the sheet and the icon button of the phone dock. */
  protected readonly editorMode = signal<EditorMode>('formatted');
  /** The done mark of the open item for the dock, or `null` for no button there. */
  protected readonly dockDone = computed<boolean | null>(() => {
    const t = this.top();
    return this.editable() && t ? !!t.doneAt : null;
  });
  /**
   * The vote icon button of the dock, for the minute-taker only: the number of votes, or
   * `null`. Everybody else opens the votes from the tab at the end edge, on a phone from the
   * session menu (spec 001460).
   */
  protected readonly dockVotes = computed<number | null>(() =>
    this.meeting().isProtokollant && this.showVotes() ? this.votes().length : null,
  );
  /** The open vote that a phone shows in the place of the text, or `null` (spec 001461). */
  protected readonly phoneVote = computed<MeetingVote | null>(() =>
    this.phone() ? this.openVote() : null,
  );
  /** The phone shows the text, not the card, for the open vote. */
  protected readonly showText = computed(() => {
    const v = this.phoneVote();
    return !!v && this.textShownFor() === v.id;
  });
  /** The switch above the open vote on a phone: the vote or the text of the item. */
  protected readonly swapOptions = computed<SegmentedOption[]>(() => [
    { value: 'vote', label: this.i18n.translate('meetings.vote.inPlaceVote') },
    { value: 'text', label: this.i18n.translate('meetings.vote.inPlaceText') },
  ]);
  /** The view switch in the dock, while an item is open and its text is not locked. A planned
   * meeting has no protocol yet, but the text of its items can be prepared. */
  protected readonly dockModeToggle = computed(() => {
    const p = this.protocol();
    if (this.top() === null) return false;
    return this.meeting().status === 'planned' ? !p?.isLocked : !!p && !p.isLocked;
  });
  /** The sheet of the open item: the dock runs its format tools. */
  protected readonly sheet = viewChild(TopSheetComponent);
  private readonly formatTpl = viewChild<TemplateRef<unknown>>('formatTpl');
  /** The format tools of the dock ("Aa" on a phone), while the text of the item can be written. */
  protected readonly dockFormat = computed<TemplateRef<unknown> | null>(() =>
    this.dockModeToggle() && this.editable() ? (this.formatTpl() ?? null) : null,
  );
  protected readonly editable = computed(
    () =>
      (this.protocol() !== null || this.meeting().status === 'planned') &&
      !this.locked() &&
      this.canEdit(),
  );

  /** "TOP hinzufügen" in the header of the agenda sheet, and the rename by a click on the title. */
  protected readonly canAddTop = computed(() => canChangeAgenda(this.meeting(), this.locked()));
  /** The title of the open item changes until the protocol is locked (§ 000982). */
  protected readonly canRenameTop = computed(() => canEditTop(this.meeting(), this.locked()));

  /**
   * The row of the application of the open item, the first row of the linked list above
   * the sheet (`topLead`), or the row of its Haushaltsplan.
   */
  protected readonly applicationLead = topLead(this.top, inject(Injector), this.i18n);

  /** "Studierendenparlament · Di, 29.09.2026 · seit 18:04". */
  protected readonly subLine = computed(() => {
    const m = this.meeting();
    const locale = this.i18n.formatLocale();
    const started = clock(m.startedAt, locale);
    const closed = clock(m.closedAt, locale);
    const time =
      m.status === 'live' && started
        ? [this.i18n.translate('meetings.page.since', { time: started })]
        : m.status === 'closed' && started
          ? [closed ? `${started}–${closed}` : started]
          : m.startTime
            ? [m.startTime.slice(0, 5)]
            : [];
    return [
      ...(m.gremiumName ? [m.gremiumName] : []),
      ...(m.date ? [this.dateText(m.date)] : []),
      ...time,
    ].join(' · ');
  });

  /**
   * The link of the head: the meeting that approved the protocol (spec 001304), else the
   * first meeting of a Wiederholungssitzung (§ 000940). The phone bar has one line below the
   * title, so there the status "Protokoll genehmigt" stands alone.
   */
  protected readonly headLink = computed(() => {
    const p = this.protocol();
    if (this.meeting().status === 'closed' && p?.approvedAt) {
      if (this.phone() || !p.approvedMeetingId) return null;
      const date = longDate(p.approvedMeetingDate ?? '', this.i18n.formatLocale());
      const meeting = [p.approvedMeetingTitle, date].filter(Boolean).join(' · ');
      return {
        label: this.i18n.translate('meetings.protocolHead.approvedIn', { meeting }),
        to: `/meetings/${p.approvedMeetingId}`,
      };
    }
    return firstMeetingLink(this.meeting(), this.i18n);
  });

  /** Presence is shown to the people who run the meeting, while it is live. */
  protected readonly showPresence = computed(() => {
    const m = this.meeting();
    return m.status === 'live' && m.canWrite;
  });
  protected readonly presenceTitle = computed(() =>
    this.viewers().length
      ? this.i18n.translate('meetings.page.viewers', { names: this.viewers().map((v) => v.name).join(', ') })
      : this.i18n.translate('meetings.viewers.empty'),
  );

  /**
   * The main action of the header: open a planned meeting or close a live one. A closed
   * meeting shows the action of its protocol at the same place (spec 001304). `null` when the
   * viewer has none.
   */
  private readonly now = openWindowClock();
  /** Where now is in the open window of a planned meeting (see `openWindowState`). */
  protected readonly openWindow = computed(() => openWindowState(this.meeting(), this.now()));
  /** "Möglich ab 17:00", the reason of the disabled "Sitzung eröffnen" while the window is not open yet, else `''`. */
  protected readonly opensAtText = computed(() => {
    const at = this.meeting().opensAt;
    if (this.openWindow() !== 'tooEarly' || !at) return '';
    const when = openWindowWhen(at, this.now(), this.i18n.locale());
    return this.i18n.translate('meetings.control.opensAt', { when });
  });

  /** Why "Sitzung eröffnen" is disabled (no minute-taker, or "Möglich ab …"), else `null`. */
  protected readonly openBlocked = computed<string | null>(() =>
    this.meeting().protokollantId
      ? this.opensAtText() || null
      : this.i18n.translate('meetings.control.needProtokollant'),
  );

  protected readonly mainAction = computed<'open' | 'close' | null>(() => {
    const m = this.meeting();
    if (m.status === 'planned' && m.canControl) return 'open';
    if (m.status === 'live' && m.canControl) return 'close';
    return null;
  });

  /**
   * The session menu: settings, attendance and delete. Below the wide layout the beamer
   * of a planned or live meeting goes in here too; on a phone the header keeps only the title, so the opening (first)
   * and the close move in as well (the protocol action too). Above the phone width both are header buttons.
   *
   * The beamer route and its stream need session.manage in the gremium.
   */
  protected readonly menu = computed<readonly RowMenuSection[]>(() => {
    const m = this.meeting();
    const t = (key: Parameters<I18nService['translate']>[0]): string => this.i18n.translate(key);
    const when = (on: boolean, item: RowMenuItem): readonly RowMenuItem[] => (on ? [item] : []);
    // A phone dock holds the attendance and the votes as icon buttons; it is hidden only while a
    // planned meeting has no item open (no agenda yet).
    const noDock = this.phone() && m.status === 'planned' && !this.top();
    const keeper =
      (m.status === 'planned' && m.canManage) ||
      (m.status === 'live' && (m.canManage || m.isProtokollant));
    const main: readonly RowMenuItem[] = [
      ...when(this.phone() && this.mainAction() === 'open', {
        id: 'open',
        label: t('meetings.control.open'),
        icon: 'play',
        disabledReason: this.openBlocked(),
      }),
      // Below the wide layout the agenda is a sheet, and the menu opens it.
      ...when(!this.wide(), { id: 'agenda', label: t('meetings.agenda.title'), icon: 'list' }),
      // The cards that link the meeting: a sheet, because a long agenda would push them out
      // of sight (spec 000551).
      { id: 'todos', label: t('todos.meeting.sheet'), icon: 'link' },
      // The linked rows of the open item; above the phone width the edge tab opens them (spec 001800).
      ...when(this.phone() && !!this.top(), { id: 'links', label: t('todos.linked.top'), icon: 'link' }),
      ...when(m.canManage, { id: 'settings', label: t('meetings.settings.title'), icon: 'edit' }),
      ...when(!this.phone() || noDock, {
        id: 'attendance',
        label: t('meetings.page.recordAttendance'),
        icon: 'users',
      }),
      ...when(this.showVotes() && this.phone() && (noDock || !m.isProtokollant), {
        id: 'votes',
        label: t('meetings.vote.count'),
        icon: 'vote',
      }),
      ...when(this.phone() && keeper, {
        id: 'keeper',
        label: t(m.status === 'live' ? 'meetings.handover.title' : 'meetings.dock.pickProtokollant'),
        icon: m.status === 'live' ? 'swap' : 'clipcheck',
      }),
      ...when(!this.wide() && m.status !== 'closed' && m.canManage, {
        id: 'beamer',
        label: t('meetings.beamer.enter'),
        icon: 'monitor',
      }),
      ...when(this.phone() && m.publicJoin && m.status !== 'closed' && m.canManage, {
        id: 'qr',
        label: t('guests.qr.title'),
        icon: 'grid',
      }),
    ];
    const danger: readonly RowMenuItem[] = [
      ...when(this.phone() && this.mainAction() === 'close', {
        id: 'close',
        label: t('meetings.control.closeSession'),
        icon: 'square',
        danger: true,
        disabledReason: this.anyOpenVote() ? t('meetings.page.closeBlocked') : null,
      }),
      ...when(m.canDelete, {
        id: 'delete',
        label: t('meetings.delete.title'),
        icon: 'trash',
        danger: true,
      }),
    ];
    const p = this.protocol();
    // The items come from the page inputs, not from the child: the child gets its inputs only
    // after this menu is first read.
    const protocol =
      m.status === 'closed' && p ? protocolMenuItems(protocolActions(m, p, true), p, this.phone(), t) : [];
    return [
      ...(protocol.length ? [{ label: t('meetings.protocolMenu.caption'), items: protocol }] : []),
      { items: main },
      { items: danger },
    ];
  });

  /** The page shows no vote while `Abstimmungen` is off (spec 000758). */
  private readonly votingOn = inject(FeatureService).isOn('voting');
  /** The votes of the open item: the open one first, then the newest first. */
  protected readonly votes = computed<MeetingVote[]>(() => {
    const t = this.top();
    if (!t || !this.votingOn) return [];
    const own = this.meeting().votes.filter((v) => v.agendaItemId === t.id);
    const open = own.filter((v) => v.status === 'open');
    const rest = own.filter((v) => v.status !== 'open').reverse();
    return [...open, ...rest];
  });
  protected readonly openVote = computed(
    () => this.votes().find((v) => v.status === 'open') ?? null,
  );
  /**
   * An open vote on any item of the meeting. It blocks the close of the meeting, so the
   * close button is disabled and says why. It also blocks a second vote: the reconnect
   * state, the beamer and the dock follow only one open vote.
   */
  protected readonly anyOpenVote = computed(() =>
    this.meeting().votes.some((v) => v.status === 'open'),
  );

  /**
   * The votes of the open item that another vote continues: a next Wahlgang (§ 000971) or a
   * repeat that is not cancelled. Such a vote takes no further Wahlgang and no further repeat.
   */
  protected readonly continuedIds = computed(
    () =>
      new Set(
        this.votes()
          .filter((v) => v.status !== 'cancelled')
          .flatMap((v) => [v.parentVoteId, v.repeatOfId])
          .filter((id): id is string => !!id),
      ),
  );

  /** The closed votes of the open item whose repeat opened: their cards say "Wiederholt". */
  protected readonly repeatedIds = computed(
    () =>
      new Set(
        this.votes()
          .filter((v) => v.repeatOfId && (v.status === 'open' || v.status === 'closed'))
          .map((v) => v.repeatOfId as string),
      ),
  );
  /**
   * The closed votes of the open item that can be voted on again: no repeat and no next
   * Wahlgang of them is prepared, open or closed, and the item has no prepared or open vote.
   */
  protected readonly repeatableIds = computed(() => {
    const own = this.votes();
    if (own.some((v) => v.status === 'draft' || v.status === 'open')) return new Set<string>();
    const taken = this.continuedIds();
    return new Set(own.filter((v) => v.status === 'closed' && !taken.has(v.id)).map((v) => v.id));
  });

  /** The newest closed vote whose result is not in the text yet. */
  protected readonly pendingResult = computed<MeetingVote | null>(() => {
    if (this.openVote()) return null;
    const shown = this.inTextIds();
    return this.votes().find((v) => v.status === 'closed' && !shown.has(v.id)) ?? null;
  });

  /** The closed votes of the open item whose callout is in its text. */
  private readonly inTextIds = computed(() => {
    const t = this.top();
    if (!t) return new Set<string>();
    const own = this.meeting().votes.filter((v) => v.agendaItemId === t.id);
    return votesInText(t.body ?? '', own);
  });

  /**
   * "Beschlussfrage hinzufügen": an application item and the item of a
   * Haushaltsplan hold one vote, free text any number. A draft of a plan is on the agenda
   * for a reading and takes no vote.
   * A planned meeting prepares the vote as a draft; so does a live meeting while another
   * vote is open (the dialog then only prepares).
   */
  protected readonly canAddVote = computed(() => {
    const m = this.meeting();
    const t = this.top();
    if (!t || !m.canManageVotes || this.locked() || m.status === 'closed' || t.planReading) return false;
    return (
      !(t.applicationId || t.planVersionId) || this.votes().every((v) => v.status === 'cancelled')
    );
  });

  /** The add button of an application item: open the vote, or only prepare it. */
  protected readonly addVoteKey = computed<'meetings.vote.openFor' | 'meetings.vote.prepareTitle'>(() =>
    this.meeting().status === 'live' && !this.anyOpenVote()
      ? 'meetings.vote.openFor'
      : 'meetings.vote.prepareTitle',
  );

  /** The name of the add button in the head of the vote sheet (spec 001802). */
  protected readonly addVoteLabel = computed(() => {
    const t = this.top();
    return t?.applicationId || t?.planVersionId ? this.addVoteKey() : ('meetings.vote.addQuestion' as const);
  });

  /**
   * The vote sheet can open for every open item, also without a vote and in a closed meeting
   * with a final protocol: the sheet then shows its empty state (specs 001802, 001804).
   */
  protected readonly showVotes = computed(() => !!this.top() && this.votingOn);

  /**
   * The edge tab of the votes: above the phone width, for everybody but the minute-taker
   * (spec 001460); in a closed meeting for the minute-taker too (spec 001804).
   */
  protected readonly showVoteTab = computed(
    () =>
      !this.phone() &&
      this.showVotes() &&
      !this.votesOpen() &&
      (this.dockVotes() === null || this.meeting().status === 'closed'),
  );
  /** The edge tab of the linked rows: above the phone width, while an item is open (spec 001800). */
  protected readonly showLinkTab = computed(() => !this.phone() && !!this.top() && !this.linksOpen());
  /** The edge tab of the attendance sheet: above the phone width, beside the dock chip (spec 001801). */
  protected readonly showAttendanceTab = computed(() => !this.phone() && this.panel() !== 'attendance');

  /** The own ballot of the open vote, for the dock. */
  protected readonly myVote = computed<string | null>(() => {
    const v = this.openVote();
    if (!v) return null;
    const local = this.choices()[v.id];
    const choice = local ?? v.myBallot?.choice ?? null;
    if (choice) return voteOptionLabel(choice, (key) => this.i18n.translate(key));
    return v.myBallot?.cast ? this.i18n.translate('meetings.dock.voteCast') : null;
  });

  /** The result of a closed vote is in the text of the open item. */
  protected inText(vote: MeetingVote): boolean {
    return this.inTextIds().has(vote.id);
  }

  protected myChoice(voteId: Uuid): string | null {
    return this.choices()[voteId] ?? null;
  }

  /**
   * Move to the previous (-1) or the next (+1) agenda item. The step forward also ticks
   * the item that the room leaves ("Nächster TOP"); the step back ticks nothing.
   */
  step(delta: -1 | 1): void {
    const from = this.agenda()[this.topIndex()];
    if (!from) return;
    const next = this.agenda()[this.topIndex() + delta];
    if (!next) return;
    if (delta === 1) {
      this.open();
      this.nextTop.emit({ id: next.id, from: from.id });
    } else {
      this.jump(next.id);
    }
  }

  /**
   * Open an agenda item and, for the room lead, make it the item the room handles now.
   * A planned meeting has no "now": a pick there opens the item to prepare it.
   */
  jump(id: Uuid): void {
    this.open();
    this.selectTop.emit(id);
  }

  /** Close the panels for the sheet of the item that opens. */
  private open(): void {
    this.panel.set('none');
    this.agendaOpen.set(false);
  }

  /**
   * Append the result of a closed vote to the text of the open item.
   *
   * A phone keyboard often ends the text with a hard break, which Markdown keeps as a trailing
   * backslash. Left in place, it becomes an empty line before the block.
   */
  insertResult(vote: MeetingVote): void {
    const t = this.top();
    if (!t) return;
    const body = (t.body ?? '').replace(/[\s\\]+$/, '');
    const snippet = voteSnippet(vote);
    this.bodyChange.emit({ itemId: t.id, body: body ? `${body}\n\n${snippet}` : snippet });
    this.revision.update((r) => r + 1);
  }

  /** "Groß zeigen" in the attendance sheet: close the sheet, show the large code. */
  showQr(): void {
    this.panel.set('none');
    this.qrOpen.set(true);
  }

  protected onMenu(item: RowMenuItem): void {
    if (this.protocolBar()?.select(item.id)) return;
    switch (item.id as SessionAction) {
      case 'todos':
        this.todosOpen.set(true);
        break;
      case 'links':
        this.linksOpen.set(true);
        break;
      case 'open':
        this.startSession.emit();
        break;
      case 'settings':
        this.openSettings.emit();
        break;
      case 'attendance':
        this.panel.set('attendance');
        break;
      case 'keeper':
        this.panel.set('protokollant');
        break;
      case 'agenda':
        this.agendaOpen.set(true);
        break;
      case 'votes':
        this.votesOpen.set(true);
        break;
      case 'beamer':
        this.toggleBeamer.emit();
        break;
      case 'qr':
        this.qrOpen.set(true);
        break;
      case 'close':
        this.closeSession.emit();
        break;
      case 'delete':
        this.deleteMeeting.emit();
        break;
    }
  }

  /** "Di, 29.09.2026" in the language of the page. */
  private dateText(isoDate: string): string {
    return weekdayDate(isoDate, this.i18n.formatLocale()) || isoDate;
  }
}
