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
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { VoteBarsComponent } from './vote-bars.component';

/**
 * Mobiles Live-Vote (AK T-32): per WebSocket (api.md §4) freischalten → casten →
 * Ergebnis. Daumen-Bedienung (große Touch-Ziele), Reconnect-Banner bei
 * Verbindungsverlust (Session resynct via `subscribe`). Nicht stimmberechtigt
 * (Server-`error: not_eligible` **oder** fehlende FE-Permission) → Hinweis.
 */
@Component({
  selector: 'app-live-vote',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, BadgeComponent, ButtonComponent, TranslatePipe, VoteBarsComponent],
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

    // Neue Abstimmung → eigene Wahl zurücksetzen.
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
