import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  inject,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import { VoteBarsComponent } from './vote-bars.component';

/**
 * Beamer-/Projektor-Ansicht (AK T-32): read-only, großschriftig, hochkontrast.
 * Zeigt Live-Balken, Stimmenzahl, Quorum-Indikator und Ergebnis — **nie** Namen
 * (Beamer-Stream liefert nur aggregierte Counts, api.md §4). Verbraucht
 * ausschließlich WS-Frames; sendet `subscribe`/nie `cast` (Session-Beamer-Modus).
 */
@Component({
  selector: 'app-beamer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, VoteBarsComponent],
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

  readonly castCount = computed(() => {
    const tally = this.tally();
    return tally ? Object.values(tally.counts).reduce((a, b) => a + b, 0) : 0;
  });
  readonly resultKey = computed(
    () => `vote.result.${this.result()?.result ?? 'tie'}` as TranslationKey,
  );

  constructor() {
    const meetingId = this.route.snapshot.paramMap.get('id') ?? 'demo';
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
