import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { type DelegationSubstitute, DelegationsApiService } from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  type Action,
  AvatarComponent,
  ButtonGroupComponent,
  DialogComponent,
  IconComponent,
  ListItemComponent,
  type ListRow,
  liveSearch,
  type LoadState,
  NoteComponent,
  RowMenuComponent,
  type RowMenuSection,
  SearchPillComponent,
  SelectFieldComponent,
  type SelectFieldOption,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';
import {
  RecordsScreenComponent,
  ScreenRecordDirective,
  ScreenSearchDirective,
} from '@stupa-makers/ui-kit/screens';
import { Subscription } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { type AdminPrincipal, isActiveMembership } from '../admin.models';
import { personLabel } from '@shared/person-label.util';
import { PageFrameService } from '../../../layout/page-frame.service';
import { hitCount, listSearch, searchedRows } from '../list-search';

/** A member of the gremium: a choice of "Vertritt". */
export interface PoolMember {
  readonly id: string;
  readonly name: string;
}

/** The most persons the search shows. */
const SEARCH_LIMIT = 8;

/**
 * The Stellvertretungen of one gremium on their own page
 * (`/admin/committees/:id/substitutes`, §002692): the substitute pool as a list page of
 * Verwaltung (§002690) with the search of Benutzer (§002691).
 *
 * A delegation to a pool substitute has no lead time and stays possible until the
 * meeting starts, also for a person who is not a member. An entry represents every
 * member or one member. "Stellvertretung hinzufügen" is the FAB; its dialog searches the
 * persons on the server. The page loads the members of the gremium for "Vertritt" and the
 * names of the rows. The last crumb shows the name of the gremium once it loads.
 *
 * The server checks the rights: `admin.delegations` or `session.manage` in the gremium.
 */
@Component({
  selector: 'app-substitute-pool',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    NoteComponent,
    FormsModule,
    TranslatePipe,
    AvatarComponent,
    ListItemComponent,
    SearchPillComponent,
    ButtonGroupComponent,
    DialogComponent,
    IconComponent,
    RowMenuComponent,
    SelectFieldComponent,
    RecordsScreenComponent,
    ScreenRecordDirective,
    ScreenSearchDirective,
  ],
  templateUrl: './substitute-pool.component.html',
  styleUrl: './substitute-pool.component.scss',
})
export class SubstitutePoolComponent {
  private readonly api = inject(AdminApiService);
  private readonly delegations = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  private readonly route = inject(ActivatedRoute);
  /** The gremium of the page, from the route. */
  readonly gremiumId = (this.route.snapshot.paramMap.get('id') ?? '') as Uuid;
  /** The name of the gremium for the title and the last crumb; `null` until it loads. */
  protected readonly gremiumName = signal<string | null>(null);

  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  protected readonly entries = signal<DelegationSubstitute[]>([]);
  protected readonly memberList = signal<PoolMember[]>([]);

  /** The search of the list (§002690, §002691). */
  protected readonly listSearch = listSearch();
  /** The rows of the records screen (§ui-kit:002257). */
  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    if (this.loading()) return { state: 'loading' };
    if (this.failed())
      return {
        state: 'error',
        message: this.i18n.translate('admin.substitutes.loadFailed'),
        retry: () => this.retry(),
      };
    const all = this.i18n.translate('admin.substitutes.allMembers');
    const rows = this.listSearch
      .filter(this.entries(), (s) => [this.memberName(s) ?? all, this.entryName(s)])
      .map((s) => ({ id: s.id, title: this.entryName(s) }));
    return searchedRows(
      rows.length
        ? { state: 'ready', data: rows }
        : { state: 'empty', icon: 'users', heading: this.i18n.translate('admin.substitutes.empty') },
      this.listSearch,
      this.i18n.translate('admin.list.noHits'),
    );
  });
  /** The hits of the search for the pill. */
  protected readonly hits = computed(() => hitCount(this.rows(), this.listSearch));
  /** "Stellvertretung hinzufügen" as the FAB. */
  protected readonly actions = computed<readonly Action[]>(() => [
    {
      key: 'add',
      label: this.i18n.translate('admin.substitutes.add'),
      icon: 'plus',
      priority: 'fab',
    },
  ]);
  /** The ids of the entries with a delete in flight. */
  protected readonly removing = signal<ReadonlySet<string>>(new Set());

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
    const frame = inject(PageFrameService);
    const url =
      '/' +
      this.route.snapshot.pathFromRoot
        .flatMap((r) => r.url.map((s) => s.path))
        .filter(Boolean)
        .join('/');
    effect(() => {
      const name = this.gremiumName();
      frame.crumbLabel.set(name ? { url, label: name } : null);
    });
    inject(DestroyRef).onDestroy(() => {
      frame.crumbLabel.set(null);
      this.loads?.unsubscribe();
    });
    this.api.listGremienOptions().subscribe({
      next: (list) => this.gremiumName.set(list.find((g) => g.id === this.gremiumId)?.name ?? null),
      error: () => this.gremiumName.set(null),
    });
    this.load(this.gremiumId);
  }

  /** The entry of a row of the records screen. */
  protected entryOf(id: string): DelegationSubstitute {
    return this.entries().find((s) => s.id === id)!;
  }

  /** Load the pool again after a failed load. */
  protected retry(): void {
    this.load(this.gremiumId);
  }

  private load(id: Uuid): void {
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
    this.loads.add(
      this.api.listGremiumMemberships(id).subscribe({
        next: (rows) => {
          const active = rows.filter(isActiveMembership);
          const list: PoolMember[] = active
            .filter((m, i) => active.findIndex((x) => x.principalId === m.principalId) === i)
            .map((m) => ({
              id: m.principalId,
              name:
                personLabel(m, this.i18n, { fallback: 'admin.gremien.unknownMember' }),
            }));
          this.memberList.set(list.sort((a, b) => a.name.localeCompare(b.name)));
        },
        error: () => this.memberList.set([]),
      }),
    );
  }

  protected entryName(s: DelegationSubstitute): string {
    return s.substituteName || this.i18n.translate('admin.gremien.unknownMember');
  }

  protected memberName(s: DelegationSubstitute): string | null {
    if (!s.memberId) return null;
    return s.memberName || this.memberList().find((m) => m.id === s.memberId)?.name || '—';
  }

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
        gremiumId: this.gremiumId,
        memberId: this.memberId() ? (this.memberId() as Uuid) : null,
        substituteId: s.id,
      })
      .subscribe({
        next: (row) => {
          this.adding.set(false);
          this.addOpen.set(false);
          this.entries.update((list) => [...list, row]);
          this.toast.show(this.i18n.translate('admin.substitutes.added'), 'success');
        },
        error: (err: { status?: number }) => {
          this.adding.set(false);
          if (err.status !== 409 && err.status !== 422) {
            this.toast.show(this.i18n.translate('admin.substitutes.failed'), 'error');
            return;
          }
          this.addError.set(
            this.i18n.translate(
              err.status === 409 ? 'admin.substitutes.duplicate' : 'admin.substitutes.invalid',
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
        this.toast.show(this.i18n.translate('admin.substitutes.removed'), 'success');
      },
      error: () => {
        this.done(s.id);
        this.toast.show(this.i18n.translate('admin.substitutes.failed'), 'error');
      },
    });
  }

  private done(id: string): void {
    this.removing.update((r) => new Set([...r].filter((x) => x !== id)));
  }
}
