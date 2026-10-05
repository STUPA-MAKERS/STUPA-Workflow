import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { type DelegationSubstitute, DelegationsApiService } from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AvatarComponent, SkeletonComponent } from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { Subject, Subscription, catchError, debounceTime, of, switchMap } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal } from '../admin.models';

/** A member of the gremium: a choice of "Vertritt". */
export interface PoolMember {
  id: string;
  name: string;
}

/** The time after the last key press until the person search runs, in ms. */
const SEARCH_DEBOUNCE = 250;
/** The most persons the search shows. */
const SEARCH_LIMIT = 8;

/**
 * The substitute pool of one gremium: the single entries (boards Admin-Vertretung and
 * Admin-Gremium-Mitglieder, "Einzelne Einträge").
 *
 * A delegation to a pool substitute has no lead time and stays possible until the
 * meeting starts, also for a person who is not a member. An entry represents every
 * member or one member. The page header of the section takes projected controls
 * (`[poolActions]`, the gremium chip of the delegations page). Without `members` the
 * component loads the members of the gremium itself.
 *
 * The server checks the rights: `admin.delegations` or `session.manage` in the gremium.
 */
@Component({
  selector: 'app-substitute-pool',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    AvatarComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SelectComponent,
    SkeletonComponent,
  ],
  templateUrl: './substitute-pool.component.html',
  styleUrl: './substitute-pool.component.scss',
})
export class SubstitutePoolComponent {
  private readonly api = inject(AdminApiService);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremiumId = input.required<Uuid>();
  /** The members of the gremium. `null`: the component loads them. */
  readonly members = input<readonly PoolMember[] | null>(null);

  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  protected readonly entries = signal<DelegationSubstitute[]>([]);
  private readonly loadedMembers = signal<PoolMember[]>([]);
  protected readonly memberList = computed(() => this.members() ?? this.loadedMembers());
  /** The ids of the entries with a delete in flight. */
  protected readonly removing = signal<ReadonlySet<string>>(new Set());

  // --- add dialog -------------------------------------------------------------
  protected readonly addOpen = signal(false);
  protected readonly query = signal('');
  protected readonly candidates = signal<AdminPrincipal[]>([]);
  protected readonly searching = signal(false);
  protected readonly selected = signal<AdminPrincipal | null>(null);
  /** An empty value makes a gremium-wide entry that represents every member. */
  protected readonly memberId = signal('');
  protected readonly adding = signal(false);
  protected readonly addError = signal('');

  protected readonly memberOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.substitutes.allMembers') },
    ...this.memberList().map((m) => ({ value: m.id, label: m.name })),
  ]);

  private readonly search$ = new Subject<string>();
  private loads?: Subscription;

  constructor() {
    effect(() => {
      const id = this.gremiumId();
      const own = this.members() === null;
      untracked(() => this.load(id, own));
    });
    const sub = this.search$
      .pipe(
        debounceTime(SEARCH_DEBOUNCE),
        // A failed search shows no persons; the next key press searches again.
        switchMap((q) =>
          this.api.listPrincipals(q).pipe(catchError(() => of([] as AdminPrincipal[]))),
        ),
      )
      .subscribe((list) => {
        this.searching.set(false);
        this.candidates.set(list.filter((p) => p.active !== false).slice(0, SEARCH_LIMIT));
      });
    inject(DestroyRef).onDestroy(() => {
      sub.unsubscribe();
      this.loads?.unsubscribe();
    });
  }

  private load(id: Uuid, ownMembers: boolean): void {
    this.loads?.unsubscribe();
    this.loads = new Subscription();
    this.loading.set(true);
    this.failed.set(false);
    this.loads.add(
      this.delegations.substitutes(id).subscribe({
        next: (list) => {
          this.entries.set(list);
          this.loading.set(false);
        },
        error: () => {
          this.entries.set([]);
          this.failed.set(true);
          this.loading.set(false);
        },
      }),
    );
    if (ownMembers) {
      this.loads.add(
        this.api.listGremiumMemberships(id).subscribe({
          next: (rows) => {
            const seen = new Set<string>();
            const list: PoolMember[] = [];
            for (const m of rows) {
              if (seen.has(m.principalId)) continue;
              seen.add(m.principalId);
              list.push({
                id: m.principalId,
                name:
                  m.displayName || m.email || this.i18n.translate('admin.gremien.unknownMember'),
              });
            }
            this.loadedMembers.set(list.sort((a, b) => a.name.localeCompare(b.name)));
          },
          error: () => this.loadedMembers.set([]),
        }),
      );
    }
  }

  protected entryName(s: DelegationSubstitute): string {
    return s.substituteName || this.i18n.translate('admin.gremien.unknownMember');
  }

  protected memberName(s: DelegationSubstitute): string | null {
    if (!s.memberId) return null;
    return s.memberName || this.memberList().find((m) => m.id === s.memberId)?.name || '—';
  }

  // --- add ----------------------------------------------------------------------

  protected openAdd(): void {
    this.query.set('');
    this.selected.set(null);
    this.candidates.set([]);
    this.memberId.set('');
    this.addError.set('');
    this.addOpen.set(true);
  }

  protected onSearch(q: string): void {
    this.query.set(q);
    if (this.selected() && q !== this.label(this.selected()!)) this.selected.set(null);
    if (q.trim()) {
      // "Keine Person gefunden" waits for the answer, not only for the debounce.
      this.searching.set(true);
      this.search$.next(q.trim());
    } else {
      this.searching.set(false);
      this.candidates.set([]);
    }
  }

  protected label(p: AdminPrincipal): string {
    return p.displayName || p.email || p.sub;
  }

  protected pick(p: AdminPrincipal): void {
    this.selected.set(p);
    this.query.set(this.label(p));
    this.candidates.set([]);
  }

  protected add(): void {
    const s = this.selected();
    if (!s || this.adding()) return;
    this.adding.set(true);
    this.addError.set('');
    this.delegations
      .addSubstitute({
        gremiumId: this.gremiumId(),
        memberId: this.memberId() ? (this.memberId() as Uuid) : null,
        substituteId: s.id,
      })
      .subscribe({
        next: (row) => {
          this.adding.set(false);
          this.addOpen.set(false);
          this.entries.update((list) => [...list, row]);
          this.toast.success(this.i18n.translate('admin.substitutes.added'));
        },
        error: (err: { status?: number }) => {
          this.adding.set(false);
          this.addError.set(
            this.i18n.translate(
              err.status === 409
                ? 'admin.substitutes.duplicate'
                : err.status === 422
                  ? 'admin.substitutes.invalid'
                  : 'admin.substitutes.failed',
            ),
          );
        },
      });
  }

  protected remove(s: DelegationSubstitute): void {
    if (this.removing().has(s.id)) return;
    this.removing.update((r) => new Set(r).add(s.id));
    this.delegations.removeSubstitute(s.id).subscribe({
      next: () => {
        this.done(s.id);
        this.entries.update((list) => list.filter((x) => x.id !== s.id));
        this.toast.success(this.i18n.translate('admin.substitutes.removed'));
      },
      error: () => {
        this.done(s.id);
        this.toast.error(this.i18n.translate('admin.substitutes.failed'));
      },
    });
  }

  private done(id: string): void {
    this.removing.update((r) => {
      const next = new Set(r);
      next.delete(id);
      return next;
    });
  }
}
