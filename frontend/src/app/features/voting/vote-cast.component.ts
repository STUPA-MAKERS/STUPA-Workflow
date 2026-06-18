import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { ProblemDetail, Vote } from '@core/api/models';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { ToastService } from '@shared/ui/toast/toast.service';
import { VoteBarsComponent } from './vote-bars.component';

type Phase = 'loading' | 'error' | 'ready';

/**
 * Vote-UI (flows §5, AK T-32): einzelne Abstimmung laden, Stimme abgeben.
 * - `open` → Optionen wählbar; `allowChange` erlaubt Umstimmen, sonst gesperrt.
 * - `closed` → read-only mit Ergebnis.
 * - nicht stimmberechtigt (FE-Permission **oder** Server-403) → Hinweis statt
 *   Stimmabgabe (RBAC bleibt serverseitig autoritativ, security.md §2).
 * Bei `secret` werden während der offenen Phase keine Counts gezeigt.
 */
@Component({
  selector: 'app-vote-cast',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, BadgeComponent, ButtonComponent, CardComponent, TranslatePipe, VoteBarsComponent],
  templateUrl: './vote-cast.component.html',
  styleUrl: './vote-cast.component.scss',
})
export class VoteCastComponent {
  private readonly api = inject(ApiClient);
  private readonly delegations = inject(DelegationsApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  readonly phase = signal<Phase>('loading');
  readonly vote = signal<Vote | null>(null);
  readonly myChoice = signal<string | null>(null);
  /** Eigene Wahl der VERTRETUNGS-Stimme (#delegation-rework, getrennte Abgabe). */
  readonly proxyChoice = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly notEligible = signal(false);
  /** Delegations-Sicht (#delegation-rework): Stimmrecht abgegeben / in Vertretung. */
  readonly delegation = signal<VoteDelegationStatus | null>(null);

  readonly isOpen = computed(() => this.vote()?.status === 'open');
  readonly isClosed = computed(() => this.vote()?.status === 'closed');
  readonly allowChange = computed(() => this.vote()?.config.allowChange ?? true);
  readonly options = computed(() => this.vote()?.config.options ?? []);
  readonly secret = computed(() => Boolean(this.vote()?.secret));
  /** Counts erst zeigen, wenn nicht (mehr) geheim: geschlossen oder nicht-secret. */
  readonly showBars = computed(() => Boolean(this.vote()) && (!this.secret() || this.isClosed()));
  /** Bereits abgestimmt und Änderung gesperrt → Optionen ausgrauen. */
  readonly locked = computed(() => this.myChoice() !== null && !this.allowChange());

  /** Summe aller abgegebenen Stimmen (für „x von y"). */
  readonly castCount = computed(() => {
    const tally = this.vote()?.tally;
    return tally ? Object.values(tally.counts).reduce((a, b) => a + b, 0) : 0;
  });

  readonly majorityKey = computed(
    () => `vote.majority.${this.vote()?.config.majorityRule ?? 'simple'}` as TranslationKey,
  );
  readonly resultKey = computed(
    () => `vote.result.${this.vote()?.result ?? 'tie'}` as TranslationKey,
  );

  constructor() {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.phase.set('error');
      return;
    }
    // Stimmrecht-UX: fehlt die Permission, Hinweis zeigen (Server bleibt autoritativ).
    this.notEligible.set(!this.auth.can('vote.cast'));
    // Delegations-Status (#delegation-rework): erklärt ein 403 (Stimmrecht abgegeben)
    // bzw. schaltet den separaten Vertretungs-Block frei. WICHTIG: `exercising`
    // macht NICHT die eigene Stimme frei (externe Stellvertreter dürfen nur die
    // Vertretungs-Stimme abgeben) — die zwei Abgaben sind getrennt.
    this.delegations.voteStatus(id).subscribe({
      next: (status) => {
        this.delegation.set(status);
        if (status.blocked) this.notEligible.set(true);
      },
      error: () => {},
    });
    this.api.getVote(id).subscribe({
      next: (vote) => {
        this.vote.set(vote);
        this.phase.set('ready');
      },
      error: (err: { status?: number }) => {
        if (err.status === 403) {
          this.notEligible.set(true);
          this.phase.set('ready');
        } else {
          this.phase.set('error');
        }
      },
    });
  }

  optionLabel(option: string): string {
    const key = `vote.option.${option}` as TranslationKey;
    const label = this.i18n.translate(key);
    return label === key ? option : label;
  }

  cast(choice: string, asDelegation = false): void {
    const vote = this.vote();
    if (!vote || this.submitting() || !this.isOpen()) return;
    if (asDelegation) {
      if (!this.delegation()?.exercising) return;
      if (this.proxyChoice() !== null && !this.allowChange()) return;
    } else {
      if (this.notEligible() || this.locked()) return;
      if (this.myChoice() === choice && !this.allowChange()) return;
    }

    this.submitting.set(true);
    this.api.castBallot(vote.id, choice, asDelegation).subscribe({
      next: (res) => {
        if (asDelegation) this.proxyChoice.set(choice);
        else this.myChoice.set(choice);
        this.submitting.set(false);
        this.toast.success(
          this.i18n.translate(
            res.status === 'changed' ? 'voting.cast.toast.changed' : 'voting.cast.toast.cast',
          ),
        );
        // Aktuellen Tally vom Server nachladen (kein optimistisches Raten).
        this.api.getVote(vote.id, { quiet: true }).subscribe((v) => this.vote.set(v));
      },
      error: (err: { status?: number; error?: ProblemDetail }) => {
        this.submitting.set(false);
        if (err.status === 403) {
          if (!asDelegation) this.notEligible.set(true);
          this.toast.error(this.i18n.translate('voting.cast.notEligible'));
        } else if (err.status === 409) {
          this.toast.error(this.i18n.translate('voting.cast.toast.conflict'));
          this.api.getVote(vote.id, { quiet: true }).subscribe((v) => this.vote.set(v));
        } else {
          this.toast.error(err.error?.detail ?? this.i18n.translate('voting.cast.toast.failed'));
        }
      },
    });
  }
}
