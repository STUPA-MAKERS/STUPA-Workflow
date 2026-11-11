import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
  NgZone,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { ServerReachabilityService } from '@core/api/server-reachability.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type { MyBallot, ProblemDetail, Vote } from '@core/api/models';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import {
  Announcer,
  ButtonComponent,
  ConfirmDialogComponent,
  EmptyStateComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  ToastService,
} from '@stupa-makers/ui-kit';
import { problemDetail } from '@core/api/problem';
import type { Observable } from 'rxjs';
import { RailStatusService } from '../../layout/rail-status.service';
import type { BallotCaster, BallotFailure } from './ballot/ballot.component';
import { VotePanelComponent } from './vote-panel/vote-panel.component';
import { NO_CONTEXT, type VoteContext, loadVoteContext } from './vote-panel/vote-context';
import { voteChangeText, voteSubject, type SeenVote } from './vote-announce.util';
import { VotingPageService, visibleTicks } from './voting-page/voting-page.service';
import { BEAMER_FROM_PARAM } from './beamer-link.util';
import { TodoLinkedListComponent } from '../todos/linked-list/todo-linked-list.component';

type Phase = 'loading' | 'error' | 'ready';

/** 409 codes of `DELETE /votes/{id}`, mapped to their explanation. */
const DELETE_CONFLICT_KEYS: Record<string, TranslationKey> = {
  vote_meeting_bound: 'voting.delete.conflict.meetingBound',
  vote_not_deletable: 'voting.delete.conflict.notDeletable',
};

const NOT_CAST: MyBallot = { cast: false, choice: null };

/**
 * One vote: the detail pane of the page "Abstimmungen" (`/voting/:id`, boards
 * Arbeit-Abstimmungen and Telefon-Abstimmen). Side by side it is the sheet beside the
 * list; one pane at a time it is the page.
 *
 * - The server flags decide the controls: `canCast` gives the own ballot, `canManage`
 *   the delete. A 403 on the load or on an own cast marks the person as not eligible.
 *   A 403 on a represented cast removes the row "Als Vertretung für <name>". After a
 *   refused cast the page reads the vote and the delegation state again.
 * - A ballot never changes after the cast. `myBallot` and `representedCast` of
 *   the server restore the lock on a reload; a 409 `already_voted` locks it too. After a
 *   cast the pane stays on the vote and tells the list, so the row reads "Abgestimmt".
 * - The delegation state explains a voting right that the person handed over, or it
 *   adds the row "Als Vertretung für <name>" (cast with `asDelegation`).
 * - A meeting vote follows its meeting over the WebSocket while it is a draft or open:
 *   the turnout grows with each ballot, an open or a close reads the vote again, so the
 *   result shows as the server has it, and a cancel shows the cancelled vote.
 * - A draft or an open vote without a channel (a poll of a Gremium) reads itself again
 *   every `VOTE_POLL_MS` while the tab is visible and when the tab comes back.
 * - A meeting vote names its meeting and agenda item ("34. Sitzung · TOP 3") and links
 *   the beamer for a person who may run the meeting. A vote without a meeting links its
 *   application, and a draft of it can be deleted.
 * - A phone uses the detail bar of the list/detail layout like every other detail
 *   (§ 000674): the back arrow, the menu and, after a scroll, the title. The meeting line
 *   stands in the status line below the title. The button bar of the ballot is pinned at
 *   the bottom.
 * - The route reuses the component from one vote to the next, so the pane loads again
 *   on each change of `:id`.
 * - Under the vote: the to-do cards that link it (`app-todo-linked-list`).
 * - Side by side the sheet fills the pane and scrolls inside itself.
 */
