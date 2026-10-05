import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { MyBallot, ProblemDetail, Vote } from '@core/api/models';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { RowMenuComponent, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
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

type Phase = 'loading' | 'error' | 'ready';

/** 409 codes of `DELETE /votes/{id}`, mapped to their explanation. */
const DELETE_CONFLICT_KEYS: Record<string, TranslationKey> = {
  vote_meeting_bound: 'voting.delete.conflict.meetingBound',
  vote_not_draft: 'voting.delete.conflict.notDraft',
  vote_has_ballots: 'voting.delete.conflict.hasBallots',
};

const NOT_CAST: MyBallot = { cast: false, choice: null };

/**
 * One vote (`/voting/vote/:id`, boards Arbeit-Abstimmungen and Telefon-Abstimmen): the
 * page "Abstimmungen" with the vote as a card, the two-step ballot, the turnout and the
 * result.
 *
 * - The server flags decide the controls: `canCast` gives the own ballot, `canManage`
 *   the delete. A 403 on the load or on an own cast marks the person as not eligible.
 * - A ballot never changes after the cast (O11). `myBallot` and `representedCast` of
 *   the server restore the lock on a reload; a 409 `already_voted` locks it too.
 * - The delegation state explains a voting right that the person handed over, or it
 *   adds the row "Als Vertretung für <name>" (cast with `asDelegation`).
 * - A meeting vote names its meeting and agenda item ("34. Sitzung · TOP 3") and links
 *   the beamer for a person who may run the meeting. A vote without a meeting stays as
 *   it was: it links its application, and a draft of it can be deleted.
 * - A phone gets the layout of board Telefon-Abstimmen: back, "Abstimmung", the meeting
 *   line, and the button bar of the ballot pinned at the bottom.
 */
@Component({
  selector: 'app-vote-cast',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    PageHeaderComponent,
    RowMenuComponent,
    TranslatePipe,
    VotePanelComponent,
    VotePhoneHeaderComponent,
  ],
  templateUrl: './vote-cast.component.html',
  styleUrl: './vote-cast.component.scss',
})
export class VoteCastComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly railStatus = inject(RailStatusService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly phone = mediaQuerySignal(MEDIA.phone);
  readonly phase = signal<Phase>('loading');
  readonly vote = signal<Vote | null>(null);
  readonly context = signal<VoteContext>(NO_CONTEXT);
  /** The person may not cast an own ballot (server flag, a 403, a handed-over right). */
  readonly notEligible = signal(false);
  /** Delegation state: the person handed the voting right over, or acts as a proxy. */
  readonly delegation = signal<VoteDelegationStatus | null>(null);

  // Delete a standalone vote. The route accepts it only while the vote is a draft with
  // no ballots, and it refuses a meeting-bound vote: that one goes through its meeting.
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly canDelete = computed(() => {
    const vote = this.vote();
    return !!vote && vote.status === 'draft' && !vote.meetingId && vote.canManage === true;
  });

  /** The own ballot for the ballot, or `null` without an own voting right. */
  readonly own = computed<MyBallot | null>(() => {
    const vote = this.vote();
    if (!vote || this.notEligible() || vote.canCast !== true) return null;
    return vote.myBallot ?? NOT_CAST;
  });
  /** The member the person represents in this vote, or `null`. */
  readonly proxyName = computed(() => {
    const d = this.delegation();
    return d?.exercising ? d.delegatedByName || '?' : null;
  });
  readonly proxyCast = computed(() => this.vote()?.representedCast === true);

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
    const meetingId = this.vote()?.meetingId;
    if (!meetingId) return null;
    const gremiumId = this.context().meeting?.gremiumId;
    const allowed = gremiumId
      ? this.auth.canInGremium(gremiumId, 'session.manage')
      : this.auth.canInAnyGremium('session.manage');
    return allowed ? ['/voting/beamer', meetingId] : null;
  });

  /** The way back of the phone header: the meeting, the application or the overview. */
  readonly backLink = computed<string[]>(() => {
    const v = this.vote();
    if (v?.meetingId) return ['/meetings', v.meetingId];
    if (v?.applicationId) return ['/applications', v.applicationId];
    return ['/voting'];
  });

  /** The line below the phone title: "TOP 3 · 34. Sitzung des Studierendenparlaments". */
  readonly phoneSubtitle = computed<string | null>(() => {
    const { meeting, position } = this.context();
    if (!meeting) return null;
    return position === null
      ? meeting.title
      : this.i18n.translate('voting.panel.wherePhone', { meeting: meeting.title, n: position });
  });

  readonly menu = computed<RowMenuSection[]>(() =>
    this.canDelete()
      ? [
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
        ]
      : [],
  );

  /** Send one ballot. The ballot component locks the row and reports the outcome. */
  readonly caster: BallotCaster = (choice, asDelegation) =>
    this.api.castBallot(this.vote()?.id ?? '', choice, asDelegation);

  constructor() {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.phase.set('error');
      return;
    }
    // The delegation status explains a handed-over voting right, or it unlocks the
    // proxy row. `exercising` does not free the own ballot: an external substitute casts
    // the represented ballot only.
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
        if (vote.canCast !== true) this.notEligible.set(true);
        this.phase.set('ready');
        loadVoteContext(this.api, vote.meetingId, vote.agendaItemId).subscribe((ctx) =>
          this.context.set(ctx),
        );
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

  goBeamer(): void {
    const link = this.beamerLink();
    if (link) void this.router.navigate(link);
  }

  onMenu(id: string): void {
    if (id === 'delete') this.confirmDelete.set(true);
  }

  /** The ballot says "Danke! Deine Stimme: Ja" itself, so no toast repeats it. */
  onCastDone(): void {
    // A ballot can close a task; the count in the navigation follows.
    this.railStatus.refresh();
    this.reload();
  }

  onCastFailed(failure: BallotFailure): void {
    const { error } = failure;
    if (error.status === 403) {
      if (!failure.asDelegation) this.notEligible.set(true);
      this.toast.error(this.i18n.translate('voting.cast.notEligible'));
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
    const vote = this.vote();
    if (!vote || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteVote(vote.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        this.toast.success(this.i18n.translate('voting.delete.done'));
        // The vote is gone, so this route 404s from now on. Go back to the application
        // that carried it, or to the vote overview without one.
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

  /** Read the vote again: the tally, the own ballot and the flags. Never guess them. */
  private reload(): void {
    const vote = this.vote();
    if (!vote) return;
    this.api.getVote(vote.id, { quiet: true }).subscribe((v) => this.vote.set(v));
  }
}
