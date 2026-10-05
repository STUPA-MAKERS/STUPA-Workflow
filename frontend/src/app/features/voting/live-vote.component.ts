import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EMPTY, of } from 'rxjs';
import { catchError, expand, map, reduce } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Meeting, MyBallot, Vote } from '@core/api/models';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { ButtonComponent, IconComponent, MEDIA, ToastService } from '@stupa-makers/ui-kit';
import {
  LIVE_MAX_PAGES,
  LIVE_PAGE_LIMIT,
  RailStatusService,
} from '../../layout/rail-status.service';
import { mediaQuerySignal } from '../../layout/media-query';
import type { BallotCaster, BallotFailure } from './ballot/ballot.component';
import { VotePhoneHeaderComponent } from './phone-header/phone-header.component';
import { VotePanelComponent } from './vote-panel/vote-panel.component';
import { NO_CONTEXT, type VoteContext, loadVoteContext } from './vote-panel/vote-context';

/** What the page shows: the search for a running meeting, its result, or the vote. */
type Mode = 'resolving' | 'none' | 'pick' | 'live';

const NOT_CAST: MyBallot = { cast: false, choice: null };

/**
 * "Abstimmungen" during a meeting (`/voting`, `/voting/meeting/:id`, boards
 * Arbeit-Abstimmungen and Telefon-Abstimmen).
 *
 * `/voting` looks for the meetings that run now. With one (or one where the person may
 * vote) it shows its vote; with several it lists them; with none it says so. The page
 * follows the meeting over the WebSocket: a vote that opens shows at once, the turnout
 * grows with each ballot, and the result shows after the close.
 *
 * The vote itself comes from `GET /votes/{id}`: the question, the rules, the flag
 * `canCast`, the own ballot and the represented ballot. A ballot goes over REST
 * (`POST /votes/{id}/ballot`), which answers each ballot for itself. A ballot never
 * changes (O11). The own row stays away when the meeting says `canVote: false`, when the
 * server sends `not_eligible`, or when the person handed the voting right over.
 */
