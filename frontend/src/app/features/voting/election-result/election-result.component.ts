import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { switchMap } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import type { ElectionConfig, ElectionResult, Uuid, Vote, VoteResult } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SegBarComponent, type SegTone } from '@shared/ui/seg-bar/seg-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import type { StatusKind } from '@shared/status-kind.util';
import { ButtonComponent, IconComponent, ToastService } from '@stupa-makers/ui-kit';
import { errorDetail } from '../../meetings/meetings-display.util';
import {
  type ElectionBar,
  candidateNames,
  electionBars,
  electionResultLine,
  lotPending,
  runoffPending,
  seatsText,
} from '../election.util';

/**
 * The result of a personnel election (F2): one bar per candidate (best first) with the
 * tag "gewählt" or "Gleichstand", then the abstentions.
 *
 * - A tie at the seat boundary of a multi-seat election shows the runoff banner; the
 *   vote manager starts the runoff ("Stichwahl starten": create it, then open it).
 * - A tie of a single seat (or in a runoff) waits for the lot; the vote manager draws
 *   it ("Los ziehen"). The server draws, records who triggered it and audits it.
 * - A drawn lot shows the note "Durch Los entschieden".
 *
 * The meeting card, the vote page and the beamer use it. The beamer never gets the
 * actions (`canManage` stays off).
 */
@Component({
  selector: 'app-election-result',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    IconComponent,
    NoteComponent,
    SegBarComponent,
    StatusTextComponent,
    TranslatePipe,
  ],
  host: {
    '[class.bars--beamer]': "variant() === 'beamer'",
  },
  templateUrl: './election-result.component.html',
  styleUrls: ['../vote-bars.component.scss', './election-result.component.scss'],
})
export class ElectionResultComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly election = input.required<ElectionConfig>();
  /** The result of the closed vote; `null` while the vote is open. */
  readonly result = input<VoteResult | string | null>(null);
  readonly electionResult = input<ElectionResult | null>(null);
  /** The counts that the server revealed (an open, not secret vote), as a fallback. */
  readonly counts = input<Readonly<Record<string, number>>>({});
  readonly variant = input<'compact' | 'beamer'>('compact');
  /** The vote id, for the actions. */
  readonly voteId = input<Uuid | null>(null);
  /** The caller may draw the lot and start the runoff (vote manager or meeting lead). */
  readonly canManage = input(false);

  /** The lot was drawn or the runoff opened: the caller reads the vote again. */
  readonly changed = output<Vote>();

  protected readonly busy = signal<'lot' | 'runoff' | null>(null);

  private readonly t = (key: TranslationKey, params?: Record<string, string | number>) =>
    this.i18n.translate(key, params);

  protected readonly bars = computed<ElectionBar[]>(() =>
    electionBars(this.election(), this.electionResult(), this.counts(), this.t),
  );
  /** All votes and abstentions: the base of the bars. */
  protected readonly total = computed(() => this.bars().reduce((sum, b) => sum + b.count, 0));

  protected readonly status = computed<{ kind: StatusKind; text: string } | null>(() => {
    const result = this.result();
    if (!result) return null;
    const er = this.electionResult();
    const kind: StatusKind =
      result === 'elected' ? 'accent' : result === 'rejected' ? 'error' : 'warn';
    const text =
      result === 'runoff'
        ? this.t('election.result.runoff')
        : electionResultLine(this.election(), result, er, this.t);
    return { kind, text };
  });

  /** "Bereits gewählt: Anna. Stichwahl um 1 Posten zwischen Ben und Cem." */
  protected readonly runoff = computed(() => {
    const er = this.electionResult();
    if (this.result() !== 'runoff' || !er?.runoff) return null;
    return {
      text: this.t('election.runoff.banner', {
        seats: seatsText(er.runoff.seats, this.t),
        names: candidateNames(this.election(), er.runoff.candidateIds).join(', '),
      }),
      pending: runoffPending(this.result(), er),
    };
  });

  /** The pending lot: "Gleichstand zwischen Anna und Ben. Das Los entscheidet." */
  protected readonly lot = computed(() => {
    const er = this.electionResult();
    if (!lotPending(this.result(), er) || !er?.lot) return null;
    return this.t('election.lot.pending', {
      names: candidateNames(this.election(), er.lot.among).join(', '),
    });
  });

  /** The drawn lot: "Durch Los entschieden: Anna". */
  protected readonly lotNote = computed(() => {
    const drawn = this.electionResult()?.lot?.drawn;
    if (!drawn) return null;
    return this.t('election.lot.note', {
      names: candidateNames(this.election(), drawn).join(', '),
    });
  });

  protected barLabel(bar: ElectionBar): string {
    return this.t('voting.bars.row', {
      option: bar.label,
      count: bar.count,
      pct: this.pct(bar),
    });
  }

  /** Ja and an elected candidate in the accent, Nein in the error colour, the
   *  abstentions grey, every other candidate in the second tone. */
  protected tone(bar: ElectionBar): SegTone {
    if (bar.id === 'abstain') return 'muted';
    if (bar.id === 'no') return 'error';
    return bar.id === 'yes' || bar.elected ? 'filled' : 'second';
  }

  protected pct(bar: ElectionBar): number {
    const total = this.total();
    return total > 0 ? Math.round((bar.count / total) * 100) : 0;
  }

  /** "Los ziehen": the server draws among the tied candidates. */
  drawLot(): void {
    const id = this.voteId();
    if (!id || this.busy()) return;
    this.busy.set('lot');
    this.api.drawElectionLot(id).subscribe({
      next: (vote) => {
        this.busy.set(null);
        this.toast.success(this.t('election.lot.drawn'));
        this.changed.emit(vote);
      },
      error: (err: unknown) => this.fail(err),
    });
  }

  /** "Stichwahl starten": create the runoff, then open it. */
  startRunoff(): void {
    const id = this.voteId();
    if (!id || this.busy()) return;
    this.busy.set('runoff');
    this.api
      .createElectionRunoff(id)
      .pipe(
        switchMap((runoff) =>
          this.api.openVote(runoff.id).pipe(switchMap(() => this.api.getVote(runoff.id))),
        ),
      )
      .subscribe({
        next: (vote) => {
          this.busy.set(null);
          this.toast.success(this.t('election.runoff.started'));
          this.changed.emit(vote);
        },
        error: (err: unknown) => this.fail(err),
      });
  }

  private fail(err: unknown): void {
    this.busy.set(null);
    const detail = errorDetail(err);
    const base = this.t('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
  }
}
