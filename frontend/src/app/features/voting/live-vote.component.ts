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
 * the server answers a second cast with `error: already_voted`.
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

  readonly notEligible = computed(
    () => this.errorCode() === 'not_eligible' || this.canVote() === false,
  );
  /** The server refused a second cast: a ballot never changes. */
  readonly alreadyVoted = computed(() => this.errorCode() === 'already_voted');
  /** The own ballot is cast (or the server says so). The options lock. */
  readonly locked = computed(() => this.myChoice() !== null || this.alreadyVoted());
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
        next: (meeting) => this.canVote.set(meeting.canVote === true),
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
