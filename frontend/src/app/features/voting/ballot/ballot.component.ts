import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import type { Observable } from 'rxjs';
import { take } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NgTemplateOutlet } from '@angular/common';
import type { ElectionConfig, MyBallot, ProblemDetail } from '@core/api/models';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { voteOptionLabel } from '../../meetings/meetings-display.util';
import { electionChoiceLabel } from '../election.util';

/** The two ballots a person can hold in one vote: the own one, and the one of a member
 *  they represent. The server keeps them apart. */
export type BallotRow = 'own' | 'proxy';

/** A pick: one option, or the candidate ids of an election ballot (F2; `[]` = full
 *  abstention). */
export type BallotPick = string | readonly string[];

/**
 * Sends one ballot to the server. The observable gives one value when the server
 * accepted the ballot, and it fails with the HTTP error otherwise. The page passes
 * `ApiClient.castBallot` here.
 */
export type BallotCaster = (choice: BallotPick, asDelegation: boolean) => Observable<unknown>;

/** The error of a refused cast, as the HTTP client reports it. */
export interface BallotCastError {
  status?: number;
  error?: ProblemDetail | null;
}

/** A refused cast, for the page to report and to reload the vote. */
export interface BallotFailure {
  asDelegation: boolean;
  /** 409 `already_voted`: the ballot exists already. The row locks. */
  alreadyVoted: boolean;
  error: BallotCastError;
}

/** An accepted ballot. */
export interface BallotCast {
  choice: BallotPick;
  asDelegation: boolean;
}

const NOT_CAST: MyBallot = { cast: false, choice: null };

/**
 * The ballot of one vote, in two steps: pick Ja, Nein or Enthaltung, then confirm with
 * "Stimme abgeben: Ja". The fixed line above the button says that the ballot cannot
 * change afterwards (O11). Nothing here offers a change: once the server accepted the
 * ballot, the row locks and says "Danke! Deine Stimme: Ja".
 *
 * - A person who represents a member gets a second row "Als Vertretung für <name>". It
 *   casts with `asDelegation`, apart from the own ballot. The button acts on the row of
 *   the last pick.
 * - A secret vote never shows the choice after the cast, only that the ballot is in.
 * - The button is off while a cast runs, so a double click sends one ballot.
 * - A 409 `already_voted` (another tab, the meeting page) locks the row as well.
 * - `compact` gives the small ballot of a side column: buttons in one row.
 * - `columns` puts the rows side by side (the strip of a narrow screen).
 * - `layout="phone"` pins the button bar to the bottom of the screen (board
 *   Telefon-Abstimmen) and always names the rows.
 * - `election` (F2) turns the options into the candidates: one seat gives a radio list
 *   with a separate "Enthaltung" row; several seats give check boxes with the counter
 *   "1 von 2 Stimmen vergeben", the further boxes stay off when all votes are given, and
 *   "Ganz enthalten" picks no candidate. A free vote is an abstention, and the button
 *   names it. One candidate keeps the Ja/Nein/Enthaltung options.
 *
 * The component calls the server through `caster`; the page owns the toasts and the
 * reload (`castDone`, `castFailed`).
 */
@Component({
  selector: 'app-ballot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent, NgTemplateOutlet, TranslatePipe],
  host: {
    class: 'ballot',
    '[class.ballot--phone]': "layout() === 'phone'",
    '[class.ballot--compact]': 'compact()',
    '[class.ballot--columns]': 'columns()',
  },
  templateUrl: './ballot.component.html',
  styleUrl: './ballot.component.scss',
})
export class BallotComponent {
  private readonly i18n = inject(I18nService);
  private readonly destroyRef = inject(DestroyRef);

  /** The vote. A new id clears the picks and the local locks. */
  readonly voteId = input.required<string>();
  readonly options = input.required<readonly string[]>();
  readonly secret = input(false);
  /** The own ballot as the server knows it (`myBallot`). `null`: no own row, because
   *  the person may not cast an own ballot (no right, or handed over). */
  readonly own = input<MyBallot | null>(NOT_CAST);
  /** The name of the member the person represents. Without it there is no second row. */
  readonly proxyName = input<string | null>(null);
  /** The represented ballot as the server knows it (`representedCast`). */
  readonly proxyCast = input(false);
  readonly caster = input.required<BallotCaster>();
  readonly layout = input<'page' | 'phone'>('page');
  /**
   * The small ballot of a side column (the participant view): the own options are a
   * row of buttons like the represented ones, and the rows always carry their name.
   */
  readonly compact = input(false);
  /**
   * The ballot of a narrow strip (board Schmal-Teilnahme): the own row and the
   * represented row side by side, the confirm bar in one line below them.
   */
  readonly columns = input(false);
  /** The personnel election of the vote (F2), or `null` for a motion. */
  readonly election = input<ElectionConfig | null>(null);

