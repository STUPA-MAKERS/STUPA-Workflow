import { Injectable, Injector, computed, effect, inject, signal, untracked } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import type { Meeting, MeetingVote, MyBallot, Vote } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { RailStatusService } from '../../../layout/rail-status.service';
import type { BallotCaster, BallotFailure } from '../../voting/ballot/ballot.component';

const NOT_CAST: MyBallot = { cast: false, choice: null };

/**
 * The vote of the participant view: the vote that the card shows, the own ballot and the
 * ballot of a represented member. The participant view provides it; the vote card and
 * the dock read it.
 *
 * The view sets `meeting` and `row` (the open vote of the meeting, else the newest
 * result of the shown agenda item). The service reads the vote (`GET /votes/{id}`) and
 * the delegation state of the caller (`GET /delegations/votes/{id}/status`) each time
 * the row changes its id or its status. While the vote is open, the turnout of the row
 * (the live channel of the meeting) replaces the turnout of the read.
 *
 * The rules are the ones of the vote page: the own row needs `canCast`, the meeting flag
 * `canVote` and no handed-over voting right; a 403 on a cast hides the refused row. A
 * ballot never changes (O11).
 */
@Injectable()
export class ParticipantVoteService {
  private readonly api = inject(ApiClient);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  /** The rail status reads the tasks again after a ballot. Looked up on use: the shell
   *  owns it, and a page under test does not need it. */
  private readonly injector = inject(Injector);

  readonly meeting = signal<Meeting | null>(null);
  readonly row = signal<MeetingVote | null>(null);

  private readonly loaded = signal<Vote | null>(null);
  readonly delegation = signal<VoteDelegationStatus | null>(null);
  /** The server refused the own ballot (403). */
  private readonly notEligible = signal(false);
  /** The server refused the represented ballot (403). */
  private readonly proxyRefused = signal(false);
  /** The id and the status of the last read, so that one state is read once. */
  private requested: string | null = null;

  /** The vote with the newest turnout of the meeting. */
  readonly vote = computed<Vote | null>(() => {
    const v = this.loaded();
    const row = this.row();
    if (!v || !row || v.id !== row.id) return null;
    if (row.status !== 'open' || v.status !== 'open') return v;
    return {
      ...v,
      tally: {
        ...v.tally,
        voted: row.voted,
        present: row.present,
        revealed: row.revealed,
        counts: row.revealed && row.counts ? row.counts : {},
      },
    };
  });

  readonly own = computed<MyBallot | null>(() => {
    const v = this.loaded();
    if (!v || v.canCast !== true || this.notEligible()) return null;
    if (this.meeting()?.canVote === false || this.delegation()?.blocked) return null;
    return v.myBallot ?? NOT_CAST;
  });

  readonly proxyName = computed<string | null>(() => {
    const d = this.delegation();
    if (this.proxyRefused() || !d?.exercising) return null;
    return d.delegatedByName || '?';
  });

  readonly proxyCast = computed(() => this.loaded()?.representedCast === true);

  /** Why the person holds no ballot in the open vote, or `null`. */
  readonly notice = computed<string | null>(() => {
    if (this.vote()?.status !== 'open') return null;
    const d = this.delegation();
    if (d?.blocked) {
      return this.i18n.translate('voting.cast.delegation.blocked', { name: d.delegatedToName || '?' });
    }
    if (this.own() === null && this.proxyName() === null) {
      return this.i18n.translate('voting.live.notEligible');
    }
    return null;
  });

  readonly caster: BallotCaster = (choice, asDelegation) =>
    this.api.castBallot(this.loaded()?.id ?? '', choice, asDelegation);

  constructor() {
    effect(() => {
      const row = this.row();
      const key = row ? `${row.id}:${row.status}` : null;
      untracked(() => {
        if (!row) {
          this.loaded.set(null);
          this.requested = null;
        } else if (key !== this.requested) {
          this.requested = key;
          this.load(row.id);
        }
      });
    });
  }

  onCastDone(): void {
    this.injector.get(RailStatusService).refresh();
    this.reload();
  }

  onCastFailed(failure: BallotFailure): void {
    const { error } = failure;
    if (error.status === 403) {
      // `canCast` can stay true when the voting right moved after the read: hide the
      // refused row, then read the vote and the delegation state again.
      if (failure.asDelegation) this.proxyRefused.set(true);
      else this.notEligible.set(true);
      this.toast.error(this.i18n.translate('voting.cast.notEligible'));
      this.reload(true);
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

  private load(id: string): void {
    this.api.getVote(id, { quiet: true }).subscribe({
      next: (vote) => {
        const isNew = vote.id !== this.loaded()?.id;
        this.loaded.set(vote);
        if (!isNew) return;
        this.delegation.set(null);
        this.notEligible.set(false);
        this.proxyRefused.set(false);
        this.loadDelegation(id);
      },
      error: () => {},
    });
  }

  private loadDelegation(id: string): void {
    this.delegations.voteStatus(id).subscribe({
      next: (status) => {
        if (this.loaded()?.id === id) this.delegation.set(status);
      },
      error: () => {},
    });
  }

  private reload(withDelegation = false): void {
    const id = this.loaded()?.id;
    if (!id) return;
    this.load(id);
    if (withDelegation) this.loadDelegation(id);
  }
}
