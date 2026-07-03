import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { ProblemDetail, Vote } from '@core/api/models';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { VoteBarsComponent } from './vote-bars.component';

type Phase = 'loading' | 'error' | 'ready';

/**
 * Vote UI: load a single vote and cast a ballot.
 * - `open` → options selectable; `allowChange` allows re-voting, else locked.
 * - `closed` → read-only with the result.
 * - not eligible (FE permission or server 403) → notice instead of casting
 *   (RBAC stays authoritative server-side).
 * With `secret`, no counts are shown during the open phase.
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
  /** Own choice for the PROXY ballot (separate submission). */
  readonly proxyChoice = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly notEligible = signal(false);
  /** Delegation view: voting right handed over / acting as proxy. */
  readonly delegation = signal<VoteDelegationStatus | null>(null);

  readonly isOpen = computed(() => this.vote()?.status === 'open');
  readonly isClosed = computed(() => this.vote()?.status === 'closed');
  readonly allowChange = computed(() => this.vote()?.config.allowChange ?? true);
  readonly options = computed(() => this.vote()?.config.options ?? []);
  readonly secret = computed(() => Boolean(this.vote()?.secret));
  /** Show counts only once no longer secret: closed or non-secret. */
  readonly showBars = computed(() => Boolean(this.vote()) && (!this.secret() || this.isClosed()));
  /** Already voted and change locked → grey out the options. */
  readonly locked = computed(() => this.myChoice() !== null && !this.allowChange());

  /** Sum of all cast votes (for "x of y"). */
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
    // Eligibility UX: if the permission is missing, show a notice (server stays authoritative).
    this.notEligible.set(!this.auth.can('vote.cast'));
    // Delegation status: explains a 403 (voting right handed over) or unlocks the
    // separate proxy block. IMPORTANT: `exercising` does NOT free one's own vote
    // (external substitutes may only cast the proxy ballot) — the two submissions
    // are separate.
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
        // Reload the current tally from the server (no optimistic guessing).
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
