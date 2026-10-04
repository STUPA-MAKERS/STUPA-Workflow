import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  inject,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import { VoteBarsComponent } from './vote-bars.component';

/**
 * Beamer/projector view: read-only, large type, high contrast. It shows live
 * bars, the vote count, the quorum indicator and the result. It never shows
 * names, because the beamer stream carries aggregated counts only. It consumes
 * WS frames only. It sends `subscribe`, never `cast` (session beamer mode).
 *
 * The route has no chrome. A link back is visually hidden until it gets the focus or a
 * pointer hovers it, so the projector shows no control, but the page is never a trap.
 */
@Component({
  selector: 'app-beamer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, VoteBarsComponent],
  templateUrl: './beamer.component.html',
  styleUrl: './beamer.component.scss',
})
export class BeamerComponent implements OnDestroy {
  private readonly live = inject(LiveVoteService);
  private readonly route = inject(ActivatedRoute);
  private readonly i18n = inject(I18nService);

  private readonly session: LiveVoteSession;
  readonly connection;
  readonly vote;
  readonly tally;
  readonly result;
  /** The live vote page of the meeting, or the voting overview without a meeting. */
  readonly backLink: string;

  readonly castCount = computed(() => {
    const tally = this.tally();
    return tally ? Object.values(tally.counts).reduce((a, b) => a + b, 0) : 0;
  });
  readonly resultKey = computed(
    () => `vote.result.${this.result()?.result ?? 'tie'}` as TranslationKey,
  );

  constructor() {
    const routeId = this.route.snapshot.paramMap.get('id');
    const meetingId = routeId ?? 'demo';
    this.backLink = routeId ? `/voting/meeting/${routeId}` : '/voting';
    this.session = this.live.open(meetingId, { beamer: true });
    this.connection = this.session.connection;
    this.vote = this.session.openVote;
    this.tally = this.session.tally;
    this.result = this.session.result;
  }

  ngOnDestroy(): void {
    this.session.close();
  }
}
