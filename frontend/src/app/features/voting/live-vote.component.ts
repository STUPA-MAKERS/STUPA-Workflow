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
import { AuthService } from '@core/auth/auth.service';
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
 * `error: not_eligible`, or when the frontend permission is missing.
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
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);

  private readonly session: LiveVoteSession;
  readonly myChoice = signal<string | null>(null);

  readonly connection;
  readonly vote;
  readonly tally;
  readonly result;
  private readonly errorCode;

  readonly notEligible = computed(
    () => this.errorCode() === 'not_eligible' || !this.auth.can('vote.cast'),
  );
  readonly resultKey = computed(
    () => `vote.result.${this.result()?.result ?? 'tie'}` as TranslationKey,
  );

  constructor() {
    const meetingId = this.route.snapshot.paramMap.get('id') ?? 'demo';
    this.session = this.live.open(meetingId);
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
  }

  optionLabel(option: string): string {
    const key = `vote.option.${option}` as TranslationKey;
    const label = this.i18n.translate(key);
    return label === key ? option : label;
  }

  cast(choice: string): void {
    if (this.notEligible() || this.result()) return;
    this.session.cast(choice);
    this.myChoice.set(choice);
  }

  ngOnDestroy(): void {
    this.session.close();
  }
}
