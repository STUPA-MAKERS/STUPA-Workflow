import {
  DestroyRef,
  Injectable,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import type { Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  Meeting,
  MeetingPatchBody,
  MeetingVote,
  Protocol,
  SelfAttendanceStatus,
  Uuid,
} from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { BodyDraftMsg, ServerMessage } from '@core/ws/ws-messages';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingAgendaService } from './meeting-agenda.service';
import { MeetingGuestsService } from './meeting-guests.service';
import { openWindowState } from './open-window.util';
import {
  assembleProtocolMarkdown,
  canReportOwn,
  liveOpenedVote,
} from './meetings-display.util';
import { problemCode, problemDetail } from '@core/api/problem';

/** The shortest time between two live drafts of the protokollant. */
const DRAFT_INTERVAL_MS = 300;

/**
 * State and actions of the loaded meeting (detail route): meeting control,
 * live votes over WebSocket, protocol lifecycle and attendance.
 * RBAC here gates the UI only. The server authorizes every action.
 * Provided by MeetingsComponent.
 */
@Injectable()
export class MeetingSessionService implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly ws = inject(WsService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly useMock = inject(USE_MOCK_API);
  private readonly agendaSvc = inject(MeetingAgendaService);
  /** The join requests and the guests (#17); provided beside this service. */
  private readonly guests = inject(MeetingGuestsService, { optional: true });

  constructor() {
    effect(() => {
      const m = this.meeting();
      untracked(() => this.guests?.sync(m));
    });
  }

  readonly loading = signal(false);
  readonly error = signal(false);
  readonly meeting = signal<Meeting | null>(null);
  readonly protocol = signal<Protocol | null>(null);

  readonly attendance = signal<Attendance[]>([]);
  /** Live viewers of the meeting page (WS `viewers`). */
  readonly viewers = signal<string[]>([]);
  readonly savingAttendance = signal(false);
  /**
   * O23: the member whose "present" the server refused with 409 `delegation_active`. The
   * attendance sheet marks the row and offers the revoke of the delegation.
   */
  readonly attendanceConflict = signal<Uuid | null>(null);

  /** Date/time editor of an already created, planned meeting. */
  readonly planDate = signal('');
  readonly planTime = signal('');
  readonly savingDate = signal(false);

  readonly finalizing = signal(false);
  /** "Sitzung schon eröffnen?" is open: the open is early and waits for the confirmation. */
  readonly earlyOpenAsk = signal(false);
  /** Poll fallback while the worker renders the protocol. */
  private renderPollTimer: ReturnType<typeof setTimeout> | null = null;

  /** The vote with a cast in flight, and the vote with a delete in flight. */
  readonly casting = signal<Uuid | null>(null);
  readonly deletingVote = signal<Uuid | null>(null);
  /** Own choice per vote (local, highlights the picked option). */
  readonly myChoices = signal<Record<string, string>>({});

  private channel: MeetingChannel | null = null;
  /** Counts the vote events of the live channel, so a slower read cannot undo one. */
  private voteEvents = 0;
  /**
   * The sequence number of the next live draft. It starts at the clock time of the
   * editor session and rises per frame, so the drafts of a reloaded page stay above the
   * drafts of the page before it.
   */
  private draftSeq = Date.now();
  /** The time of the last sent draft, and the draft that waits for the throttle. */
  private draftSentAt = 0;
  private draftTimer: ReturnType<typeof setTimeout> | null = null;
  private draftPending: { itemId: Uuid; body: string } | null = null;
  /** The highest draft sequence number seen per agenda item (viewer side). */
  private readonly draftSeen = new Map<Uuid, number>();

  // Permission flags, per meeting where loaded. The backend checks them per Gremium.
  /** The admin manages the meetings of every Gremium. Everybody else manages per
   *  Gremium through `session.manage`, which the server reports as `canManage`. */
  readonly canManageAny = computed(() => this.auth.isAdmin());
  readonly canManage = computed(() => this.meeting()?.canManage ?? this.canManageAny());
  readonly canWrite = computed(() => this.meeting()?.canWrite ?? false);
  readonly canManageVotes = computed(() => this.meeting()?.canManageVotes ?? false);
  readonly canVote = computed(() => this.meeting()?.canVote ?? false);
  /** Global READ permission. It only adds rights: it shows every meeting read-only. */
  readonly canViewAll = computed(() => this.auth.can('meeting.view_all'));
  /** The server resolves this. The FE only knows `principal.sub`, not the principal id. */
  readonly isProtokollant = computed(() => this.meeting()?.isProtokollant ?? false);
  /**
   * Live follow view (read the protocol and cast on open votes) instead of the
   * edit/manager view. Only the rights the server sends decide this. A named
   * protokollant does NOT push everybody else into the follow view: the
   * exclusivity covers the protocol text alone (see `canEditProtocol`), never
   * the meeting control, the agenda or the votes. Coupling the two once stranded
   * a meeting whose protokollant was away, because the switch that reassigns
   * them sits in the settings dialog behind the hidden toolbar.
   */
  readonly isFollower = computed(() => {
    const m = this.meeting();
    if (!m) return false;
    if (this.canViewAll()) return false;
    return !m.canWrite && !m.canManage;
  });
  /**
   * Write the minutes. Two people must not type into one protocol, so in a live
   * meeting with a named protokollant only that person edits it. Everybody else with
   * `canWrite` reads the pane. The server grants `canWrite` to the protokollant,
   * the manager and any `protocol.write` role alike, so this last step is the
   * frontend's alone.
   *
   * Before the start and after the close there is no live keeper to protect. Every
   * writer prepares the text of a planned meeting, and every writer edits the draft of
   * a closed one (O22): the session lead, the finalizer and an earlier keeper, not only
   * the last one. A final protocol stays locked through `Protocol.isLocked`.
   */
  readonly canEditProtocol = computed(() => {
    const m = this.meeting();
    if (!m?.canWrite) return false;
    if (m.status !== 'live') return true;
    return !m.protokollantId || this.isProtokollant();
  });

  /** Votes of one TOP, grouped by agendaItemId. */
  votesForTop(topId: Uuid): MeetingVote[] {
    return (this.meeting()?.votes ?? []).filter((v) => v.agendaItemId === topId);
  }
  /** Meeting votes without a TOP binding. The control card lists them. */
  readonly looseVotes = computed<MeetingVote[]>(() =>
    (this.meeting()?.votes ?? []).filter((v) => !v.agendaItemId),
  );

  ngOnDestroy(): void {
    this.clearDraft();
    this.channel?.close();
    if (this.renderPollTimer !== null) clearTimeout(this.renderPollTimer);
  }

  loadMeeting(id: Uuid): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.getMeeting(id).subscribe({
      next: (m) => {
        this.loading.set(false);
        this.adoptMeeting(m);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
      },
    });
  }

  /** An existing protocol is read with GET, which keeps the write rate limit intact. */
  private adoptMeeting(m: Meeting): void {
    this.meeting.set(m);
    this.attendanceConflict.set(null);
    this.planDate.set(m.date ?? '');
    this.planTime.set(m.startTime ?? '');
    this.connectLive(m.id);
    if (m.protocolId && (this.canWrite() || this.canViewAll())) this.refreshProtocol();
    this.loadAttendance(m.id);
    this.agendaSvc.load(m.id, m.currentAgendaItemId);
  }

  /**
   * Tell the room which agenda item runs now.
   *
   * Only the protokollant moves the room: the open item follows the minutes. The
   * session lead and everybody else keep a local selection, so a look at another
   * item does not move the beamer and the followers. Only a live meeting
   * has a "now": the server refuses it for a closed meeting, and a planned meeting
   * must not start with an item that a click during the preparation set.
   *
   * "Nächster TOP" names the item that the room leaves (`completeItemId`): the server
   * ticks it in the same request. A click on an item ticks nothing.
   */
  setCurrentTop(itemId: Uuid, completeItemId: Uuid | null = null): void {
    const m = this.meeting();
    if (!m || !m.isProtokollant || m.status !== 'live' || m.currentAgendaItemId === itemId) return;
    const body: MeetingPatchBody = completeItemId
      ? { currentAgendaItemId: itemId, completeAgendaItemId: completeItemId }
      : { currentAgendaItemId: itemId };
    this.api.patchMeeting(m.id, body).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        if (completeItemId) this.agendaSvc.load(m.id, updated.currentAgendaItemId);
      },
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /**
   * Start a planned meeting (planned → live). The server creates the protocol on
   * the start. Only a planned meeting starts, and it needs a minute-taker: the page
   * says so at once instead of showing the server 409 after the click.
   *
   * The open window: before `opensAt` the page refuses at once (the button is off
   * anyway) and reads the meeting again, because the window may have moved. The
   * server 409 `meeting_too_early` (the clocks differ) does the same. Before `confirmUntil` the open is early: the first call opens "Sitzung
   * schon eröffnen?" (`earlyOpenAsk`), and the dialog calls again with
   * `confirmEarly`. When the server still finds the open early (the clocks differ),
   * its 409 `early_open_unconfirmed` opens the dialog too.
   *
   * The close is a dialog of its own (`CloseMeetingDialogComponent`), and a planned
   * meeting that does not take place is deleted, not closed (O13).
   *
   * The window may have moved (settings, a date change in another tab), so the start reads it
   * again.
   */
  startMeeting(confirmEarly = false): void {
    const m = this.meeting();
    this.earlyOpenAsk.set(false);
    if (!m || m.status !== 'planned') return;
    if (!m.protokollantId) {
      this.toast.error(this.i18n.translate('meetings.toast.protokollantRequired'));
      return;
    }
    const phase = openWindowState(m, Date.now());
    if (phase === 'tooEarly') {
      this.tooEarly();
      return;
    }
    if (phase === 'early' && !confirmEarly) {
      this.earlyOpenAsk.set(true);
      return;
    }
    const body: MeetingPatchBody = confirmEarly ? { status: 'live', confirmEarly } : { status: 'live' };
    this.api.patchMeeting(m.id, body).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        if (updated.status === 'live' && updated.protocolId && this.canWrite()) {
          this.refreshProtocol();
        }
      },
      error: (err: unknown) => {
        const code = problemCode(err);
        if (code === 'early_open_unconfirmed') {
          this.earlyOpenAsk.set(true);
          return;
        }
        if (code === 'meeting_too_early') {
          this.tooEarly();
          return;
        }
        this.statusChangeFailed(err);
      },
    });
  }

  /**
   * Show why the server refused a status change, then reload the meeting. The
   * meeting may have changed in another tab.
   */
  private statusChangeFailed(err: unknown): void {
    const detail = problemDetail(err);
    const base = this.i18n.translate('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
    const m = this.meeting();
    if (m) {
      this.api.getMeeting(m.id, { quiet: true }).subscribe({
        next: (updated) => this.meeting.set(updated),
        error: () => {},
      });
    }
  }

  /** The open is too early: say so and read the meeting again for a fresh window. */
  private tooEarly(): void {
    this.toast.error(this.i18n.translate('meetings.toast.tooEarly'));
    this.reloadMeeting();
  }

  /** Read the meeting again (quiet): the lot of an election or its runoff (F2). */
  reloadMeeting(): void {
    const m = this.meeting();
    if (!m) return;
    this.api.getMeeting(m.id, { quiet: true }).subscribe({
      next: (updated) => {
        if (this.meeting()?.id === updated.id) this.meeting.set(updated);
      },
      error: () => {},
    });
  }

  savePlannedDate(): void {
    const m = this.meeting();
    const date = this.planDate().trim();
    if (!m || !date || this.savingDate()) return;
    this.savingDate.set(true);
    this.api.patchMeeting(m.id, { date, startTime: this.planTime().trim() || null }).subscribe({
      next: (updated) => {
        this.savingDate.set(false);
        this.meeting.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.dateSaved'));
      },
      error: () => {
        this.savingDate.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  setActive(applicationId: Uuid): void {
    const m = this.meeting();
    if (!m) return;
    this.api.patchMeeting(m.id, { activeApplicationId: applicationId }).subscribe({
      next: (updated) => this.meeting.set(updated),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /**
   * Open a prepared vote of the meeting. The meeting route checks the draft again and
   * counts the voters from the current roster, so the answer carries the new meeting.
   */
  openVote(voteId: Uuid): void {
    const m = this.meeting();
    if (!m) return;
    this.api.openPreparedMeetingVote(m.id, voteId).subscribe({
      next: (updated) => {
        if (this.meeting()?.id === updated.id) this.meeting.set(updated);
      },
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Close a vote. The close always ends the vote. When the pass or fail
   *  transition of the application is blocked (`branchFired: false`), a warning
   *  tells the manager to move the application by hand.
   *
   * A generic motion has no application and fires no branch on purpose.
   */
  closeVote(voteId: Uuid): void {
    this.api.closeVote(voteId).subscribe({
      next: (closed) => {
        this.patchVote(voteId, { status: 'closed', closedAt: nowIso() });
        if (closed.applicationId && !closed.branchFired) {
          this.toast.show(this.i18n.translate('meetings.toast.voteBranchBlocked'), 'warning', 10000);
        }
      },
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Cancel a vote: open → cancelled, with no result and no branch. This is the
   *  way out when the quorum is not reached, because a close is blocked then. */
  cancelVote(voteId: Uuid): void {
    this.api.cancelVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'cancelled', closedAt: nowIso() }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Show the server reason (for example 409) and reload the meeting. The vote
   *  may have changed on the server, for example to cancelled. */
  private voteActionFailed(err: unknown): void {
    const detail = problemDetail(err);
    const base = this.i18n.translate('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
    const m = this.meeting();
    if (m) {
      this.api.getMeeting(m.id, { quiet: true }).subscribe({
        next: (updated) => this.meeting.set(updated),
        error: () => {},
      });
    }
  }

  /** Cast a ballot (protokollant/member with `vote.cast`). */
  cast(voteId: Uuid, choice: string): void {
    if (this.casting()) return;
    this.casting.set(voteId);
    this.api.castBallot(voteId, choice).subscribe({
      next: () => {
        this.casting.set(null);
        this.myChoices.update((m) => ({ ...m, [voteId]: choice }));
        this.toast.success(this.i18n.translate('meetings.toast.voteCast'));
      },
      error: (err: unknown) => {
        this.casting.set(null);
        this.voteActionFailed(err);
      },
    });
  }

  /** Delete a vote question and its ballots. Vote managers only. */
  deleteVote(voteId: Uuid): void {
    const m = this.meeting();
    if (!m || this.deletingVote()) return;
    this.deletingVote.set(voteId);
    this.api.deleteMeetingVote(m.id, voteId).subscribe({
      next: (updated) => {
        this.deletingVote.set(null);
        this.meeting.set(updated);
        this.toast.success(this.i18n.translate('meetings.toast.voteDeleted'));
      },
      error: (err: unknown) => {
        this.deletingVote.set(null);
        this.voteActionFailed(err);
      },
    });
  }

  /** An application TOP holds exactly one vote. A freetext TOP holds any number. */
  canAddVote(item: AgendaItem): boolean {
    return !item.applicationId || this.votesForTop(item.id).length === 0;
  }

  /** Re-read an existing protocol with GET, which keeps the write rate limit intact. */
  refreshProtocol(): void {
    const m = this.meeting();
    if (!m) return;
    this.api.getProtocol(m.id, { quiet: true }).subscribe({
      next: (proto) => {
        this.protocol.set(proto);
        this.watchRendering(proto);
      },
      error: () => {},
    });
  }

  /** Apply the status change after a background render and show the toast.
   *  `rendering → draft` means the worker gave up and rolled back. */
  private applyProtocolUpdate(updated: Protocol): void {
    const prev = this.protocol();
    this.protocol.set(updated);
    if (prev?.status === 'rendering') {
      if (updated.isFinal) {
        this.toast.success(this.i18n.translate('meetings.toast.finalized'));
      } else if (updated.status === 'draft') {
        this.toast.error(this.i18n.translate('meetings.toast.finalizeFailed'));
      }
    }
    this.watchRendering(updated);
  }

  /** While the status is `rendering`, poll the protocol. This is the fallback if
   *  the `meeting_state` broadcast of the worker is lost. GET keeps the write
   *  rate limit intact. */
  private watchRendering(proto: Protocol): void {
    if (this.renderPollTimer !== null) clearTimeout(this.renderPollTimer);
    if (proto.status !== 'rendering' || (!this.canWrite() && !this.canViewAll())) return;
    this.renderPollTimer = setTimeout(() => {
      this.renderPollTimer = null;
      const m = this.meeting();
      if (!m) return;
      this.api.getProtocol(m.id, { quiet: true }).subscribe({
        next: (updated) => this.applyProtocolUpdate(updated),
        error: () => this.watchRendering(proto),
      });
    }, 4000);
  }

  /**
   * Finalize the protocol. `publicWithheld` keeps the protocol of a public gremium off
   * the public protocol page (the finalize dialog asks for it).
   *
   * `isLocked` also covers `rendering`, so there is no second start and no 409 on PATCH. The
   * protocol is finalized only after the close, as a step of its own. The text typed within the
   * last autosave delay is sent first, because the server renders the PDF from the item texts it
   * holds.
   */
  finalize(opts: { publicWithheld?: boolean } = {}): void {
    const proto = this.protocol();
    if (!proto || proto.isLocked || this.finalizing()) return;
    if (this.meeting()?.status !== 'closed') return;
    const meetingId = this.meeting()?.id;
    if (!meetingId) return;
    this.finalizing.set(true);
    this.agendaSvc.persistBody(meetingId).subscribe((held) => {
      if (!held) {
        this.finalizing.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.saveFailed'));
        return;
      }
      this.api
        .updateProtocol(proto.id, assembleProtocolMarkdown(this.agendaSvc.agenda()))
        .subscribe({
          next: (saved) => {
            this.protocol.set(saved);
            this.doFinalize(saved.id, opts);
          },
          error: () => {
            this.finalizing.set(false);
            this.toast.error(this.i18n.translate('meetings.toast.saveFailed'));
          },
        });
    });
  }

  /** A change of the publication of a final protocol runs. */
  readonly publicationSaving = signal(false);

  /**
   * Hold the protocol back from the public protocol page, or publish it again. The
   * server checks the right to finalize in the gremium.
   */
  setPublicWithheld(withheld: boolean): void {
    const proto = this.protocol();
    if (!proto || this.publicationSaving()) return;
    this.publicationSaving.set(true);
    this.api.setProtocolWithheld(proto.id, withheld).subscribe({
      next: (updated) => {
        this.publicationSaving.set(false);
        this.protocol.set(updated);
        this.toast.success(
          this.i18n.translate(
            withheld ? 'meetings.toast.protocolWithheld' : 'meetings.toast.protocolPublished',
          ),
        );
      },
      error: (err: unknown) => {
        this.publicationSaving.set(false);
        const detail = problemDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
      },
    });
  }

  private doFinalize(protocolId: Uuid, opts: { publicWithheld?: boolean } = {}): void {
    this.api.finalizeProtocol(protocolId, opts).subscribe({
      next: (updated) => {
        this.finalizing.set(false);
        this.protocol.set(updated);
        if (updated.isFinal) {
          this.toast.success(this.i18n.translate('meetings.toast.finalized'));
        } else {
          this.toast.success(this.i18n.translate('meetings.toast.renderQueued'));
          this.watchRendering(updated);
        }
      },
      error: (err: unknown) => {
        this.finalizing.set(false);
        const detail = problemDetail(err);
        this.toast.error(
          detail
            ? `${this.i18n.translate('meetings.toast.finalizeFailed')}: ${detail}`
            : this.i18n.translate('meetings.toast.finalizeFailed'),
        );
      },
    });
  }

  private loadAttendance(meetingId: Uuid): void {
    this.api.listAttendance(meetingId).subscribe({
      next: (rows) => this.attendance.set(rows),
      error: () => this.attendance.set([]),
    });
  }

  /**
   * Change an attendance record. The meeting lead (`canControl`) sets any status of any
   * member through the lead endpoint. A member reports only the own record, only as
   * present or excused (Z2), and only while the lead did not set it (O15). `note` is
   * the reason of an excuse: leave it out to keep the stored reason.
   */
  setAttendance(member: Attendance, status: AttendanceStatus, note?: string | null): void {
    const m = this.meeting();
    if (!m || this.savingAttendance()) return;
    if (member.status === status && (note === undefined || note === member.note)) return;
    const asLead = m.canControl;
    if (!asLead && !canReportOwn(member, status)) return;
    this.savingAttendance.set(true);
    const req = asLead
      ? this.api.setMemberAttendance(m.id, member.principalId, status, note)
      : this.api.setOwnAttendance(m.id, status as SelfAttendanceStatus, note);
    this.saveAttendance(m.id, member.principalId, req, asLead);
  }

  /** O23: the delegation of the member was revoked, so the refusal no longer applies. */
  clearAttendanceConflict(principalId: Uuid): void {
    if (this.attendanceConflict() === principalId) this.attendanceConflict.set(null);
  }

  /** Reset a member to "open" (meeting lead only). The member can then report again. */
  resetAttendance(member: Attendance): void {
    const m = this.meeting();
    if (!m || !m.canControl || this.savingAttendance() || member.status === null) return;
    this.savingAttendance.set(true);
    this.saveAttendance(
      m.id,
      member.principalId,
      this.api.resetMemberAttendance(m.id, member.principalId),
    );
  }

  private saveAttendance(
    meetingId: Uuid,
    principalId: Uuid,
    req: Observable<Attendance[]>,
    asLead = true,
  ): void {
    req.subscribe({
      next: (rows) => {
        this.savingAttendance.set(false);
        this.attendance.set(rows);
        if (this.attendanceConflict() === principalId) this.attendanceConflict.set(null);
      },
      error: (err: unknown) => {
        this.savingAttendance.set(false);
        this.attendanceFailed(meetingId, principalId, err, asLead);
      },
    });
  }

  /**
   * Explain a refused attendance change. O23: a member with a delegation cannot be set or
   * report present; for the lead the attendance sheet marks the row and offers the
   * revoke. O15: the lead set the record of the member. Both reload the roster, because
   * it changed in another tab or by the lead.
   */
  private attendanceFailed(
    meetingId: Uuid,
    principalId: Uuid,
    err: unknown,
    asLead: boolean,
  ): void {
    const code = problemCode(err);
    if (code === 'delegation_active') {
      if (asLead) {
        this.attendanceConflict.set(principalId);
      } else {
        this.toast.error(this.i18n.translate('meetings.toast.ownDelegationActive'));
      }
    } else if (code === 'attendance_set_by_lead') {
      this.toast.error(this.i18n.translate('meetings.toast.attendanceSetByLead'));
    } else {
      const detail = problemDetail(err);
      const base = this.i18n.translate('meetings.toast.actionFailed');
      this.toast.error(detail ? `${base}: ${detail}` : base);
      return;
    }
    this.loadAttendance(meetingId);
  }

  /**
   * Send the text of the open item to the viewers while the protokollant types.
   *
   * Only the protokollant of a live meeting sends. At most one frame goes out per
   * `DRAFT_INTERVAL_MS`: a change inside the interval waits, and the last text always
   * goes out at the end of the interval. The autosave stays the only save; the server
   * passes the draft on without a write.
   *
   * A wait for another item goes out first, so the last text of each item goes out.
   */
  sendBodyDraft(itemId: Uuid, body: string): void {
    const m = this.meeting();
    if (!m || m.status !== 'live' || !m.isProtokollant || !this.channel) return;
    if (this.draftPending && this.draftPending.itemId !== itemId) this.flushDraft();
    this.draftPending = { itemId, body };
    if (this.draftTimer !== null) return;
    const wait = this.draftSentAt + DRAFT_INTERVAL_MS - Date.now();
    if (wait <= 0) {
      this.flushDraft();
      return;
    }
    this.draftTimer = setTimeout(() => this.flushDraft(), wait);
  }

  /** Send the waiting draft now. */
  private flushDraft(): void {
    if (this.draftTimer !== null) clearTimeout(this.draftTimer);
    this.draftTimer = null;
    const draft = this.draftPending;
    this.draftPending = null;
    if (!draft) return;
    this.draftSentAt = Date.now();
    this.channel?.send({
      type: 'body_draft',
      agendaItemId: draft.itemId,
      body: draft.body,
      seq: this.draftSeq++,
    });
  }

  /** Drop the waiting draft, for example when the channel goes away. */
  private clearDraft(): void {
    if (this.draftTimer !== null) clearTimeout(this.draftTimer);
    this.draftTimer = null;
    this.draftPending = null;
  }

  /**
   * Show a live draft of the protokollant (viewer side).
   *
   * The own client of the protokollant and an editable editor never take a draft. A
   * frame with a lower sequence number than the last one of its item is old and goes
   * away.
   */
  private applyBodyDraft(m: Meeting, msg: BodyDraftMsg): void {
    if (m.isProtokollant || this.canEditProtocol()) return;
    const last = this.draftSeen.get(msg.agendaItemId);
    if (last !== undefined && msg.seq < last) return;
    this.draftSeen.set(msg.agendaItemId, msg.seq);
    this.agendaSvc.applyDraft(msg.agendaItemId, msg.body);
  }

  /** Mock mode has no WS server, so the live channel is skipped. */
  private connectLive(meetingId: Uuid): void {
    this.viewers.set([]);
    this.clearDraft();
    this.draftSeen.clear();
    if (this.useMock) return;
    this.channel?.close();
    this.channel = this.ws.connectMeeting(meetingId);
    this.channel.messages$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => this.onLive(msg));
  }

  /**
   * TOP bodies can change without a vote, so a live event reloads the agenda. The event carries no
   * rights, so a handover reads the meeting again. Reads after a live event use GET, so broadcast
   * bursts do not burn the write rate limit.
   */
  private onLive(msg: ServerMessage): void {
    const m = this.meeting();
    if (!m) return;
    switch (msg.type) {
      case 'meeting_state': {
        const currentAgendaItemId =
          msg.currentAgendaItemId === undefined ? m.currentAgendaItemId : msg.currentAgendaItemId;
        this.meeting.set({
          ...m,
          status: (msg.status as Meeting['status']) ?? m.status,
          activeApplicationId: msg.activeApplicationId,
          currentAgendaItemId,
        });
        this.draftSeen.clear();
        this.agendaSvc.load(m.id, currentAgendaItemId);
        if (currentAgendaItemId && currentAgendaItemId !== m.currentAgendaItemId && !m.isProtokollant) {
          this.agendaSvc.selectTop(m.id, currentAgendaItemId);
        }
        this.reloadAfterState(m.id);
        if (
          (this.canWrite() || this.canViewAll()) &&
          this.protocol() &&
          !this.protocol()!.isFinal
        ) {
          this.api.getProtocol(m.id, { quiet: true }).subscribe({
            next: (proto) => this.applyProtocolUpdate(proto),
            error: () => {},
          });
        }
        break;
      }
      case 'vote_opened': {
        this.voteEvents++;
        const known = m.votes.find((v) => v.id === msg.voteId);
        if (known) {
          this.patchVote(msg.voteId, {
            status: 'open',
            closesAt: msg.closesAt,
            openedAt: known.openedAt ?? nowIso(),
            secret: msg.secret ?? known.secret,
            ...(msg.kind === 'election'
              ? { kind: msg.kind, election: msg.election ?? known.election, round: msg.round ?? 1 }
              : {}),
            ...(msg.kind === 'poll' ? { kind: msg.kind, poll: msg.poll ?? known.poll } : {}),
          });
        } else {
          this.meeting.set({ ...m, votes: [...m.votes, liveOpenedVote(msg)] });
        }
        break;
      }
      case 'vote_tally':
        this.voteEvents++;
        this.patchVote(msg.voteId, {
          counts: msg.counts,
          leading: msg.leading,
          voted: msg.cast ?? 0,
          present: msg.present ?? 0,
          revealed: msg.revealed ?? true,
          ...(msg.presentMembers !== undefined ? { presentMembers: msg.presentMembers } : {}),
          ...(msg.presentGuests !== undefined ? { presentGuests: msg.presentGuests } : {}),
        });
        break;
      case 'guest_requested':
      case 'guest_updated':
        this.guests?.apply(msg.guest);
        break;
      case 'guest_counts':
        this.meeting.set({
          ...m,
          publicJoin: msg.publicJoin ?? m.publicJoin,
          guestsMode: msg.guestsMode ?? m.guestsMode,
          joinCode: msg.joinCode !== undefined ? msg.joinCode : m.joinCode,
          admittedGuests: msg.admittedGuests,
          pendingGuests: msg.pendingGuests ?? m.pendingGuests,
        });
        break;
      case 'vote_closed':
        this.voteEvents++;
        this.patchVote(msg.voteId, {
          status: 'closed',
          result: msg.result,
          counts: msg.counts,
          failedReason: msg.failedReason ?? null,
          closedAt: closedAtOf(m, msg.voteId),
          ...(msg.electionResult ? { electionResult: msg.electionResult } : {}),
          ...(msg.pollResult ? { pollResult: msg.pollResult } : {}),
        });
        break;
      case 'vote_lot_drawn':
        this.voteEvents++;
        this.patchVote(msg.voteId, { result: msg.result, electionResult: msg.electionResult });
        break;
      case 'vote_cancelled':
        this.voteEvents++;
        this.patchVote(msg.voteId, {
          status: 'cancelled',
          closedAt: closedAtOf(m, msg.voteId),
        });
        break;
      case 'viewers':
        this.viewers.set(msg.viewers);
        break;
      case 'body_draft':
        this.applyBodyDraft(m, msg);
        break;
      default:
        break;
    }
  }

  /**
   * Read the meeting again after a `meeting_state` event (quiet GET).
   *
   * The GET gives the rights of this viewer after a handover: the new keeper
   * gets the editor and the vote controls, the old keeper loses the controls.
   * When the viewer can write now but has no protocol loaded yet, the method
   * loads it.
   *
   * A vote event that arrives while the read runs triggers one more read, because the read may
   * predate it and would undo it.
   */
  private reloadAfterState(meetingId: Uuid, attempt = 0): void {
    const events = this.voteEvents;
    this.api.getMeeting(meetingId, { quiet: true }).subscribe({
      next: (read) => {
        const current = this.meeting();
        if (current?.id !== read.id) return;
        let updated = read;
        if (this.voteEvents !== events) {
          if (attempt < 2) {
            this.reloadAfterState(meetingId, attempt + 1);
            return;
          }
          updated = { ...read, votes: current.votes };
        }
        this.meeting.set(updated);
        if (updated.protocolId && !this.protocol() && (this.canWrite() || this.canViewAll())) {
          this.refreshProtocol();
        }
      },
      error: () => {},
    });
  }

  /** Immutably patch a single vote in the meeting state. */
  private patchVote(voteId: Uuid, patch: Partial<MeetingVote>): void {
    const m = this.meeting();
    if (!m) return;
    this.meeting.set({
      ...m,
      votes: m.votes.map((v) => (v.id === voteId ? { ...v, ...patch } : v)),
    });
  }
}

/** The current time as an ISO timestamp, for a vote that changed here or by a live event. */
function nowIso(): string {
  return new Date().toISOString();
}

/** The end time of a vote: the known one (an own close or a read), else now. */
function closedAtOf(m: Meeting, voteId: Uuid): string {
  return m.votes.find((v) => v.id === voteId)?.closedAt ?? nowIso();
}