@Component({
  selector: 'app-vote-cast',
  host: { '[class.vc-host--split]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ConfirmDialogComponent,
    RouterLink,
    ButtonComponent,
    EmptyStateComponent,
    IconComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    TodoLinkedListComponent,
    TranslatePipe,
    VotePanelComponent,
  ],
  templateUrl: './vote-cast.component.html',
  styleUrl: './vote-cast.component.scss',
})
export class VoteCastComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly reachability = inject(ServerReachabilityService);
  private readonly railStatus = inject(RailStatusService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly liveVotes = inject(LiveVoteService);
  /** The list page around the pane. The pane also works without it (a test). */
  private readonly page = inject(VotingPageService, { optional: true });

  readonly phone = mediaQuery(MEDIA.phone);
  /** The list sits beside the pane: the vote is a sheet. */
  readonly split = computed(() => this.page?.split() ?? false);
  readonly phase = signal<Phase>('loading');
  /** The vote as `GET /votes/{id}` gave it. */
  private readonly loaded = signal<Vote | null>(null);
  readonly context = signal<VoteContext>(NO_CONTEXT);
  /** The person may not cast an own ballot (server flag, a 403, a handed-over right). */
  readonly notEligible = signal(false);
  /** Delegation state: the person handed the voting right over, or acts as a proxy. */
  readonly delegation = signal<VoteDelegationStatus | null>(null);
  /** The server refused the represented ballot (403), so the proxy row goes away. */
  readonly proxyRefused = signal(false);
  /** The live channel of the meeting of the vote, while the vote is a draft or open. */
  readonly session = signal<LiveVoteSession | null>(null);
  /** A channel this pane opened itself (no list page around it), and its meeting. */
  private ownSession: LiveVoteSession | null = null;
  private ownMeetingId: string | null = null;
  /** The vote the channel showed open at the last check, so a close of it reloads. */
  private lastOpened: string | null = null;
  /** The status of the shown vote when it was last read, for the announcement of a change. */
  private lastStatus: SeenVote | null = null;
  private readonly announcer = inject(Announcer);
  /** The id of the shown vote. A late answer for another vote is dropped. */
  private currentId: string | null = null;

  /** The vote with the newest turnout of the socket. */
  readonly vote = computed<Vote | null>(() => {
    const vote = this.loaded();
    if (!vote) return null;
    const msg = this.session()?.tally();
    if (!msg || msg.voteId !== vote.id || vote.status !== 'open') return vote;
    const revealed = msg.revealed ?? vote.tally.revealed ?? true;
    return {
      ...vote,
      tally: {
        ...vote.tally,
        counts: revealed ? msg.counts : {},
        voted: msg.cast ?? vote.tally.voted,
        present: msg.present ?? vote.tally.present,
        revealed,
        quorumMet: msg.quorumMet,
      },
    };
  });

  /**
   * The confirmation to delete a standalone vote. The route accepts the delete only while
   * the vote is a draft or cancelled (§F/meetings/voting/000029). It refuses a
   * meeting-bound vote, because that one goes through its meeting.
   */
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly canDelete = computed(() => {
    const vote = this.loaded();
    return (
      !!vote &&
      (vote.status === 'draft' || vote.status === 'cancelled') &&
      !vote.meetingId &&
      vote.canManage === true
    );
  });

  /** The own ballot for the ballot, or `null` without an own voting right. */
  readonly own = computed<MyBallot | null>(() => {
    const vote = this.loaded();
    if (!vote || this.notEligible() || vote.canCast !== true) return null;
    return vote.myBallot ?? NOT_CAST;
  });
  /** The member the person represents in this vote, or `null`. */
  readonly proxyName = computed(() => {
    const d = this.delegation();
    if (this.proxyRefused() || !d?.exercising) return null;
    return d.delegatedByName || '?';
  });
  readonly proxyCast = computed(() => this.loaded()?.representedCast === true);

  /** Why an open vote offers no ballot. */
  readonly notice = computed<string | null>(() => {
    if (this.vote()?.status !== 'open') return null;
    const d = this.delegation();
    if (d?.blocked) {
      return this.i18n.translate('voting.cast.delegation.blocked', {
        name: d.delegatedToName || '?',
      });
    }
    if (this.own() === null && this.proxyName() === null) {
      return this.i18n.translate('voting.cast.notEligible');
    }
    return null;
  });

  /** The beamer of the meeting, for a person who may run it. */
  readonly beamerLink = computed<string[] | null>(() => {
    const meetingId = this.loaded()?.meetingId;
    if (!meetingId) return null;
    const gremiumId = this.context().meeting?.gremiumId;
    const allowed = gremiumId
      ? this.auth.canInGremium(gremiumId, 'session.manage')
      : this.auth.canInAnyGremium('session.manage');
    return allowed ? ['/voting/projector', meetingId] : null;
  });

  /**
   * The poll of a Gremium (no meeting) that the person may manage: "Starten" while it is
   * a draft, "Umfrage beenden" while it is open. A meeting poll runs in its meeting.
   */
  readonly pollAction = computed<'start' | 'close' | null>(() => {
    const vote = this.loaded();
    if (!vote || vote.kind !== 'poll' || vote.meetingId || vote.canManage !== true) return null;
    if (vote.status === 'draft') return 'start';
    return vote.status === 'open' ? 'close' : null;
  });
  /** A poll action runs. */
  readonly pollBusy = signal(false);

  /** The ⋮ menu: the poll action, then the delete. */
  readonly menu = computed<readonly RowMenuSection[]>(() => {
    const action = this.pollAction();
    const pollItems: readonly RowMenuItem[] = action ? [this.pollMenuItem(action)] : [];
    const deleteItems: readonly RowMenuItem[] = this.canDelete()
      ? [
          {
            id: 'delete',
            label: this.i18n.translate('voting.delete.action'),
            icon: 'trash',
            danger: true,
          },
        ]
      : [];
    return [{ items: [...pollItems, ...deleteItems] }];
  });
  /** The ⋮ menu has an item. */
  readonly hasMenu = computed(() => this.menu()[0]!.items.length > 0);

  /** Send one ballot. The ballot component locks the row and reports the outcome. */
  readonly caster: BallotCaster = (choice, asDelegation) =>
    this.api.castBallot(this.loaded()?.id ?? '', choice, asDelegation);

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => this.open(pm.get('id')));
    this.followLive();
    visibleTicks(inject(NgZone))
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.poll());
    effect(() => {
      const vote = this.loaded();
      const shown = vote
        ? { id: vote.id, meetingId: vote.meetingId ?? null, status: vote.status }
        : null;
      untracked(() => this.page?.shown.set(shown));
    });
    effect(() => {
      const lost = this.connectionLost();
      untracked(() => this.showConnectionLost(lost));
    });
  }

  /**
   * The live connection is lost and the client tries again (§ 000678). Not while the
   * server or the network is away: then the bar "Server nicht erreichbar" says so.
   */
  readonly connectionLost = computed(
    () => this.session()?.connection() === 'reconnecting' && !this.reachability.waiting(),
  );
  private lostToast: number | null = null;

  /** The toast "Verbindung verloren" stays while the connection is lost and closes itself. */
  private showConnectionLost(lost: boolean): void {
    if (lost && this.lostToast === null) {
      this.lostToast = this.toast.showNotice({
        message: this.i18n.translate('voting.live.reconnecting'),
        variant: 'warning',
        // On a phone the notice is the bar at the top of the frame, like "Server nicht
        // erreichbar": a card that stays would cover the back arrow of the detail.
        phonePlacement: 'top',
      });
    } else if (!lost && this.lostToast !== null) {
      this.toast.dismiss(this.lostToast);
      this.lostToast = null;
    }
  }

  ngOnDestroy(): void {
    this.ownSession?.close();
    this.page?.shown.set(null);
    this.showConnectionLost(false);
  }

  goBeamer(): void {
    const link = this.beamerLink();
    if (!link) return;
    void this.router.navigate(link, { queryParams: { [BEAMER_FROM_PARAM]: this.router.url } });
  }

  onMenu(id: string): void {
    switch (id) {
      case 'delete':
        this.confirmDelete.set(true);
        return;
      case 'start':
      case 'close':
        this.runPoll(id);
        return;
      default:
        return;
    }
  }

  /** The menu item of a poll action: "Starten" or "Umfrage beenden". */
  private pollMenuItem(action: 'start' | 'close'): RowMenuItem {
    switch (action) {
      case 'start':
        return { id: 'start', label: this.i18n.translate('poll.action.start'), icon: 'play' };
      case 'close':
        return { id: 'close', label: this.i18n.translate('poll.action.close'), icon: 'square' };
    }
  }

  /** "Starten" opens the draft of a poll, "Umfrage beenden" closes it before its end. */
  private runPoll(action: 'start' | 'close'): void {
    const vote = this.loaded();
    if (!vote || this.pollBusy()) return;
    this.pollBusy.set(true);
    const call: Observable<unknown> =
      action === 'start' ? this.api.openVote(vote.id) : this.api.closeVote(vote.id);
    call.subscribe({
      next: () => {
        this.pollBusy.set(false);
        this.toast.success(
          this.i18n.translate(action === 'start' ? 'poll.toast.started' : 'poll.toast.closed'),
        );
        this.page?.notify({ id: vote.id, kind: 'updated' });
        this.reload();
      },
      error: (err: unknown) => {
        this.pollBusy.set(false);
        const detail = problemDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
        this.reload();
      },
    });
  }

  /** The ballot says "Danke! Deine Stimme: Ja" itself, so no toast repeats it. */
  /** The lot of an election was drawn, or its runoff opened: read the vote again. */
  onElectionChanged(): void {
    this.reload();
  }

  onCastDone(): void {
    this.railStatus.refresh();
    const id = this.loaded()?.id;
    if (id) this.page?.notify({ id, kind: 'cast' });
    this.reload();
  }

  /**
   * A refused row hides, so that the person cannot send the same ballot into the same 403, and the
   * state loads again, because the voting right can have moved after the page loaded.
   */
  onCastFailed(failure: BallotFailure): void {
    const { error } = failure;
    if (error.status === 403) {
      if (failure.asDelegation) this.proxyRefused.set(true);
      else this.notEligible.set(true);
      this.toast.error(this.i18n.translate('voting.cast.notEligible'));
      this.reload();
      const id = this.loaded()?.id;
      if (id) this.loadDelegation(id);
      return;
    }
    if (error.status === 409) {
      this.toast.error(
        this.i18n.translate(
          failure.alreadyVoted ? 'voting.cast.toast.alreadyVoted' : 'voting.cast.toast.conflict',
        ),
      );
      this.reload();
      return;
    }
    this.toast.error(error.error?.detail ?? this.i18n.translate('voting.cast.toast.failed'));
  }

  /**
   * Delete the vote for good (`DELETE /votes/{id}`).
   *
   * A 409 is a real state, not a generic failure: the vote opened, it already holds
   * ballots, or it belongs to a meeting. Name the reason and reload, so the page shows
   * the state the server has.
   *
   * The vote is gone, so this route answers 404 from now on.
   */
  doDelete(): void {
    const vote = this.loaded();
    if (!vote || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteVote(vote.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        this.toast.success(this.i18n.translate('voting.delete.done'));
        this.page?.notify({ id: vote.id, kind: 'deleted' });
        void this.router.navigate(['/voting'], { queryParamsHandling: 'preserve' });
      },
      error: (err: { status?: number; error?: ProblemDetail }) => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        if (err.status === 409) {
          const key = DELETE_CONFLICT_KEYS[err.error?.code ?? ''] ?? 'voting.delete.conflict.other';
          this.toast.error(this.i18n.translate(key));
          this.reload();
          return;
        }
        this.toast.error(
          this.i18n.translate(
            err.status === 403 ? 'voting.delete.forbidden' : 'voting.delete.failed',
          ),
        );
      },
    });
  }

  /** Show the vote of the route: reset the pane, then read the vote and its context. */
  private open(id: string | null): void {
    this.currentId = id;
    this.loaded.set(null);
    this.context.set(NO_CONTEXT);
    this.notEligible.set(false);
    this.delegation.set(null);
    this.proxyRefused.set(false);
    this.confirmDelete.set(false);
    this.phase.set('loading');
    if (!id) {
      this.phase.set('error');
      return;
    }
    this.loadDelegation(id, true);
    this.api.getVote(id, { detail: true }).subscribe({
      next: (vote) => {
        if (this.currentId !== id) return;
        const first = this.loaded() === null;
        this.loaded.set(vote);
        this.notEligible.set(vote.canCast !== true || !!this.delegation()?.blocked);
        this.phase.set('ready');
        if (!first) return;
        loadVoteContext(this.api, vote.meetingId, vote.agendaItemId).subscribe((ctx) => {
          if (this.currentId === id) this.context.set(ctx);
        });
      },
      error: (err: { status?: number }) => {
        if (this.currentId !== id) return;
        if (err.status === 403) {
          this.notEligible.set(true);
          this.phase.set('ready');
        } else {
          this.phase.set('error');
        }
      },
    });
  }

  /**
   * Follow the meeting of the vote while the vote is a draft or open. The list page
   * shares its channel; without the page the pane opens its own.
   *
   * - `vote_opened` of this draft: read the vote again (it is open now).
   * - `vote_closed` of this vote: read the vote again (the result).
   * - The open vote of the channel was this vote and is gone without a result: the
   *   vote was cancelled; read it again.
   */
  private followLive(): void {
    effect(() => {
      const vote = this.loaded();
      const meetingId = vote?.meetingId ?? null;
      const live = !!vote && (vote.status === 'open' || vote.status === 'draft');
      untracked(() => {
        if (!live || !meetingId) {
          this.session.set(null);
          return;
        }
        if (this.page) {
          this.session.set(this.page.follow(meetingId));
          return;
        }
        if (this.ownMeetingId !== meetingId) {
          this.ownSession?.close();
          this.ownSession = this.liveVotes.open(meetingId);
          this.ownMeetingId = meetingId;
        }
        this.session.set(this.ownSession);
      });
    });

    effect(() => {
      const session = this.session();
      const opened = session?.openVote()?.voteId ?? null;
      const closed = session?.result()?.voteId ?? null;
      untracked(() => {
        const vote = this.loaded();
        const before = this.lastOpened;
        this.lastOpened = opened;
        if (!vote) return;
        if (vote.status === 'draft' && opened === vote.id) this.reload();
        else if (vote.status === 'open' && closed === vote.id) this.reload();
        else if (vote.status === 'open' && before === vote.id && opened !== vote.id) this.reload();
      });
    });

    effect(() => {
      const vote = this.loaded();
      untracked(() => this.announceChange(vote));
    });
  }

  /**
   * Read out that the shown vote opened or closed (spec 000518). The change comes over the
   * live channel or the poll, without an action of the reader, so a screen reader would
   * not notice it. The text names the vote and its TOP, and the result on a close.
   */
  private announceChange(vote: Vote | null): void {
    const before = this.lastStatus;
    this.lastStatus = vote ? { id: vote.id, status: vote.status } : null;
    if (!vote) return;
    const { meeting, position } = this.context();
    const t: Translate = (key, params) => this.i18n.translate(key, params);
    this.announcer.announce(voteChangeText(t, before, vote, voteSubject(t, vote.question, meeting?.title, position)));
  }


  /**
   * Read the delegation status. It explains a handed-over voting right, or it unlocks
   * the proxy row. `exercising` does not free the own ballot: an external substitute
   * casts the represented ballot only.
   */
  private loadDelegation(id: string, detail = false): void {
    this.delegations.voteStatus(id, { detail }).subscribe({
      next: (status) => {
        if (this.currentId !== id) return;
        const was = this.delegation();
        this.delegation.set(status);
        if (status.blocked) this.notEligible.set(true);
        else if (was?.blocked && this.loaded()?.canCast === true) this.notEligible.set(false);
      },
      error: () => {},
    });
  }

  /**
   * The pane updates itself: a draft or an open vote without a live channel (a poll of a
   * Gremium) is read again every `VOTE_POLL_MS` while the tab is visible, and when the tab
   * comes back. The turnout grows, a start or an end shows. A new status tells the list.
   * A meeting vote has its channel, which is faster.
   */
  private poll(): void {
    const vote = this.loaded();
    if (!vote || this.session()) return;
    if (vote.status !== 'open' && vote.status !== 'draft') return;
    const id = vote.id;
    this.api.getVote(id, { quiet: true }).subscribe({
      next: (v) => {
        if (this.currentId !== id) return;
        const was = this.loaded()?.status;
        this.loaded.set(v);
        if (was && was !== v.status) this.page?.notify({ id, kind: 'updated' });
      },
      error: () => {},
    });
  }

  /** Read the vote again: the tally, the own ballot and the flags. Never guess them. */
  private reload(): void {
    const vote = this.loaded();
    if (!vote) return;
    const id = vote.id;
    this.api.getVote(id, { quiet: true }).subscribe((v) => {
      if (this.currentId === id) this.loaded.set(v);
    });
  }
}