@Component({
  selector: 'app-live-vote',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    ButtonComponent,
    EmptyStateComponent,
    IconComponent,
    PageHeaderComponent,
    TranslatePipe,
    VotePanelComponent,
    VotePhoneHeaderComponent,
  ],
  templateUrl: './live-vote.component.html',
  styleUrl: './live-vote.component.scss',
})
export class LiveVoteComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly live = inject(LiveVoteService);
  private readonly railStatus = inject(RailStatusService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);

  readonly phone = mediaQuerySignal(MEDIA.phone);
  readonly mode = signal<Mode>('resolving');
  /** The running meetings, when `/voting` finds more than one. */
  readonly liveMeetings = signal<Meeting[]>([]);
  readonly session = signal<LiveVoteSession | null>(null);
  readonly meeting = signal<Meeting | null>(null);
  readonly context = signal<VoteContext>(NO_CONTEXT);
  /** The shown vote as `GET /votes/{id}` gave it. */
  private readonly loaded = signal<Vote | null>(null);
  readonly delegation = signal<VoteDelegationStatus | null>(null);
  /** The vote id of the last load, so that one vote is asked for once. */
  private requested: string | null = null;

  readonly connection = computed(() => this.session()?.connection() ?? 'connecting');
  private readonly errorCode = computed(() => this.session()?.errorCode() ?? null);

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

  readonly own = computed<MyBallot | null>(() => {
    const vote = this.loaded();
    if (!vote || vote.canCast !== true) return null;
    if (this.meeting()?.canVote === false || this.errorCode() === 'not_eligible') return null;
    if (this.delegation()?.blocked) return null;
    return vote.myBallot ?? NOT_CAST;
  });
  readonly proxyName = computed(() => {
    const d = this.delegation();
    return d?.exercising ? d.delegatedByName || '?' : null;
  });
  readonly proxyCast = computed(() => this.loaded()?.representedCast === true);

  readonly notice = computed<string | null>(() => {
    if (this.vote()?.status !== 'open') return null;
    const d = this.delegation();
    if (d?.blocked) {
      return this.i18n.translate('voting.cast.delegation.blocked', { name: d.delegatedToName || '?' });
    }
    if (this.own() === null && this.proxyName() === null) {
      return this.i18n.translate('voting.live.notEligible');
    }
    return null;
  });

  readonly beamerLink = computed<string[] | null>(() => {
    const m = this.meeting();
    if (!m) return null;
    const allowed = m.gremiumId
      ? this.auth.canInGremium(m.gremiumId, 'session.manage')
      : this.auth.canInAnyGremium('session.manage');
    return allowed ? ['/voting/beamer', m.id] : null;
  });

  readonly phoneSubtitle = computed<string | null>(() => {
    const { meeting, position } = this.context();
    const m = meeting ?? this.meeting();
    if (!m) return null;
    return position === null
      ? m.title
      : this.i18n.translate('voting.panel.wherePhone', { meeting: m.title, n: position });
  });

  readonly caster: BallotCaster = (choice, asDelegation) =>
    this.api.castBallot(this.loaded()?.id ?? '', choice, asDelegation);

  constructor() {
    const routeId = this.route.snapshot.paramMap.get('id');
    if (routeId) this.start(routeId);
    else this.resolve();

    // A vote that opens on the socket becomes the shown vote (the server sends the open
    // vote on each connect). When the socket gave up, the open vote of the meeting load
    // stands in, so a ballot over REST stays possible. The close reloads the vote, so
    // the result shows as the server has it.
    effect(() => {
      const session = this.session();
      const opened = session?.openVote()?.voteId ?? null;
      const fromMeeting =
        session?.connection() === 'closed'
          ? (this.meeting()?.votes.find((v) => v.status === 'open')?.id ?? null)
          : null;
      const id = opened ?? fromMeeting;
      untracked(() => {
        if (id && id !== this.loaded()?.id) this.load(id);
      });
    });
    effect(() => {
      const result = this.session()?.result();
      untracked(() => {
        if (result && result.voteId === this.loaded()?.id && this.loaded()?.status === 'open') {
          this.load(result.voteId, true);
        }
      });
    });
    // A cancelled vote leaves the page (the socket drops its open vote); the page waits
    // for the next one.
    let lastOpened: string | null = null;
    effect(() => {
      const opened = this.session()?.openVote()?.voteId ?? null;
      untracked(() => {
        if (lastOpened && !opened && this.loaded()?.id === lastOpened) {
          this.loaded.set(null);
          this.requested = null;
        }
        lastOpened = opened;
      });
    });
  }

  ngOnDestroy(): void {
    this.session()?.close();
  }

  goBeamer(): void {
    const link = this.beamerLink();
    if (link) void this.router.navigate(link);
  }

  onCastDone(): void {
    this.railStatus.refresh();
    this.reload();
  }

  onCastFailed(failure: BallotFailure): void {
    const { error } = failure;
    if (error.status === 403) {
      this.toast.error(this.i18n.translate('voting.cast.notEligible'));
      this.reload();
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

  /** Follow one meeting: the socket, the meeting flags and the open vote. */
  private start(meetingId: string): void {
    this.mode.set('live');
    this.session.set(this.live.open(meetingId));
    this.api.getMeeting(meetingId, { quiet: true }).subscribe({
      next: (m) => this.meeting.set(m),
      // The server still refuses a ballot the person may not cast.
      error: () => {},
    });
  }

  /** `/voting`: find the meetings that run now. */
  private resolve(): void {
    const page = (cursor: string | null) =>
      this.api.listMeetingsTimeline({ direction: 'upcoming', limit: LIVE_PAGE_LIMIT, cursor });
    page(null)
      .pipe(
        expand((p, i) => (p.nextCursor && i + 1 < LIVE_MAX_PAGES ? page(p.nextCursor) : EMPTY)),
        map((p) => p.items.filter((m) => m.status === 'live')),
        reduce((all, items) => [...all, ...items], [] as Meeting[]),
        catchError(() => of([] as Meeting[])),
      )
      .subscribe((running) => {
        const voting = running.filter((m) => m.canVote);
        const pick = running.length === 1 ? running[0] : voting.length === 1 ? voting[0] : null;
        if (pick) {
          this.start(pick.id);
        } else if (running.length) {
          this.liveMeetings.set(running);
          this.mode.set('pick');
        } else {
          this.mode.set('none');
        }
      });
  }

  /** Load a vote, its delegation state and where it takes place. */
  private load(id: string, force = false): void {
    if (!force && id === this.requested) return;
    this.requested = id;
    this.api.getVote(id, { quiet: true }).subscribe({
      next: (vote) => {
        const isNew = vote.id !== this.loaded()?.id;
        this.loaded.set(vote);
        if (!isNew) return;
        this.delegation.set(null);
        this.delegations.voteStatus(id).subscribe({
          next: (status) => this.delegation.set(status),
          error: () => {},
        });
        loadVoteContext(this.api, vote.meetingId, vote.agendaItemId).subscribe((ctx) =>
          this.context.set(ctx),
        );
      },
      error: () => {},
    });
  }

  private reload(): void {
    const id = this.loaded()?.id;
    if (id) this.load(id, true);
  }
}
