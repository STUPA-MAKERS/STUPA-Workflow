import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  effect,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { i18nLabel } from '@shared/forms/i18n-text';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { PageFrameService } from '../../../layout/page-frame.service';
import {
  AvatarComponent,
  CapitalizePipe,
  type ListRow,
  type LoadState,
  NoteComponent,
  SearchPillComponent,
} from '@stupa-makers/ui-kit';
import {
  RecordsScreenComponent,
  ScreenIntroDirective,
  ScreenRecordDirective,
  ScreenSearchDirective,
} from '@stupa-makers/ui-kit/screens';
import { AdminApiService } from '../admin-api.service';
import {
  FORCED_GREMIUM_ROLE_KEYS,
  type Gremium,
  type GremiumMembership,
  type GremiumRole,
  isActiveMembership,
  MEMBER_GREMIUM_ROLE_KEY,
} from '../admin.models';
import { personLabel } from '@shared/person-label.util';
import { hitCount, listSearch, searchedRows } from '../list-search';

/** One row of the member list. */
interface Member {
  readonly id: string;
  readonly name: string;
  readonly email: string | null;
  readonly role: string;
  /** Sort rank of the role: board and manager first, `member` last. */
  readonly rank: number;
}

/**
 * Members of a gremium on its own page (`/admin/committees/:id/members`).
 *
 * A list page of Verwaltung (§002690) with the search of Benutzer (§002691). The members come
 * only from the OIDC groups of the IdP, so the list is read-only: avatar, name, e-mail and the
 * gremium role. The note links to the group mappings, where the memberships come from. The
 * membership rows carry the name and the e-mail of the member, so the page loads no principal
 * list. The substitute pool has its own page (§002692). The last crumb shows the name of the
 * gremium once it loads.
 */
@Component({
  selector: 'app-gremium-members',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    CapitalizePipe,
    AvatarComponent,
    NoteComponent,
    RecordsScreenComponent,
    ScreenIntroDirective,
    ScreenRecordDirective,
    ScreenSearchDirective,
    SearchPillComponent,
  ],
  templateUrl: './gremium-members.component.html',
  styleUrl: './gremium-members.component.scss',
})
export class GremiumMembersComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);

  private readonly route = inject(ActivatedRoute);
  protected readonly gremiumId = (this.route.snapshot.paramMap.get('id') ?? '') as Uuid;

  /** True until the first answer, so the list does not claim there are no members. */
  protected readonly loading = signal(true);
  protected readonly failed = signal(false);

  /** The note links to the mappings page only with its permission. */
  protected readonly canManageMappings = computed(() => this.auth.can('admin.group_mappings'));

  readonly gremium = signal<Gremium | null>(null);
  private readonly gremiumRoles = signal<GremiumRole[]>([]);
  private readonly memberships = signal<GremiumMembership[]>([]);

  private readonly rolesById = computed(() => new Map(this.gremiumRoles().map((r) => [r.id, r])));

  /**
   * One row per person, sorted by role (board, manager, own roles, member), then name.
   * Only the active memberships count, so the header agrees with the gremien list.
   */
  readonly members = computed<Member[]>(() => {
    const active = this.memberships().filter(isActiveMembership);
    const rows: Member[] = active
      .filter((m, i) => active.findIndex((x) => x.principalId === m.principalId) === i)
      .map((m) => {
        const role = this.rolesById().get(m.gremiumRoleId);
        return {
          id: m.principalId,
          name: personLabel(m, this.i18n, { fallback: 'admin.gremien.unknownMember' }),
          email: m.email ?? null,
          role: role ? this.roleName(role) : '—',
          rank: this.rank(role),
        };
      });
    return rows.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
  });

  /** The search of the list (§002690, §002691). */
  protected readonly search = listSearch();
  /** The rows of the records screen (§ui-kit:002257). */
  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    if (this.loading()) return { state: 'loading' };
    if (this.failed())
      return {
        state: 'error',
        message: this.i18n.translate('admin.gremien.membersLoadFailed'),
        retry: () => this.loadMembers(),
      };
    const rows = this.search
      .filter(this.members(), (m) => [m.name, m.email, m.role])
      .map((m) => ({ id: m.id, title: m.name }));
    return searchedRows(
      rows.length
        ? { state: 'ready', data: rows }
        : { state: 'empty', icon: 'users', heading: this.i18n.translate('admin.gremien.membersEmpty') },
      this.search,
      this.i18n.translate('admin.list.noHits'),
    );
  });
  /** The hits of the search for the pill. */
  protected readonly hits = computed(() => hitCount(this.rows(), this.search));

  /** The member of a row of the records screen. */
  protected memberOf(id: string): Member {
    return this.members().find((m) => m.id === id)!;
  }

  constructor() {
    const frame = inject(PageFrameService);
    const url =
      '/' +
      this.route.snapshot.pathFromRoot
        .flatMap((r) => r.url.map((s) => s.path))
        .filter(Boolean)
        .join('/');
    effect(() => {
      const name = this.gremium()?.name;
      frame.crumbLabel.set(name ? { url, label: name } : null);
    });
    inject(DestroyRef).onDestroy(() => frame.crumbLabel.set(null));
    this.api.listGremienOptions().subscribe({
      next: (list) => this.gremium.set(list.find((g) => g.id === this.gremiumId) ?? null),
      error: () => this.gremium.set(null),
    });
    this.api.listGremiumRoles(this.gremiumId, { quiet: true }).subscribe({
      next: (r) => this.gremiumRoles.set(r),
      error: () => this.gremiumRoles.set([]),
    });
    this.loadMembers();
  }

  /** Load the memberships. A failure, for example a 403, shows, never an empty list. */
  protected loadMembers(): void {
    this.loading.set(true);
    this.failed.set(false);
    this.api.listGremiumMemberships(this.gremiumId).subscribe({
      next: (m) => {
        this.memberships.set(m);
        this.loading.set(false);
      },
      error: () => {
        this.memberships.set([]);
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  private roleName(role: GremiumRole): string {
    return i18nLabel(role.name, this.i18n.uiLocale(), role.key);
  }

  private rank(role: GremiumRole | undefined): number {
    if (!role) return 99;
    if (role.key === MEMBER_GREMIUM_ROLE_KEY) return 50;
    const i = (FORCED_GREMIUM_ROLE_KEYS as readonly string[]).indexOf(role.key);
    return i < 0 ? 10 : i;
  }
}