  readonly castDone = output<BallotCast>();
  readonly castFailed = output<BallotFailure>();

  /** The pick of each row (step 1). */
  protected readonly picked = signal<Record<BallotRow, BallotPick | null>>({ own: null, proxy: null });

  /** The ballot picks candidates (an election with more than one candidate). */
  protected readonly candidateMode = computed(() => (this.election()?.candidates.length ?? 0) > 1);
  /** Several seats: check boxes and a counter. */
  protected readonly multiSeat = computed(() => (this.election()?.seats ?? 1) > 1);
  protected readonly seats = computed(() => this.election()?.seats ?? 1);
  /** The row the button acts on: the row of the last pick. */
  protected readonly active = signal<BallotRow>('own');
  /** The row whose ballot is on its way to the server. */
  protected readonly pending = signal<BallotRow | null>(null);
  /** Ballots of this page view, before the page reloads the vote. */
  private readonly local = signal<Record<BallotRow, MyBallot | null>>({ own: null, proxy: null });

  /** The own ballot: this page view first, then the server copy. */
  protected readonly ownState = computed<MyBallot | null>(() => {
    const own = this.own();
    return own === null ? null : (this.local().own ?? own);
  });
  protected readonly proxyState = computed<MyBallot | null>(() => {
    if (!this.proxyName()) return null;
    return this.local().proxy ?? (this.proxyCast() ? { cast: true, choice: null } : NOT_CAST);
  });

  /** Name the rows when a proxy row exists, and always on a phone (board). A lone own
   *  row needs no name. */
  protected readonly named = computed(
    () => this.layout() === 'phone' || this.compact() || this.proxyState() !== null,
  );

  /** The row the button acts on now, or `null` when every row is cast. */
  protected readonly target = computed<BallotRow | null>(() => {
    const open = (row: BallotRow) => {
      const state = row === 'own' ? this.ownState() : this.proxyState();
      return state !== null && !state.cast;
    };
    const active = this.active();
    if (open(active)) return active;
    const other: BallotRow = active === 'own' ? 'proxy' : 'own';
    return open(other) ? other : null;
  });

  /** The label of the button: "Stimme abgeben: Ja", "Für Jonas Weber abgeben: Nein". */
  protected readonly confirmLabel = computed(() => {
    const row = this.target();
    const choice = row ? this.picked()[row] : null;
    if (row === 'proxy') {
      const name = this.proxyName() ?? '';
      return choice !== null
        ? this.i18n.translate('voting.ballot.confirmProxy', { name, choice: this.choiceLabel(choice) })
        : this.i18n.translate('voting.ballot.confirmProxyEmpty', { name });
    }
    return choice !== null
      ? this.i18n.translate('voting.ballot.confirm', { choice: this.choiceLabel(choice) })
      : this.i18n.translate('voting.ballot.confirmEmpty');
  });

  /**
   * The confirm bar shows while a row is open. The strip (`columns`) shows it only once
   * the person picked an option, so the strip stays low (board Schmal-Teilnahme).
   */
  protected readonly showBar = computed(() => {
    const row = this.target();
    if (row === null) return false;
    return !this.columns() || this.picked()[row] !== null || this.pending() !== null;
  });

  protected readonly canConfirm = computed(() => {
    const row = this.target();
    return row !== null && this.picked()[row] !== null && this.pending() === null;
  });

  /** The pinned bar of the phone layout, measured to keep room for it below the rows. */
  private readonly bar = viewChild<ElementRef<HTMLElement>>('bar');
  protected readonly barHeight = signal(0);

  constructor() {
    // A new vote starts with no pick and no local lock.
    effect(() => {
      this.voteId();
      untracked(() => {
        this.picked.set({ own: null, proxy: null });
        this.local.set({ own: null, proxy: null });
        this.active.set('own');
        this.pending.set(null);
      });
    });
    effect((onCleanup) => {
      const el = this.bar()?.nativeElement;
      if (!el || typeof ResizeObserver === 'undefined') return;
      const observer = new ResizeObserver(() => this.barHeight.set(el.offsetHeight));
      observer.observe(el);
      onCleanup(() => observer.disconnect());
    });
  }

