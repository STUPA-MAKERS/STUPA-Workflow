import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  NgZone,
  afterNextRender,
  computed,
  inject,
  input,
  model,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  AgendaItem,
  Attendance,
  HandoverMode,
  Meeting,
  MeetingVote,
  Protocol,
  Uuid,
} from '@core/api/models';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui/row-menu/row-menu.component';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { meetingStatus } from '@shared/status-kind.util';
import { type AgendaMove, AgendaPaneComponent } from '../agenda-pane/agenda-pane.component';
import type { AttendanceChange } from '../meeting-attendance-table.component';
import { PrepChecklistComponent } from '../prep-checklist/prep-checklist.component';
import { type DockPanel, SessionDockComponent } from '../session-dock/session-dock.component';
import { type SaveState, TopSheetComponent } from '../top-sheet/top-sheet.component';
import { VoteCardComponent } from '../vote-card/vote-card.component';
import { voteSnippet, voteSnippetHead } from '../meetings.util';
import { clockTime, voteOptionLabel } from '../meetings-display.util';

/** The ids of the session menu. */
type SessionAction = 'settings' | 'attendance' | 'beamer' | 'close' | 'finalize' | 'delete';

/**
 * The session page of the meeting lead and the minute-taker (`/meetings/:id`).
 *
 * The header carries the title, the status, "Gremium · date · seit HH:MM", the people
 * who have the meeting open, the beamer, the session menu and the one main action (open,
 * close, or finalize after the close). Below it the agenda pane, the sheet of the open
 * item and the cards of its votes; a planned meeting shows the preparation instead of the
 * sheet. The dock at the foot steps through the agenda and holds the attendance and the
 * minute-taker.
 *
 * Wide (>= 1200px): three columns. Below that the agenda moves into a sheet from the
 * start edge, and the vote cards go above the item. On a phone the agenda sheet, the
 * attendance and the minute-taker open as bottom sheets.
 */
