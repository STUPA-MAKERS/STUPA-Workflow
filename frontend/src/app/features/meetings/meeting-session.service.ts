import {
  DestroyRef,
  Injectable,
  type OnDestroy,
  computed,
  inject,
  signal,
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
  MeetingVote,
  Protocol,
  SelfAttendanceStatus,
  Uuid,
} from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingAgendaService } from './meeting-agenda.service';
import {
  assembleProtocolMarkdown,
  canReportOwn,
  errorCode,
  errorDetail,
  liveOpenedVote,
} from './meetings-display.util';

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
  /** Poll fallback while the worker renders the protocol. */
  private renderPollTimer: ReturnType<typeof setTimeout> | null = null;

  /** The vote with a cast in flight, and the vote with a delete in flight. */
  readonly casting = signal<Uuid | null>(null);
  readonly deletingVote = signal<Uuid | null>(null);
  /** Own choice per vote (local, highlights the picked option). */
  readonly myChoices = signal<Record<string, string>>({});

  private channel: MeetingChannel | null = null;

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
    // Readers with view_all get the full 3-column view read-only.
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
   * After the close there is no live keeper to protect. Every writer edits the draft
   * (O22): the session lead, the finalizer and an earlier keeper, not only the last
   * one. A final protocol stays locked through `Protocol.isLocked`.
   */
  readonly canEditProtocol = computed(() => {
    const m = this.meeting();
    if (!m?.canWrite) return false;
    if (m.status === 'closed') return true;
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

  private adoptMeeting(m: Meeting): void {
    this.meeting.set(m);
    this.attendanceConflict.set(null);
    this.planDate.set(m.date ?? '');
    this.planTime.set(m.startTime ?? '');
    this.connectLive(m.id);
    // Read an existing protocol with GET, which keeps the write rate limit
    // intact. A protocol is only ever created explicitly.
    if (m.protocolId && (this.canWrite() || this.canViewAll())) this.refreshProtocol();
    this.loadAttendance(m.id);
    this.agendaSvc.load(m.id, m.currentAgendaItemId);
  }

  /**
   * Tell the room which agenda item runs now.
   *
   * The protokollant leads, and the session lead may take over, so the gate is
   * `canManageVotes`. Everybody else keeps a local selection. Only a live meeting
   * has a "now": the server refuses it for a closed meeting, and a planned meeting
   * must not start with an item that a click during the preparation set.
   */
  setCurrentTop(itemId: Uuid): void {
    const m = this.meeting();
    if (!m || !m.canManageVotes || m.status !== 'live' || m.currentAgendaItemId === itemId) return;
    this.api.patchMeeting(m.id, { currentAgendaItemId: itemId }).subscribe({
      next: (updated) => this.meeting.set(updated),
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /**
   * Start a planned meeting (planned → live). The server creates the protocol on
   * the start. Only a planned meeting starts, and it needs a minute-taker: the page
   * says so at once instead of showing the server 409 after the click.
   *
   * The close is a dialog of its own (`CloseMeetingDialogComponent`), and a planned
   * meeting that does not take place is deleted, not closed (O13).
   */
  startMeeting(): void {
    const m = this.meeting();
    if (!m || m.status !== 'planned') return;
    if (!m.protokollantId) {
      this.toast.error(this.i18n.translate('meetings.toast.protokollantRequired'));
      return;
    }
    this.api.patchMeeting(m.id, { status: 'live' }).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        // The backend creates the protocol on start. Fetch it right away.
        if (updated.status === 'live' && updated.protocolId && this.canWrite()) {
          this.refreshProtocol();
        }
      },
      error: (err: unknown) => this.statusChangeFailed(err),
    });
  }

  /**
   * Show why the server refused a status change, then reload the meeting. The
   * meeting may have changed in another tab.
   */
  private statusChangeFailed(err: unknown): void {
    const detail = errorDetail(err);
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

  openVote(voteId: Uuid): void {
    this.api.openVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'open', openedAt: nowIso() }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Close a vote. The close always ends the vote. When the pass or fail
   *  transition of the application is blocked (`branchFired: false`), a warning
   *  tells the manager to move the application by hand. */
  closeVote(voteId: Uuid): void {
    this.api.closeVote(voteId).subscribe({
      next: (closed) => {
        this.patchVote(voteId, { status: 'closed', closedAt: nowIso() });
        // A generic motion has no application and fires no branch on purpose.
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
    const detail = errorDetail(err);
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
        // A closed meeting keeps its votes (409 `meeting_closed`), and an open or
        // closed vote stays (409 `vote_not_deletable`). Show the reason.
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

  finalize(): void {
    const proto = this.protocol();
    // `isLocked` also covers `rendering`: no second start, no 409 on PATCH.
    if (!proto || proto.isLocked || this.finalizing() || this.agendaSvc.savingTop()) return;
    // F8, O13: the protocol is finalized only after the close (409 otherwise), as a
    // step of its own. The close never finalizes.
    if (this.meeting()?.status !== 'closed') return;
    this.finalizing.set(true);
    // First persist the assembled TOP markdown, then finalize/render.
    this.api.updateProtocol(proto.id, assembleProtocolMarkdown(this.agendaSvc.agenda())).subscribe({
      next: (saved) => {
        this.protocol.set(saved);
        this.doFinalize(saved.id);
      },
      error: () => {
        this.finalizing.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.saveFailed'));
      },
    });
  }

  private doFinalize(protocolId: Uuid): void {
    this.api.finalizeProtocol(protocolId).subscribe({
      next: (updated) => {
        this.finalizing.set(false);
        this.protocol.set(updated);
        if (updated.isFinal) {
          // Sync path (dev without Redis): the protocol is final right away.
          this.toast.success(this.i18n.translate('meetings.toast.finalized'));
        } else {
          // Async path: the worker renders in the background. The completion
          // arrives over the WS broadcast or the poll fallback.
          this.toast.success(this.i18n.translate('meetings.toast.renderQueued'));
          this.watchRendering(updated);
        }
      },
      error: (err: unknown) => {
        this.finalizing.set(false);
        // Render and compile errors (400) carry a concrete reason. Show it.
        const detail = errorDetail(err);
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
    const code = errorCode(err);
    if (code === 'delegation_active') {
      if (asLead) {
        this.attendanceConflict.set(principalId);
      } else {
        this.toast.error(this.i18n.translate('meetings.toast.ownDelegationActive'));
      }
    } else if (code === 'attendance_set_by_lead') {
      this.toast.error(this.i18n.translate('meetings.toast.attendanceSetByLead'));
    } else {
      const detail = errorDetail(err);
      const base = this.i18n.translate('meetings.toast.actionFailed');
      this.toast.error(detail ? `${base}: ${detail}` : base);
      return;
    }
    this.loadAttendance(meetingId);
  }

  private connectLive(meetingId: Uuid): void {
    this.viewers.set([]); // drop the state of the previous meeting
    // Mock mode (FE dev and test harness) has no WS server. Skip the live channel.
    if (this.useMock) return;
    this.channel?.close();
    this.channel = this.ws.connectMeeting(meetingId);
    this.channel.messages$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => this.onLive(msg));
  }

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
        // TOP bodies can change without a vote. Reload the agenda so live
        // followers see the current protocol state.
        this.agendaSvc.load(m.id, currentAgendaItemId);
        // The event carries no rights. A handover (or the start of a planned
        // handover on a TOP move) moves canWrite, canManageVotes and the keeper
        // data, so read the meeting again.
        this.reloadAfterState(m.id);
        // The protocol status can change (rendering → final or draft). The worker
        // broadcasts meeting_state after the background render. Use GET so
        // broadcast bursts do not burn the write rate limit.
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
        const known = m.votes.find((v) => v.id === msg.voteId);
        if (known) {
          this.patchVote(msg.voteId, {
            status: 'open',
            closesAt: msg.closesAt,
            // Another manager opened it: the card shows "seit HH:MM" at once. Keep the
            // time of an own open, or of a read.
            openedAt: known.openedAt ?? nowIso(),
            secret: msg.secret ?? known.secret,
          });
        } else {
          // A vote opened live that did not exist at load time (follower).
          this.meeting.set({ ...m, votes: [...m.votes, liveOpenedVote(msg)] });
        }
        break;
      }
      case 'vote_tally':
        this.patchVote(msg.voteId, {
          counts: msg.counts,
          leading: msg.leading,
          voted: msg.cast ?? 0,
          present: msg.present ?? 0,
          revealed: msg.revealed ?? true,
        });
        break;
      case 'vote_closed':
        this.patchVote(msg.voteId, {
          status: 'closed',
          result: msg.result,
          counts: msg.counts,
          failedReason: msg.failedReason ?? null,
          closedAt: closedAtOf(m, msg.voteId),
        });
        break;
      case 'vote_cancelled':
        this.patchVote(msg.voteId, {
          status: 'cancelled',
          closedAt: closedAtOf(m, msg.voteId),
        });
        break;
      case 'viewers':
        this.viewers.set(msg.viewers);
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
   */
  private reloadAfterState(meetingId: Uuid): void {
    this.api.getMeeting(meetingId, { quiet: true }).subscribe({
      next: (updated) => {
        if (this.meeting()?.id !== updated.id) return; // the user opened another meeting
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
