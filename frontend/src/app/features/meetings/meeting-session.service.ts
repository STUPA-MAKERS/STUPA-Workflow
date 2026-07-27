import {
  DestroyRef,
  Injectable,
  type OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
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
  Uuid,
} from '@core/api/models';
import { WsService, type MeetingChannel } from '@core/ws/ws.service';
import type { ServerMessage } from '@core/ws/ws-messages';
import { ToastService, type SelectOption } from '@stupa-makers/ui-kit';
import { MeetingAgendaService } from './meeting-agenda.service';
import {
  FIXED_VOTE_OPTIONS,
  assembleProtocolMarkdown,
  errorDetail,
  liveOpenedVote,
  pickBeamerVote,
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

  readonly voteDialogOpen = signal(false);
  private readonly voteItem = signal<AgendaItem | null>(null);
  readonly voteQuestion = signal<string>('');
  readonly voteSecret = signal(false);
  // Only the majority rule is set per vote. The quorum and the eligible voters
  // come from the Gremium configuration.
  readonly voteMajorityRule = signal<'simple' | 'absolute' | 'two_thirds'>('simple');
  readonly majorityRuleOptions = computed<SelectOption[]>(() =>
    (['simple', 'absolute', 'two_thirds'] as const).map((v) => ({
      value: v,
      label: this.i18n.translate(`vote.majority.${v}`),
    })),
  );
  readonly openingVote = signal(false);

  private channel: MeetingChannel | null = null;

  // Permission flags, per meeting where loaded. The backend checks them per Gremium.
  readonly canManageAny = computed(() => this.auth.can('meeting.manage'));
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
   * edit/manager view. After a protokollant is chosen, ONLY that person gets
   * the manager view. Without a protokollant the write/manage gate applies.
   * This keeps a fresh meeting usable before the start.
   */
  readonly isFollower = computed(() => {
    const m = this.meeting();
    if (!m) return false;
    // Readers with view_all get the full 3-column view read-only. This applies
    // only when they have no write or manage right on this meeting. Otherwise
    // they would bypass the protokollant exclusivity below.
    if (this.canViewAll() && !m.canWrite && !m.canManage) return false;
    if (m.protokollantId) return !this.isProtokollant();
    return !m.canWrite && !m.canManage;
  });

  /** Votes of one TOP, grouped by agendaItemId. */
  votesForTop(topId: Uuid): MeetingVote[] {
    return (this.meeting()?.votes ?? []).filter((v) => v.agendaItemId === topId);
  }
  /** Meeting votes without a TOP binding. The control card lists them. */
  readonly looseVotes = computed<MeetingVote[]>(() =>
    (this.meeting()?.votes ?? []).filter((v) => !v.agendaItemId),
  );
  /** Beamer: currently open vote, else the last closed one. */
  readonly beamerVote = computed<MeetingVote | null>(() =>
    pickBeamerVote(this.meeting()?.votes ?? []),
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
    this.planDate.set(m.date ?? '');
    this.planTime.set(m.startTime ?? '');
    this.connectLive(m.id);
    // Read an existing protocol with GET, which keeps the write rate limit
    // intact. A protocol is only ever created explicitly.
    if (m.protocolId && (this.canWrite() || this.canViewAll())) this.refreshProtocol();
    this.loadAttendance(m.id);
    this.agendaSvc.load(m.id, this.canManage());
  }

  setStatus(status: 'live' | 'closed'): void {
    const m = this.meeting();
    if (!m) return;
    // "closed" is terminal. Nobody reopens a meeting, and the server refuses it.
    if (m.status === 'closed') return;
    // A start requires a protokollant. Check it here instead of showing the
    // server 409 after the click.
    if (status === 'live' && !m.protokollantId) {
      this.toast.error(this.i18n.translate('meetings.toast.protokollantRequired'));
      return;
    }
    this.api.patchMeeting(m.id, { status }).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        // The backend creates the protocol on start. Fetch it right away.
        if (updated.status === 'live' && updated.protocolId && this.canWrite()) {
          this.refreshProtocol();
        }
      },
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
    });
  }

  /** Close the meeting irrevocably: set the status to closed and finalize the protocol. */
  closeMeeting(): void {
    const m = this.meeting();
    if (!m || this.finalizing()) return;
    this.api.patchMeeting(m.id, { status: 'closed' }).subscribe({
      next: (updated) => {
        this.meeting.set(updated);
        const proto = this.protocol();
        // The finalize step is implicit: render the PDF and mail it to the list.
        if (proto && !proto.isLocked) {
          this.finalize();
        }
      },
      error: () => this.toast.error(this.i18n.translate('meetings.toast.actionFailed')),
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

  openVote(voteId: Uuid): void {
    this.api.openVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'open' }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  closeVote(voteId: Uuid): void {
    this.api.closeVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'closed' }),
      error: (err: unknown) => this.voteActionFailed(err),
    });
  }

  /** Cancel a vote: open → cancelled, with no result and no branch. This is the
   *  way out when the quorum is not reached, because a close is blocked then. */
  cancelVote(voteId: Uuid): void {
    this.api.cancelVote(voteId).subscribe({
      next: () => this.patchVote(voteId, { status: 'cancelled' }),
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
      error: () => {
        this.deletingVote.set(null);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** An application TOP holds exactly one vote. A freetext TOP holds any number. */
  canAddVote(item: AgendaItem): boolean {
    return !item.applicationId || this.votesForTop(item.id).length === 0;
  }

  openVoteDialog(item: AgendaItem): void {
    this.voteItem.set(item);
    // An application TOP carries the application title as its TOP title. Prefill
    // the question with it. The user can still edit it. A freetext TOP keeps the
    // raw title.
    this.voteQuestion.set(
      item.applicationId
        ? this.i18n.translate('meetings.vote.questionPrefill', { name: item.title ?? '' })
        : (item.title ?? ''),
    );
    this.voteSecret.set(false);
    this.voteMajorityRule.set('simple');
    this.voteDialogOpen.set(true);
  }

  closeVoteDialog(): void {
    this.voteDialogOpen.set(false);
  }

  submitVote(): void {
    const m = this.meeting();
    const item = this.voteItem();
    const options = [...FIXED_VOTE_OPTIONS];
    if (!m || !item || this.openingVote()) return;
    this.openingVote.set(true);
    this.api
      .openMeetingVote(m.id, {
        agendaItemId: item.id,
        question: this.voteQuestion().trim() || null,
        options,
        secret: this.voteSecret(),
        majorityRule: this.voteMajorityRule(),
        // eligibleCount and quorumPercent are omitted, so the server uses the
        // Gremium defaults.
      })
      .subscribe({
        next: (updated) => {
          this.openingVote.set(false);
          this.voteDialogOpen.set(false);
          this.meeting.set(updated);
          this.toast.success(this.i18n.translate('meetings.toast.voteOpened'));
        },
        error: (err: unknown) => {
          this.openingVote.set(false);
          const detail = errorDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.error(detail ? `${base}: ${detail}` : base);
        },
      });
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

  setAttendance(member: Attendance, status: AttendanceStatus): void {
    const m = this.meeting();
    if (!m || this.savingAttendance() || member.status === status) return;
    this.savingAttendance.set(true);
    // Own attendance goes through the self endpoint. The lead sets it for members.
    const req = member.isSelf
      ? this.api.setOwnAttendance(m.id, status)
      : this.api.setMemberAttendance(m.id, member.principalId, status);
    req.subscribe({
      next: (rows) => {
        this.savingAttendance.set(false);
        this.attendance.set(rows);
      },
      error: () => {
        this.savingAttendance.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
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
      case 'meeting_state':
        this.meeting.set({
          ...m,
          status: (msg.status as Meeting['status']) ?? m.status,
          activeApplicationId: msg.activeApplicationId,
        });
        // TOP bodies can change without a vote. Reload the agenda so live
        // followers see the current protocol state.
        this.agendaSvc.load(m.id, this.canManage());
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
      case 'vote_opened':
        if (m.votes.some((v) => v.id === msg.voteId)) {
          this.patchVote(msg.voteId, { status: 'open', closesAt: msg.closesAt });
        } else {
          // A vote opened live that did not exist at load time (follower).
          this.meeting.set({ ...m, votes: [...m.votes, liveOpenedVote(msg)] });
        }
        break;
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
        });
        break;
      case 'viewers':
        this.viewers.set(msg.viewers);
        break;
      default:
        break;
    }
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
