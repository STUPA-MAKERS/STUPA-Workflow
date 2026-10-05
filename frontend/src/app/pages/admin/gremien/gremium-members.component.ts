import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { AvatarComponent, NoteComponent, PageHeaderComponent, SkeletonComponent } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import {
  FORCED_GREMIUM_ROLE_KEYS,
  type Gremium,
  type GremiumMembership,
  type GremiumRole,
  MEMBER_GREMIUM_ROLE_KEY,
} from '../admin.models';
import { SubstitutePoolComponent } from '../delegations/substitute-pool.component';

/** One row of the member list. */
interface Member {
  id: string;
  name: string;
  email: string | null;
  role: string;
  /** Sort rank of the role: board and manager first, `member` last. */
  rank: number;
}

/** The rows the list shows before "Alle n anzeigen". */
export const MEMBER_PREVIEW = 7;

/**
 * Members of a gremium on its own page (`/admin/gremien/:id/members`, board
 * Admin-Gremium-Mitglieder).
 *
 * The members come only from the OIDC groups of the IdP, so the list is read-only: avatar,
 * name, e-mail and the gremium role. The note links to the group mappings, where the
 * memberships come from. The list shows the first rows; "Alle n anzeigen" shows the rest.
 * The membership rows carry the name and the e-mail of the member, so the page loads no
 * principal list. With `admin.delegations` the substitute pool of the gremium follows
 * (`app-substitute-pool`).
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
    PageHeaderComponent,
    SkeletonComponent,
    SubstitutePoolComponent,
  ],
  templateUrl: './gremium-members.component.html',
  styleUrl: './gremium-members.component.scss',
})
export class GremiumMembersComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);

  protected readonly gremiumId = (inject(ActivatedRoute).snapshot.paramMap.get('id') ?? '') as Uuid;

  /** True until the first answer, so the list does not claim there are no members. */
  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  protected readonly showAll = signal(false);
  protected readonly preview = MEMBER_PREVIEW;

  /** The note links to the mappings page only with its permission. */
  protected readonly canManageMappings = computed(() => this.auth.can('admin.group_mappings'));
  /** The substitute pool needs `admin.delegations` (or `session.manage` in the gremium). */
  protected readonly canPool = computed(
    () =>
      this.auth.can('admin.delegations') ||
      this.auth.canInGremium(this.gremiumId, 'session.manage'),
  );

  readonly gremium = signal<Gremium | null>(null);
  private readonly gremiumRoles = signal<GremiumRole[]>([]);
  private readonly memberships = signal<GremiumMembership[]>([]);

  private readonly rolesById = computed(() => new Map(this.gremiumRoles().map((r) => [r.id, r])));

  /** One row per person, sorted by role (board, manager, own roles, member), then name. */
  readonly members = computed<Member[]>(() => {
    const seen = new Set<string>();
    const rows: Member[] = [];
    for (const m of this.memberships()) {
      if (seen.has(m.principalId)) continue;
      seen.add(m.principalId);
      const role = this.rolesById().get(m.gremiumRoleId);
      rows.push({
        id: m.principalId,
        name: m.displayName || m.email || this.i18n.translate('admin.gremien.unknownMember'),
        email: m.email ?? null,
        role: role ? this.roleName(role) : '—',
        rank: this.rank(role),
      });
    }
    return rows.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
  });

  protected readonly visible = computed(() =>
    this.showAll() ? this.members() : this.members().slice(0, MEMBER_PREVIEW),
  );

  /** The options of "Vertritt" in the substitute pool: every member. */
  protected readonly poolMembers = computed(() =>
    this.members().map((m) => ({ id: m.id, name: m.name })),
  );

  constructor() {
    this.api.listGremienOptions().subscribe({
      next: (list) => this.gremium.set(list.find((g) => g.id === this.gremiumId) ?? null),
      error: () => this.gremium.set(null),
    });
    this.api.listGremiumRoles(this.gremiumId, { quiet: true }).subscribe({
      next: (r) => this.gremiumRoles.set(r),
      error: () => this.gremiumRoles.set([]),
    });
    this.api.listGremiumMemberships(this.gremiumId).subscribe({
      next: (m) => {
        this.memberships.set(m);
        this.loading.set(false);
      },
      // Show the failure, for example a 403, and never an empty list.
      error: () => {
        this.memberships.set([]);
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  private roleName(role: GremiumRole): string {
    return role.name[this.i18n.locale()] ?? role.name['de'] ?? role.key;
  }

  private rank(role: GremiumRole | undefined): number {
    if (!role) return 99;
    if (role.key === MEMBER_GREMIUM_ROLE_KEY) return 50;
    const i = (FORCED_GREMIUM_ROLE_KEYS as readonly string[]).indexOf(role.key);
    return i < 0 ? 10 : i;
  }

  protected countLabel(n: number): string {
    return this.i18n.translate(n === 1 ? 'admin.home.memberCountOne' : 'admin.home.memberCount', {
      count: n,
    });
  }
}
