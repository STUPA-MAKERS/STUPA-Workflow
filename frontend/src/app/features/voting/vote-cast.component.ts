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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { MyBallot, ProblemDetail, Vote } from '@core/api/models';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { RowMenuComponent, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  ToastService,
} from '@stupa-makers/ui-kit';
import { RailStatusService } from '../../layout/rail-status.service';
import { mediaQuerySignal } from '../../layout/media-query';
import type { BallotCaster, BallotFailure } from './ballot/ballot.component';
import { VotePhoneHeaderComponent } from './phone-header/phone-header.component';
import { VotePanelComponent } from './vote-panel/vote-panel.component';
import { NO_CONTEXT, type VoteContext, loadVoteContext } from './vote-panel/vote-context';
import { VotingPageService } from './voting-page/voting-page.service';
import { BEAMER_FROM_PARAM } from './beamer-link.util';
import { SheetBarComponent } from '@shared/ui/sheet-bar/sheet-bar.component';

type Phase = 'loading' | 'error' | 'ready';

/** 409 codes of `DELETE /votes/{id}`, mapped to their explanation. */
const DELETE_CONFLICT_KEYS: Record<string, TranslationKey> = {
  vote_meeting_bound: 'voting.delete.conflict.meetingBound',
  vote_not_draft: 'voting.delete.conflict.notDraft',
  vote_has_ballots: 'voting.delete.conflict.hasBallots',
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
 * - A ballot never changes after the cast (O11). `myBallot` and `representedCast` of
 *   the server restore the lock on a reload; a 409 `already_voted` locks it too. After a
 *   cast the pane stays on the vote and tells the list, so the row reads "Abgestimmt".
 * - The delegation state explains a voting right that the person handed over, or it
 *   adds the row "Als Vertretung für <name>" (cast with `asDelegation`).
 * - A meeting vote follows its meeting over the WebSocket while it is a draft or open:
 *   the turnout grows with each ballot, an open or a close reads the vote again, so the
 *   result shows as the server has it, and a cancel shows the cancelled vote.
 * - A meeting vote names its meeting and agenda item ("34. Sitzung · TOP 3") and links
 *   the beamer for a person who may run the meeting. A vote without a meeting links its
 *   application, and a draft of it can be deleted.
 * - A phone gets the layout of board Telefon-Abstimmen: back to the list,
 *   "Abstimmung", the meeting line as a link to the meeting ("Antrag öffnen" for a vote
 *   without a meeting), and the button bar of the ballot pinned at the bottom.
 * - The route reuses the component from one vote to the next, so the pane loads again
 *   on each change of `:id`.
 */
@Component({
  selector: 'app-vote-cast',
  // Side by side the sheet fills the pane and scrolls inside itself.
  host: { '[class.vc-host--split]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SheetBarComponent,
    RouterLink,
    ButtonComponent,
    DialogComponent,
    EmptyStateComponent,
    IconComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    TranslatePipe,
    VotePanelComponent,
    VotePhoneHeaderComponent,
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
  private readonly railStatus = inject(RailStatusService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly liveVotes = inject(LiveVoteService);
  /** The list page around the pane. The pane also works without it (a test). */
  private readonly page = inject(VotingPageService, { optional: true });

  readonly phone = mediaQuerySignal(MEDIA.phone);
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

  // Delete a standalone vote. The route accepts it only while the vote is a draft with
  // no ballots, and it refuses a meeting-bound vote: that one goes through its meeting.
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly canDelete = computed(() => {
    const vote = this.loaded();
    return !!vote && vote.status === 'draft' && !vote.meetingId && vote.canManage === true;
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
      return this.i18n.translate('voting.cast.delegation.blocked', { name: d.delegatedToName || '?' });
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
    return allowed ? ['/voting/beamer', meetingId] : null;
  });

  /** The line at the top of the sheet: the gremium of the meeting, else of the list row. */
  readonly sheetMeta = computed(() => {
    const fromMeeting = this.context().meeting?.gremiumName;
    if (fromMeeting) return fromMeeting;
    const id = this.loaded()?.id;
    return (id && this.page?.gremiumNames().get(id)) || null;
  });

  /**
   * The line below the phone title. A meeting vote names its meeting and agenda item
   * ("TOP 3 · 34. Sitzung des Studierendenparlaments"); a vote without a meeting reads
   * "Antrag öffnen". The way back goes to the list, so this line is the way to the
   * meeting or to the application (`phoneSubtitleLink`).
   */
  readonly phoneSubtitle = computed<string | null>(() => {
    const vote = this.loaded();
    const { meeting, position } = this.context();
    if (meeting) {
      return position === null
        ? meeting.title
        : this.i18n.translate('voting.panel.wherePhone', { meeting: meeting.title, n: position });
    }
    if (vote && !vote.meetingId && vote.applicationId) {
      return this.i18n.translate('voting.panel.application');
    }
    return null;
  });

  /** The target of the phone line: the meeting, else the application, of the vote. */
  readonly phoneSubtitleLink = computed<string[] | null>(() => {
    const vote = this.loaded();
    const meeting = this.context().meeting;
    if (meeting) return ['/meetings', meeting.id];
    if (vote && !vote.meetingId && vote.applicationId) return ['/applications', vote.applicationId];
    return null;
  });

  /** The ⋮ menu. The template shows it only while `canDelete` holds. */
  readonly menu = computed<RowMenuSection[]>(() => [
    {
      items: [
        {
          id: 'delete',
          label: this.i18n.translate('voting.delete.action'),
          icon: 'trash',
          danger: true,
        },
      ],
    },
  ]);

  /** Send one ballot. The ballot component locks the row and reports the outcome. */
  readonly caster: BallotCaster = (choice, asDelegation) =>
    this.api.castBallot(this.loaded()?.id ?? '', choice, asDelegation);

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => this.open(pm.get('id')));
    this.followLive();
    // Tell the list which vote is shown, so that it can follow its meeting.
    effect(() => {
      const vote = this.loaded();
      const shown = vote
        ? { id: vote.id, meetingId: vote.meetingId ?? null, status: vote.status }
        : null;
      untracked(() => this.page?.shown.set(shown));
    });
  }

  ngOnDestroy(): void {
    this.ownSession?.close();
    this.page?.shown.set(null);
  }

  goBeamer(): void {
    const link = this.beamerLink();
    if (!link) return;
    void this.router.navigate(link, { queryParams: { [BEAMER_FROM_PARAM]: this.router.url } });
  }

  onMenu(id: string): void {
    if (id === 'delete') this.confirmDelete.set(true);
  }

  /** The ballot says "Danke! Deine Stimme: Ja" itself, so no toast repeats it. */
  onCastDone(): void {
    // A ballot can close a task; the count in the navigation follows.
    this.railStatus.refresh();
    const id = this.loaded()?.id;
    if (id) this.page?.notify({ id, kind: 'cast' });
    this.reload();
  }

  onCastFailed(failure: BallotFailure): void {
    const { error } = failure;
    if (error.status === 403) {
      // The server refused this row. Hide it, so that the person cannot send the same
      // ballot into the same 403, and read the state again: the voting right can have
      // moved after the page loaded.
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
        // The vote is gone, so this route 404s from now on. The row leaves the list and
        // the pane goes back to the list with its filters.
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
    this.loadDelegation(id);
    this.api.getVote(id).subscribe({
      next: (vote) => {
        if (this.currentId !== id) return;
        this.loaded.set(vote);
        if (vote.canCast !== true) this.notEligible.set(true);
        this.phase.set('ready');
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

    let lastOpened: string | null = null;
    effect(() => {
      const session = this.session();
      const opened = session?.openVote()?.voteId ?? null;
      const closed = session?.result()?.voteId ?? null;
      untracked(() => {
        const vote = this.loaded();
        const before = lastOpened;
        lastOpened = opened;
        if (!vote) return;
        if (vote.status === 'draft' && opened === vote.id) this.reload();
        else if (vote.status === 'open' && closed === vote.id) this.reload();
        else if (vote.status === 'open' && before === vote.id && opened !== vote.id) this.reload();
      });
    });
  }

  /**
   * Read the delegation status. It explains a handed-over voting right, or it unlocks
   * the proxy row. `exercising` does not free the own ballot: an external substitute
   * casts the represented ballot only.
   */
  private loadDelegation(id: string): void {
    this.delegations.voteStatus(id).subscribe({
      next: (status) => {
        if (this.currentId !== id) return;
        this.delegation.set(status);
        if (status.blocked) this.notEligible.set(true);
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
