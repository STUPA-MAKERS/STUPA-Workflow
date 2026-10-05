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
import type { MyBallot, ProblemDetail } from '@core/api/models';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { voteOptionLabel } from '../../meetings/meetings-display.util';

/** The two ballots a person can hold in one vote: the own one, and the one of a member
 *  they represent. The server keeps them apart. */
export type BallotRow = 'own' | 'proxy';

/**
 * Sends one ballot to the server. The observable gives one value when the server
 * accepted the ballot, and it fails with the HTTP error otherwise. The page passes
 * `ApiClient.castBallot` here.
 */
export type BallotCaster = (choice: string, asDelegation: boolean) => Observable<unknown>;

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
  choice: string;
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
 * - `layout="phone"` pins the button bar to the bottom of the screen (board
 *   Telefon-Abstimmen) and always names the rows.
 *
 * The component calls the server through `caster`; the page owns the toasts and the
 * reload (`castDone`, `castFailed`).
 */
@Component({
  selector: 'app-ballot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent, TranslatePipe],
  host: {
    class: 'ballot',
    '[class.ballot--phone]': "layout() === 'phone'",
    '[class.ballot--compact]': 'compact()',
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

  readonly castDone = output<BallotCast>();
  readonly castFailed = output<BallotFailure>();

  /** The pick of each row (step 1). */
  protected readonly picked = signal<Record<BallotRow, string | null>>({ own: null, proxy: null });
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
      return choice
        ? this.i18n.translate('voting.ballot.confirmProxy', { name, choice: this.label(choice) })
        : this.i18n.translate('voting.ballot.confirmProxyEmpty', { name });
    }
    return choice
      ? this.i18n.translate('voting.ballot.confirm', { choice: this.label(choice) })
      : this.i18n.translate('voting.ballot.confirmEmpty');
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
  protected castChoice(row: BallotRow): string | null {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    return state?.cast && !this.secret() ? state.choice : null;
  }

  /** The option looks chosen: the pick of an open row, or the choice of a cast row. */
  protected isOn(row: BallotRow, option: string): boolean {
    const state = row === 'own' ? this.ownState() : this.proxyState();
    if (state?.cast) return this.castChoice(row) === option;
    return this.picked()[row] === option;
  }

  private lock(row: BallotRow, choice: string | null): void {
    this.local.update((l) => ({ ...l, [row]: { cast: true, choice } }));
    this.picked.update((p) => ({ ...p, [row]: null }));
  }
}
