import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { ProblemDetail, Vote } from '@core/api/models';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { DialogComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { VoteBarsComponent } from './vote-bars.component';

type Phase = 'loading' | 'error' | 'ready';

/** 409 codes of `DELETE /votes/{id}`, mapped to their explanation. */
const DELETE_CONFLICT_KEYS: Record<string, TranslationKey> = {
  vote_meeting_bound: 'voting.delete.conflict.meetingBound',
  vote_not_draft: 'voting.delete.conflict.notDraft',
  vote_has_ballots: 'voting.delete.conflict.hasBallots',
};

/**
 * Vote UI: load a single vote and cast a ballot.
 *
 * - `open`: the user selects an option. A ballot never changes after the cast, so the
 *   choice locks. `myBallot` and `representedCast` of the server restore the lock on
 *   a reload. A 409 `already_voted` locks it too.
 * - `closed`: a read-only view with the result.
 * - not eligible: a notice replaces the cast controls.
 *
 * The server flags `canCast` and `canManage` decide the controls. A missing `canCast`
 * or a server 403 marks the user as not eligible. RBAC stays authoritative on the
 * server. A `secret` vote shows no counts while it is open.
 */
@Component({
  selector: 'app-vote-cast',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    DialogComponent,
    PageHeaderComponent,
    TranslatePipe,
    VoteBarsComponent,
  ],
  templateUrl: './vote-cast.component.html',
  styleUrl: './vote-cast.component.scss',
})
export class VoteCastComponent {
  private readonly api = inject(ApiClient);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly phase = signal<Phase>('loading');
  readonly vote = signal<Vote | null>(null);
  readonly myChoice = signal<string | null>(null);
  /** The own ballot is cast. A secret vote has no known choice, only this flag. */
  readonly ownCast = signal(false);
  /** The choice for the proxy ballot. It goes to the server as a separate submission. */
  readonly proxyChoice = signal<string | null>(null);
  /** The proxy ballot is cast (also known from the server after a reload). */
  readonly proxyCast = signal(false);
  readonly submitting = signal(false);
  readonly notEligible = signal(false);
  /** Delegation state: the user handed the voting right over, or the user acts as a proxy. */
  readonly delegation = signal<VoteDelegationStatus | null>(null);

  readonly isOpen = computed(() => this.vote()?.status === 'open');
  readonly isClosed = computed(() => this.vote()?.status === 'closed');
  readonly options = computed(() => this.vote()?.config.options ?? []);
  readonly secret = computed(() => Boolean(this.vote()?.secret));
  readonly showBars = computed(() => Boolean(this.vote()) && (!this.secret() || this.isClosed()));
  /** A ballot never changes after the cast (the server answers 409 `already_voted`). */
  readonly locked = computed(() => this.ownCast());
  readonly proxyLocked = computed(() => this.proxyCast());

  // Delete a standalone vote. The route accepts it only while the vote is a
  // draft with no ballots, and it refuses a meeting-bound vote: that one is
  // deleted through its meeting. `cancel` stays the path for an open vote.
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly canDelete = computed(() => {
    const vote = this.vote();
    return !!vote && vote.status === 'draft' && !vote.meetingId && vote.canManage === true;
  });

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
  /** Page-header subtitle: the majority rule, plus the quorum when the vote has one. */
  readonly subtitle = computed(() => {
    const majority = this.i18n.translate(this.majorityKey());
    const quorum = this.vote()?.config.quorum;
    if (!quorum) return majority;
    const unit = quorum.type === 'percent' ? '%' : '';
    return `${majority} · ${this.i18n.translate('vote.tally.quorum')} ${quorum.value}${unit}`;
  });

  constructor() {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.phase.set('error');
      return;
    }
    // The delegation status explains a 403 (the user handed the voting right over) or it
    // unlocks the separate proxy block. Important: `exercising` does not free the own
    // vote. An external substitute can cast the proxy ballot only. The two submissions
    // stay separate.
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
        this.ownCast.set(vote.myBallot?.cast === true);
        this.myChoice.set(vote.myBallot?.choice ?? null);
        this.proxyCast.set(vote.representedCast === true);
        // Eligibility UX: the server flag `canCast` decides. The server stays
        // authoritative on the cast.
        if (vote.canCast !== true) this.notEligible.set(true);
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

  /**
   * Delete the vote for good (`DELETE /votes/{id}`).
   *
   * A 409 is a real state, not a generic failure: the vote opened, it already
   * holds ballots, or it belongs to a meeting. Name the reason and reload, so
   * the page shows the state the server has.
   */
  doDelete(): void {
    const vote = this.vote();
    if (!vote || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteVote(vote.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        this.toast.success(this.i18n.translate('voting.delete.done'));
        // The vote is gone, so this route 404s from now on. Go back to the
        // application that carried it, or to the vote overview without one.
        void this.router.navigate(
          vote.applicationId ? ['/applications', vote.applicationId] : ['/voting'],
        );
      },
      error: (err: { status?: number; error?: ProblemDetail }) => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        if (err.status === 409) {
          const key = DELETE_CONFLICT_KEYS[err.error?.code ?? ''] ?? 'voting.delete.conflict.other';
          this.toast.error(this.i18n.translate(key));
          this.api.getVote(vote.id, { quiet: true }).subscribe((v) => this.vote.set(v));
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

  cast(choice: string, asDelegation = false): void {
    const vote = this.vote();
    if (!vote || this.submitting() || !this.isOpen()) return;
    if (asDelegation) {
      if (!this.delegation()?.exercising || this.proxyLocked()) return;
    } else if (this.notEligible() || this.locked()) {
      return;
    }

    this.submitting.set(true);
    this.api.castBallot(vote.id, choice, asDelegation).subscribe({
      next: () => {
        this.markCast(asDelegation, choice);
        this.submitting.set(false);
        this.toast.success(this.i18n.translate('voting.cast.toast.cast'));
        // Reload the current tally from the server. Do not guess it optimistically.
        this.api.getVote(vote.id, { quiet: true }).subscribe((v) => this.vote.set(v));
      },
      error: (err: { status?: number; error?: ProblemDetail }) => {
        this.submitting.set(false);
        if (err.status === 403) {
          if (!asDelegation) this.notEligible.set(true);
          this.toast.error(this.i18n.translate('voting.cast.notEligible'));
        } else if (err.status === 409) {
          // `already_voted`: the ballot exists (another tab, the live page). Lock it.
          const already = err.error?.code === 'already_voted';
          if (already) this.markCast(asDelegation, null);
          this.toast.error(
            this.i18n.translate(
              already ? 'voting.cast.toast.alreadyVoted' : 'voting.cast.toast.conflict',
            ),
          );
          this.api.getVote(vote.id, { quiet: true }).subscribe((v) => this.vote.set(v));
        } else {
          this.toast.error(err.error?.detail ?? this.i18n.translate('voting.cast.toast.failed'));
        }
      },
    });
  }

  /** Lock the own or the proxy ballot. `choice` is `null` when it is not known. */
  private markCast(asDelegation: boolean, choice: string | null): void {
    if (asDelegation) {
      this.proxyCast.set(true);
      if (choice !== null) this.proxyChoice.set(choice);
    } else {
      this.ownCast.set(true);
      if (choice !== null) this.myChoice.set(choice);
    }
  }
}
