import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { MyBallot } from '@core/api/models';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { VoteBarsComponent } from './vote-bars.component';

/**
 * Mobile live vote: unlock over WebSocket → cast → result. The layout is
 * thumb-friendly with large touch targets. A reconnect banner appears on
 * connection loss, and the session resyncs with `subscribe`. A viewer that
 * cannot vote gets a notice. That happens when the server sends
 * `error: not_eligible`, or when the meeting reports `canVote: false`.
 *
 * A ballot never changes after the cast. The options lock after the first tap, and
 * the server answers a second cast with `error: already_voted`. After a reload the
 * `myBallot` of the meeting votes restores the lock: an open vote shows the own choice,
 * and a secret vote shows only that the ballot is cast.
 */
@Component({
  selector: 'app-live-vote',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    BadgeComponent,
    ButtonComponent,
    PageHeaderComponent,
    TranslatePipe,
    VoteBarsComponent,
  ],
  templateUrl: './live-vote.component.html',
  styleUrl: './live-vote.component.scss',
})
export class LiveVoteComponent implements OnDestroy {
  private readonly live = inject(LiveVoteService);
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);

  private readonly session: LiveVoteSession;
  readonly myChoice = signal<string | null>(null);

  readonly connection;
  readonly vote;
  readonly tally;
  readonly result;
  private readonly errorCode;
  /** The `canVote` flag of the meeting. `null` until the meeting loads. The server
   *  sets it from the gremium `vote.cast` or a voting delegation for this meeting. */
  private readonly canVote = signal<boolean | null>(null);
  /** The own ballots from the meeting load, by vote id. */
  private readonly ballots = signal<ReadonlyMap<string, MyBallot>>(new Map());
  /** The own ballot of the open vote as the server knows it. `null` if unknown. */
  private readonly serverBallot = computed<MyBallot | null>(() => {
    const id = this.vote()?.voteId;
    return id ? (this.ballots().get(id) ?? null) : null;
  });

  readonly notEligible = computed(
    () => this.errorCode() === 'not_eligible' || this.canVote() === false,
  );
  /** The server refused a second cast: a ballot never changes. */
  readonly alreadyVoted = computed(() => this.errorCode() === 'already_voted');
  /** The own ballot is cast (or the server says so). The options lock. */
  readonly locked = computed(
    () =>
      this.myChoice() !== null || this.alreadyVoted() || this.serverBallot()?.cast === true,
  );
  /** The choice to show as the own ballot: the tap, else the server copy (open votes). */
  readonly shownChoice = computed(() => this.myChoice() ?? this.serverBallot()?.choice ?? null);
  /** The ballot is cast, but the choice is unknown (secret vote, or a refused second cast). */
  readonly castWithoutChoice = computed(
    () => this.shownChoice() === null && (this.alreadyVoted() || this.serverBallot()?.cast === true),
  );
  readonly resultKey = computed(
    () => `vote.result.${this.result()?.result ?? 'tie'}` as TranslationKey,
  );

  constructor() {
    const routeId = this.route.snapshot.paramMap.get('id');
    const meetingId = routeId ?? 'demo';
    this.session = this.live.open(meetingId);
    if (routeId) {
      // A failed load keeps `null`: the server still refuses a cast with `not_eligible`.
      this.api.getMeeting(routeId, { quiet: true }).subscribe({
        next: (meeting) => {
          this.canVote.set(meeting.canVote === true);
          const ballots = new Map<string, MyBallot>();
          // A partial meeting (a stub or an old server) can lack `votes`.
          for (const v of meeting.votes ?? []) {
            if (v.myBallot) ballots.set(v.id, v.myBallot);
          }
          this.ballots.set(ballots);
        },
        error: () => {},
      });
    }
    this.connection = this.session.connection;
    this.vote = this.session.openVote;
    this.tally = this.session.tally;
    this.result = this.session.result;
    this.errorCode = this.session.errorCode;

    // New vote → reset own choice.
    let lastVoteId: string | null = null;
    effect(() => {
      const id = this.vote()?.voteId ?? null;
      if (id !== lastVoteId) {
        lastVoteId = id;
        this.myChoice.set(null);
      }
    });
    // A refused cast (other than `already_voted`) did not count. Free the options again.
    effect(() => {
      const code = this.errorCode();
      if (code !== null && code !== 'already_voted') this.myChoice.set(null);
    });
  }

  optionLabel(option: string): string {
    const key = `vote.option.${option}` as TranslationKey;
    const label = this.i18n.translate(key);
    return label === key ? option : label;
  }

  cast(choice: string): void {
    if (this.notEligible() || this.result() || this.locked()) return;
    this.session.cast(choice);
    this.myChoice.set(choice);
  }

  ngOnDestroy(): void {
    this.session.close();
  }
}