  protected label(option: string): string {
    return voteOptionLabel(option, (key) => this.i18n.translate(key));
  }

  /** The label of a pick: an option, or the candidates with the abstentions. */
  protected choiceLabel(pick: BallotPick): string {
    if (typeof pick === 'string') return this.label(pick);
    return electionChoiceLabel(this.election(), pick, (key, params) =>
      this.i18n.translate(key, params),
    );
  }

  /** The candidate ids that a row picked, or `[]`. */
  protected picks(row: BallotRow): readonly string[] {
    const pick = this.picked()[row];
    return Array.isArray(pick) ? pick : [];
  }

  /** The candidate is chosen: the pick of an open row, or the ballot of a cast row. */
  protected isPicked(row: BallotRow, id: string): boolean {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (state?.cast) return (this.castPicks(row) ?? []).includes(id);
    return this.picks(row).includes(id);
  }

  /** The row picked a full abstention (`[]`). */
  protected isAbstain(row: BallotRow): boolean {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (state?.cast) return this.castPicks(row)?.length === 0;
    const pick = this.picked()[row];
    return Array.isArray(pick) && pick.length === 0;
  }

  /** All votes of a multi-seat row are given: the further boxes stay off. */
  protected isFull(row: BallotRow): boolean {
    return this.picks(row).length >= this.seats();
  }

  /** Step 1 of an election: pick (one seat) or toggle (several seats) a candidate. */
  protected toggle(row: BallotRow, id: string): void {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (!state || state.cast || this.pending() !== null) return;
    let next: readonly string[];
    if (!this.multiSeat()) {
      next = [id];
    } else {
      const current = this.picks(row);
      if (current.includes(id)) next = current.filter((c) => c !== id);
      else if (current.length < this.seats()) next = [...current, id];
      else return;
    }
    this.picked.update((p) => ({ ...p, [row]: next }));
    this.active.set(row);
  }

  /** "Enthaltung" / "Ganz enthalten": the row picks no candidate. */
  protected abstainAll(row: BallotRow): void {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (!state || state.cast || this.pending() !== null) return;
    this.picked.update((p) => ({ ...p, [row]: [] }));
    this.active.set(row);
  }

  /** The candidate ids of a cast row, or `null` (secret, or not known). */
  private castPicks(row: BallotRow): readonly string[] | null {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (!state?.cast || this.secret()) return null;
    return state.choices ?? null;
  }

  /** Step 1: pick an option of a row. A cast row takes no pick. */
  protected pick(row: BallotRow, option: string): void {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (!state || state.cast || this.pending() !== null) return;
    this.picked.update((p) => ({ ...p, [row]: option }));
    this.active.set(row);
  }

  /** Step 2: send the pick of the target row. */
  protected confirm(): void {
    const row = this.target();
    if (row === null || this.pending() !== null) return;
    const choice = this.picked()[row];
    if (choice === null) return;
    const asDelegation = row === 'proxy';
    this.pending.set(row);
    this.caster()(choice, asDelegation)
      .pipe(take(1), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.lock(row, this.secret() ? null : choice);
          this.pending.set(null);
          this.castDone.emit({ choice, asDelegation });
        },
        error: (error: BallotCastError) => {
          this.pending.set(null);
          const alreadyVoted = error?.status === 409 && error.error?.code === 'already_voted';
          if (alreadyVoted) this.lock(row, null);
          this.castFailed.emit({ asDelegation, alreadyVoted, error: error ?? {} });
        },
      });
  }

  /** The choice to mark as cast in a row, or `null` (secret, or not known). */
  protected castChoice(row: BallotRow): BallotPick | null {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (!state?.cast || this.secret()) return null;
    return state.choices ?? state.choice;
  }

  /** The option looks chosen: the pick of an open row, or the choice of a cast row. */
  protected isOn(row: BallotRow, option: string): boolean {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (state?.cast) return state.choice === option && !this.secret();
    return this.picked()[row] === option;
  }

  private lock(row: BallotRow, choice: BallotPick | null): void {
    const ballot: MyBallot =
      typeof choice === 'string' || choice === null
        ? { cast: true, choice }
        : { cast: true, choice: null, choices: [...choice] };
    this.local.update((l) => ({ ...l, [row]: ballot }));
    this.picked.update((p) => ({ ...p, [row]: null }));
  }
}