@Component({
  selector: 'app-meeting-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    RowMenuComponent,
    SideSheetComponent,
    StatusTextComponent,
    AgendaPaneComponent,
    PrepChecklistComponent,
    SessionDockComponent,
    TopSheetComponent,
    VoteCardComponent,
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
  private readonly agendaPane = viewChild(AgendaPaneComponent);

  /** Three columns from 1200px; below that the agenda is a sheet. */
  protected readonly wide = mediaQuerySignal(MEDIA.wide);
  protected readonly phone = mediaQuerySignal(MEDIA.phone);
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
  readonly viewers = input.required<string[]>();
  readonly casting = input.required<Uuid | null>();
  readonly deletingVote = input.required<Uuid | null>();
  readonly finalizing = input.required<boolean>();
  /** Own choice per vote id, from this session. */
  readonly choices = input.required<Record<string, string>>();
  readonly savingAgenda = input.required<boolean>();
  readonly renamingTopId = input.required<Uuid | null>();
  readonly renameDraft = model<string>('');

  /** Leave the session page for the meeting list. */
  readonly back = output<void>();
  readonly selectTop = output<Uuid>();
  readonly bodyChange = output<{ itemId: Uuid; body: string }>();
  readonly castVote = output<{ voteId: Uuid; choice: string }>();
  readonly voteOpen = output<Uuid>();
  readonly voteClose = output<Uuid>();
  readonly voteCancel = output<Uuid>();
  readonly voteDelete = output<Uuid>();
  readonly voteDialog = output<AgendaItem>();
  readonly startSession = output<void>();
  readonly closeSession = output<void>();
  readonly finalize = output<void>();
  readonly openSettings = output<void>();
  readonly deleteMeeting = output<void>();
  readonly toggleBeamer = output<void>();
  readonly attendanceChange = output<AttendanceChange>();
  readonly attendanceReset = output<Attendance>();
  /** Open "TOP hinzufügen". */
  readonly addTop = output<void>();
  readonly removeFromAgenda = output<Uuid>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly setNonPublic = output<{ item: AgendaItem; nonPublic: boolean }>();
  readonly moveTop = output<AgendaMove>();
  readonly dragStart = output<number>();
  readonly dragOver = output<DragEvent>();
  readonly drop = output<number>();
  /** Name the minute-taker of a planned meeting. */
  readonly setProtokollant = output<Uuid>();
  /** Hand the minutes of a live meeting over, now or with the next item (Z3). */
  readonly handOver = output<{ principalId: Uuid; mode: HandoverMode }>();
  /** Discard the planned handover. */
  readonly cancelHandover = output<void>();

  /** The dock panel that is open: a popover above the dock, a bottom sheet on a phone. */
  readonly panel = signal<DockPanel>('none');
  /** The agenda sheet below the wide layout. */
  readonly agendaOpen = signal(false);
  /** The list of the people who have the meeting open. */
  protected readonly presenceOpen = signal(false);
  /** Raised by an insert from outside the editor, so the editor loads the new text. */
  protected readonly revision = signal(0);

  constructor() {
    const destroyRef = inject(DestroyRef);
    const zone = inject(NgZone);
    afterNextRender(() => {
      const el = this.dock().nativeElement;
      // The observer fires outside the zone, so the write runs inside it, or the page
      // keeps the old room below its content until the next event.
      const observer = new ResizeObserver(() =>
        zone.run(() => this.dockHeight.set(el.offsetHeight)),
      );
      observer.observe(el);
      destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  protected readonly status = computed(() => meetingStatus(this.meeting().status));
  protected readonly locked = computed(() => this.protocol()?.isLocked ?? false);
  protected readonly editable = computed(
    () => this.protocol() !== null && !this.locked() && this.canEdit(),
  );

  /** The planned meeting shows what the opening needs instead of the sheet. */
  protected readonly preparing = computed(() => {
    const m = this.meeting();
    return m.status === 'planned' && (m.canControl || m.canManage);
  });

  /** "Studierendenparlament · Di, 29.09.2026 · seit 18:04". */
  protected readonly subLine = computed(() => {
    const m = this.meeting();
    const locale = this.i18n.locale();
    const parts: string[] = [];
    if (m.gremiumName) parts.push(m.gremiumName);
    if (m.date) parts.push(this.dateText(m.date));
    const started = clockTime(m.startedAt, locale);
    if (m.status === 'live' && started) {
      parts.push(this.i18n.translate('meetings.page.since', { time: started }));
    } else if (m.status === 'closed' && started) {
      const closed = clockTime(m.closedAt, locale);
      parts.push(closed ? `${started}–${closed}` : started);
    } else if (m.startTime) {
      parts.push(m.startTime.slice(0, 5));
    }
    return parts.join(' · ');
  });

  /** Presence is shown to the people who run the meeting, while it is live. */
  protected readonly showPresence = computed(() => {
    const m = this.meeting();
    return m.status === 'live' && m.canWrite;
  });
  protected readonly presenceTitle = computed(() =>
    this.viewers().length
      ? this.i18n.translate('meetings.page.viewers', { names: this.viewers().join(', ') })
      : this.i18n.translate('meetings.viewers.empty'),
  );

  /**
   * The main action of the header: open a planned meeting, close a live one, or finalize
   * the protocol of a closed one (O13). `null` when the viewer has none.
   */
  protected readonly mainAction = computed<'open' | 'close' | 'finalize' | null>(() => {
    const m = this.meeting();
    const p = this.protocol();
    if (m.status === 'planned' && m.canControl) return 'open';
    if (m.status === 'live' && m.canControl) return 'close';
    if (m.status === 'closed' && m.canFinalize && p && !p.isFinal && p.status !== 'rendering') {
      return 'finalize';
    }
    return null;
  });

  /**
   * The session menu: settings, attendance and delete. Below the wide layout the beamer
   * goes in here too; on a phone the header keeps only the title, so the close and the
   * finalize move in as well (the opening is on the preparation page).
   */
  protected readonly menu = computed<RowMenuSection[]>(() => {
    const m = this.meeting();
    const t = (key: Parameters<I18nService['translate']>[0]): string => this.i18n.translate(key);
    const main: RowMenuItem[] = [];
    if (m.canManage) main.push({ id: 'settings', label: t('meetings.settings.title'), icon: 'edit' });
    main.push({ id: 'attendance', label: t('meetings.page.recordAttendance'), icon: 'users' });
    if (!this.wide()) main.push({ id: 'beamer', label: t('meetings.beamer.enter'), icon: 'monitor' });
    if (this.phone() && this.mainAction() === 'finalize') {
      main.push({ id: 'finalize', label: t('meetings.protocol.finalize'), icon: 'send' });
    }
    const sections: RowMenuSection[] = [{ items: main }];
    const danger: RowMenuItem[] = [];
    if (this.phone() && this.mainAction() === 'close') {
      danger.push({
        id: 'close',
        label: t('meetings.control.closeSession'),
        icon: 'stop',
        danger: true,
        disabledReason: this.anyOpenVote() ? t('meetings.page.closeBlocked') : null,
      });
    }
    if (m.canManage) {
      danger.push({ id: 'delete', label: t('meetings.delete.title'), icon: 'delete', danger: true });
    }
    sections.push({ items: danger });
    return sections;
  });

  /** The votes of the open item: the open one first, then the newest first. */
  protected readonly votes = computed<MeetingVote[]>(() => {
    const t = this.top();
    if (!t) return [];
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
   * close button is disabled and says why.
   */
  protected readonly anyOpenVote = computed(() =>
    this.meeting().votes.some((v) => v.status === 'open'),
  );

  /** The newest closed vote whose result is not in the text yet. */
  protected readonly pendingResult = computed<MeetingVote | null>(() => {
    if (this.openVote()) return null;
    const body = this.top()?.body ?? '';
    return (
      this.votes().find((v) => v.status === 'closed' && !body.includes(voteSnippetHead(v))) ?? null
    );
  });

  /** "Beschlussfrage hinzufügen": an application item holds one vote, free text any number. */
  protected readonly canAddVote = computed(() => {
    const m = this.meeting();
    const t = this.top();
    if (!t || !m.canManageVotes || this.locked() || m.status !== 'live') return false;
    if (this.openVote()) return false;
    return !t.applicationId || this.votes().length === 0;
  });

  /** The column of the vote cards shows when there is a vote or one can be added. */
  protected readonly showVotes = computed(
    () => !this.preparing() && (this.votes().length > 0 || this.canAddVote()),
  );

  /** The own ballot of the open vote, for the dock. */
  protected readonly myVote = computed<string | null>(() => {
    const v = this.openVote();
    if (!v) return null;
    const local = this.choices()[v.id];
    const choice = local ?? v.myBallot?.choice ?? null;
    if (choice) return voteOptionLabel(choice, (key) => this.i18n.translate(key));
    return v.myBallot?.cast ? this.i18n.translate('meetings.dock.voteCast') : null;
  });

  protected readonly wordCount = computed(() => {
    const body = this.top()?.body?.trim() ?? '';
    return body ? body.split(/\s+/).length : 0;
  });

  protected myChoice(voteId: Uuid): string | null {
    return this.choices()[voteId] ?? null;
  }

  /** Move to the previous (-1) or the next (+1) agenda item. */
  step(delta: -1 | 1): void {
    if (this.topIndex() < 0) return;
    const next = this.agenda()[this.topIndex() + delta];
    if (next) this.jump(next.id);
  }

  jump(id: Uuid): void {
    this.panel.set('none');
    this.agendaOpen.set(false);
    this.selectTop.emit(id);
  }

  /** Append the result of a closed vote to the text of the open item. */
  insertResult(vote: MeetingVote): void {
    const t = this.top();
    if (!t) return;
    // A phone keyboard often ends the text with a hard break, which Markdown keeps as a
    // trailing backslash. Left in place it becomes an empty line before the block.
    const body = (t.body ?? '').replace(/[\s\\]+$/, '');
    const snippet = voteSnippet(vote);
    this.bodyChange.emit({ itemId: t.id, body: body ? `${body}\n\n${snippet}` : snippet });
    this.revision.update((r) => r + 1);
  }

  /** "Tagesordnung bearbeiten": the pane on a wide screen, else the agenda sheet. */
  editAgenda(): void {
    if (this.wide()) this.agendaPane()?.focus();
    else this.agendaOpen.set(true);
  }

  protected onMenu(item: RowMenuItem): void {
    switch (item.id as SessionAction) {
      case 'settings':
        this.openSettings.emit();
        break;
      case 'attendance':
        this.panel.set('attendance');
        break;
      case 'beamer':
        this.toggleBeamer.emit();
        break;
      case 'close':
        this.closeSession.emit();
        break;
      case 'finalize':
        this.finalize.emit();
        break;
      case 'delete':
        this.deleteMeeting.emit();
        break;
    }
  }

  /** "Di, 29.09.2026" in the language of the page. */
  private dateText(isoDate: string): string {
    const date = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(date.getTime())) return isoDate;
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      weekday: 'short',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(date);
  }
}
