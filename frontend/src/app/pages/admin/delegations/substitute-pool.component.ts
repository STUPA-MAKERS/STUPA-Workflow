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
import {
  AvatarComponent,
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  IconComponent,
  ListItemComponent,
  liveSearch,
  NoteComponent,
  RowMenuComponent,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SelectFieldComponent,
  type SelectFieldOption,
  SkeletonComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { Subscription } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { type AdminPrincipal, isActiveMembership } from '../admin.models';
import { SectionHeaderComponent } from '@shared/ui/section-header/section-header.component';
import { personLabel } from '@shared/person-label.util';

/** A member of the gremium: a choice of "Vertritt". */
export interface PoolMember {
  id: string;
  name: string;
}

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
    SectionHeaderComponent,
    NoteComponent,
    EmptyStateComponent,
    ScrollFadeDirective,
    FormsModule,
    TranslatePipe,
    AvatarComponent,
    ListItemComponent,
    SearchPillComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    RowMenuComponent,
    SelectFieldComponent,
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
  /** The ⋮ menu of a pool entry: remove is its only action. */
  protected readonly rowMenu = computed<readonly RowMenuSection[]>(() => [
    { items: [{ id: 'remove', label: this.i18n.translate('admin.substitutes.remove'), icon: 'trash', danger: true }] },
  ]);
  protected readonly addOpen = signal(false);
  protected readonly candidates = signal<AdminPrincipal[]>([]);
  /**
   * The person search runs while the user types. A failed search shows no persons; the
   * next key press searches again.
   */
  protected readonly search = liveSearch<AdminPrincipal[]>({
    run: (q) => this.api.listPrincipals(q),
    result: (list) =>
      this.candidates.set(list.filter((p) => p.active !== false).slice(0, SEARCH_LIMIT)),
    reset: () => this.candidates.set([]),
    error: () => this.candidates.set([]),
  });
  protected readonly selected = signal<AdminPrincipal | null>(null);
  /** An empty value makes a gremium-wide entry that represents every member. */
  protected readonly memberId = signal('');
  protected readonly adding = signal(false);
  protected readonly addError = signal('');

  protected readonly memberOptions = computed<SelectFieldOption[]>(() => {
    const all = this.i18n.translate('admin.substitutes.allMembers');
    return [
      { value: '', label: all, person: { name: all, icon: 'users' } },
      ...this.memberList().map((m) => ({
        value: m.id,
        label: m.name,
        person: { name: m.name, principalId: m.id },
      })),
    ];
  });

  private loads?: Subscription;

  constructor() {
    effect(() => {
      const id = this.gremiumId();
      const own = this.members() === null;
      untracked(() => this.load(id, own));
    });
    inject(DestroyRef).onDestroy(() => this.loads?.unsubscribe());
  }

  /** Load the pool again after a failed load. */
  protected retry(): void {
    this.load(this.gremiumId(), this.members() === null);
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
              if (!isActiveMembership(m) || seen.has(m.principalId)) continue;
              seen.add(m.principalId);
              list.push({
                id: m.principalId,
                name:
                  personLabel(m, this.i18n, { fallback: 'admin.gremien.unknownMember' }),
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
    this.search.sync('');
    this.selected.set(null);
    this.candidates.set([]);
    this.memberId.set('');
    this.addError.set('');
    this.addOpen.set(true);
  }

  protected onSearch(q: string): void {
    if (this.selected() && q !== this.label(this.selected()!)) this.selected.set(null);
    this.search.set(q);
  }

  /** Without a name and an e-mail: "Ohne Namen", never the `sub`. */
  protected label(p: AdminPrincipal): string {
    return personLabel(p, this.i18n);
  }

  protected pick(p: AdminPrincipal): void {
    this.selected.set(p);
    this.search.sync(this.label(p));
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
