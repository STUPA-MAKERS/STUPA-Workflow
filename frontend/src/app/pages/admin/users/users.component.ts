import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { liveSearch } from '@shared/live-search';
import {
  AvatarComponent,
  EmptyStateComponent,
  NoteComponent,
  PageHeaderComponent,
  SearchPillComponent,
  StickyBarComponent,
  SkeletonComponent,
} from '@shared/ui';
import { ButtonComponent, ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, GroupMapping, Role } from '../admin.models';

/**
 * Users (board Admin-Benutzer): a search and one row per principal.
 *
 * A row shows the person, the global roles, the OIDC groups and the last login, and
 * "Deaktivieren" or "Aktivieren". The roles are read-only. They come from the OIDC
 * groups through the group mappings (`/admin/group-mappings`), plus the bootstrap
 * assignments (`admin` from the settings and the implicit `member`). Gremium membership
 * and gremium roles have their own mappings on the same page. The frontend only gates
 * the UX. The server stays authoritative.
 */
@Component({
  selector: 'app-admin-users',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    AvatarComponent,
    EmptyStateComponent,
    NoteComponent,
    PageHeaderComponent,
    SearchPillComponent,
    StickyBarComponent,
    SkeletonComponent,
  ],
  templateUrl: './users.component.html',
  styleUrl: './users.component.scss',
})
export class UsersComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly capitalize = new CapitalizePipe();

  /** OIDC `sub` of the logged-in user. The view uses it to block self-deactivation. */
  protected readonly mySub = computed(() => this.auth.principal()?.sub ?? null);

  /**
   * The search runs while the user types (debounced, a new query cancels the old
   * request). Below two characters the list shows every user.
   */
  protected readonly search = liveSearch<AdminPrincipal[]>({
    run: (q) => this.api.listPrincipals(q),
    result: (list) => {
      this.principals.set(list);
      this.loading.set(false);
    },
    error: () => {
      this.loading.set(false);
      this.toast.error(this.i18n.translate('admin.users.loadFailed'));
    },
  });
  protected readonly principals = signal<AdminPrincipal[]>([]);
  protected readonly roles = signal<Role[]>([]);
  /** The global group mappings. Empty without `admin.group_mappings`. */
  private readonly groupMappings = signal<GroupMapping[]>([]);

  /** The group-mappings page needs its own permission. The hint links to it only then. */
  protected readonly canManageMappings = computed(() => this.auth.can('admin.group_mappings'));

  protected readonly rolesById = computed(() => new Map(this.roles().map((r) => [r.id, r])));

  /**
   * True until the first answer. Without it the table says "Keine Treffer" while the
   * request is still out, which asserts there is nothing when nothing has arrived yet.
   * A later search keeps the rows and turns the magnifier into a spinner instead, so
   * the list does not jump on every key press.
   */
  protected readonly loading = signal(true);

  constructor() {
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    // The mappings resolve the roles that the groups give. Without the permission the
    // request answers 403, so the column then shows the bootstrap roles only.
    if (this.canManageMappings()) {
      this.api.listGroupMappings().subscribe({
        next: (m) => this.groupMappings.set(m),
        error: () => this.groupMappings.set([]),
      });
    }
    // `/admin/users?q=…` is where a global-search hit on a person lands. Without it the
    // hit opened the unfiltered list and the reader searched the same name twice.
    //
    // The subscription and not one read of the snapshot: the palette can send us here
    // while we are already here, and a hit on another person changes only the query
    // string. The router keeps this component, so a snapshot read would never run again.
    // The query param map emits at once, so its first value makes the initial load.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      const q = qp.get('q') ?? '';
      if (q === this.search.text() && this.principals().length) return;
      this.search.sync(q);
      this.search.refresh();
    });
  }

  /**
   * The global roles of one principal, read-only: the global bootstrap assignments
   * plus every role that a group mapping gives to one of the OIDC groups. The same
   * rule as the RBAC resolver: an exact group match, the reserved `vote:` groups
   * give nothing.
   */
  protected roleIds(p: AdminPrincipal): string[] {
    const ids = new Set(p.assignments.filter((a) => !a.gremiumId).map((a) => a.roleId));
    const groups = new Set(p.oidcGroups.filter((g) => !g.startsWith('vote:')));
    for (const m of this.groupMappings()) {
      if (groups.has(m.oidcGroup)) ids.add(m.roleId);
    }
    return [...ids];
  }

  protected roleLabel(roleId: string): string {
    const role = this.rolesById().get(roleId);
    if (!role) return roleId;
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  /** The global roles of one principal as one line, for example "Administration, Mitglied". */
  protected roleText(p: AdminPrincipal): string {
    return this.roleIds(p)
      .map((id) => this.capitalize.transform(this.roleLabel(id)))
      .join(', ');
  }

  protected userLabel(p: AdminPrincipal): string {
    return p.displayName || p.email || p.sub;
  }

  /** The account of the logged-in user. The view blocks a deactivation of it. */
  protected isSelf(p: AdminPrincipal): boolean {
    return this.mySub() !== null && p.sub === this.mySub();
  }

  protected setActive(principal: AdminPrincipal, active: boolean): void {
    this.api.setPrincipalActive(principal.id, active).subscribe({
      next: () => {
        this.toast.success(
          this.i18n.translate(active ? 'admin.users.activated' : 'admin.users.deactivated'),
        );
        this.search.refresh();
      },
      error: () => this.toast.error(this.i18n.translate('admin.users.actionFailed')),
    });
  }
}
