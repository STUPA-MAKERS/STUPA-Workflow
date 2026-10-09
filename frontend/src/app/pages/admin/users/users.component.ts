import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
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
  FilterSelectComponent,
  NoteComponent,
  PageHeaderComponent,
  RowMenuComponent,
  SearchPillComponent,
  StickyBarComponent,
  SkeletonComponent,
} from '@shared/ui';
import { ButtonComponent, ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, GroupMapping, PrincipalFilters, Role } from '../admin.models';
import type { FilterSelectOption, RowMenuItem, RowMenuSection } from '@shared/ui';
import { UserMergeComponent } from './user-merge/user-merge.component';
import { UserRevokeComponent } from './user-revoke/user-revoke.component';

/** The choices of the chip "Letzter Login" (F3): older than n days, or never. */
export const LAST_LOGIN_FILTERS = ['', '90', '180', '365', 'never'] as const;
export type LastLoginFilter = (typeof LAST_LOGIN_FILTERS)[number];
/** The choices of the chip "Hat SSO-Gruppen". */
export const GROUP_FILTERS = ['', 'yes', 'no'] as const;
export type GroupFilter = (typeof GROUP_FILTERS)[number];

/** A last login older than this many days shows in the warning colour. */
export const STALE_LOGIN_DAYS = 90;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * The server filters of the two chips. "über n Tage" also keeps the people who never
 * logged in: they are stale too. `now` is a parameter for the tests.
 */
export function principalFilters(
  lastLogin: LastLoginFilter,
  groups: GroupFilter,
  now = Date.now(),
): PrincipalFilters | undefined {
  const f: PrincipalFilters = {};
  if (lastLogin === 'never') f.includeNever = true;
  else if (lastLogin) {
    f.lastLoginBefore = new Date(now - Number(lastLogin) * DAY_MS).toISOString().slice(0, 10);
    f.includeNever = true;
  }
  if (groups) f.hasGroups = groups === 'yes';
  return Object.keys(f).length ? f : undefined;
}

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
    RowMenuComponent,
    SearchPillComponent,
    StickyBarComponent,
    SkeletonComponent,
    FilterSelectComponent,
    UserMergeComponent,
    UserRevokeComponent,
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
  private readonly router = inject(Router);
  private readonly capitalize = new CapitalizePipe();

  /** OIDC `sub` of the logged-in user. The view uses it to block self-deactivation. */
  protected readonly mySub = computed(() => this.auth.principal()?.sub ?? null);

  /**
   * The search runs while the user types (debounced, a new query cancels the old
   * request). Below two characters the list shows every user.
   */
  protected readonly search = liveSearch<AdminPrincipal[]>({
    run: (q) => {
      const filters = principalFilters(this.lastLoginFilter(), this.groupFilter());
      return filters ? this.api.listPrincipals(q, filters) : this.api.listPrincipals(q);
    },
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

  /** "Mit anderem Konto zusammenführen" needs its own permission (admin only by default). */
  protected readonly canMerge = computed(() => this.auth.can('admin.users.merge'));
  /** "Konto löschen (DSGVO)" leads to the privacy page and needs its permission (D1). */
  protected readonly canErase = computed(() => this.auth.can('privacy.manage'));
  /** "Rechte entziehen …" needs its own permission (admin only by default, F3). */
  protected readonly canRevoke = computed(() => this.auth.can('admin.users.revoke_groups'));
  /** A row has a ⋮ menu when at least one of its actions is allowed. */
  protected readonly hasMenu = computed(() => this.canMerge() || this.canErase() || this.canRevoke());
  /** The old account of the open merge dialog. Null: the dialog is closed. */
  protected readonly mergeSource = signal<AdminPrincipal | null>(null);
  /** The person of the open revoke dialog. Null: the dialog is closed. */
  protected readonly revokeSource = signal<AdminPrincipal | null>(null);

  /** The chip "Letzter Login". */
  protected readonly lastLoginFilter = signal<LastLoginFilter>('');
  /** The chip "Hat SSO-Gruppen". */
  protected readonly groupFilter = signal<GroupFilter>('');
  protected readonly lastLoginOptions = computed<FilterSelectOption[]>(() =>
    LAST_LOGIN_FILTERS.map((value) => ({
      value,
      label: this.i18n.translate(`admin.users.filter.lastLogin.${value || 'all'}`),
    })),
  );
  protected readonly groupOptions = computed<FilterSelectOption[]>(() =>
    GROUP_FILTERS.map((value) => ({
      value,
      label: this.i18n.translate(`admin.users.filter.groups.${value || 'all'}`),
    })),
  );
  /** The chip text: "Letzter Login: über 90 Tage", or only the name while it is off. */
  protected readonly lastLoginText = computed(() => this.chipText('admin.users.filter.lastLogin', this.lastLoginFilter(), this.lastLoginOptions()));
  protected readonly groupText = computed(() => this.chipText('admin.users.filter.groups', this.groupFilter(), this.groupOptions()));

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

  private chipText(
    key: 'admin.users.filter.lastLogin' | 'admin.users.filter.groups',
    value: string,
    options: readonly FilterSelectOption[],
  ): string {
    const name = this.i18n.translate(key);
    const hit = options.find((o) => o.value === value);
    return value && hit ? `${name}: ${hit.label}` : name;
  }

  protected setLastLoginFilter(value: string): void {
    this.lastLoginFilter.set(value as LastLoginFilter);
    this.search.refresh();
  }

  protected setGroupFilter(value: string): void {
    this.groupFilter.set(value as GroupFilter);
    this.search.refresh();
  }

  /** The last login is older than {@link STALE_LOGIN_DAYS}: it shows in the warning colour. */
  protected isStale(p: AdminPrincipal, now = Date.now()): boolean {
    return !!p.lastLogin && now - new Date(p.lastLogin).getTime() > STALE_LOGIN_DAYS * DAY_MS;
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

  /** The name of an account. Without a name and an e-mail: "Ohne Namen" (D7), never the `sub`. */
  protected userLabel(p: AdminPrincipal): string {
    return p.displayName || p.email || this.i18n.translate('common.unnamed');
  }

  /** The tooltip of the name: the `sub` of a nameless account, for the admin detail (D7). */
  protected userTitle(p: AdminPrincipal): string {
    return p.displayName || p.email ? this.userLabel(p) : p.sub;
  }

  /** The account of the logged-in user. The view blocks a deactivation of it. */
  protected isSelf(p: AdminPrincipal): boolean {
    return this.mySub() !== null && p.sub === this.mySub();
  }

  /** The row menu of an account that is not merged. */
  protected menuFor(p: AdminPrincipal): RowMenuSection[] {
    const items: RowMenuItem[] = [];
    if (this.canMerge()) {
      items.push({
        id: 'merge',
        label: this.i18n.translate('admin.users.merge.action'),
        icon: 'users',
        danger: true,
        disabledReason: this.isSelf(p) ? this.i18n.translate('admin.users.merge.notSelf') : null,
      });
    }
    // Only for a person who still has something to take away (the server flag `hasAccess`).
    if (this.canRevoke() && p.hasAccess) {
      items.push({
        id: 'revoke',
        label: this.i18n.translate('admin.users.revoke.action'),
        icon: 'shield',
        danger: true,
        // The server refuses it too (409 `revoke_own_account`).
        disabledReason: this.isSelf(p) ? this.i18n.translate('admin.users.revoke.notSelf') : null,
      });
    }
    if (this.canErase()) {
      items.push({
        id: 'erase',
        label: this.i18n.translate('admin.users.erase.action'),
        icon: 'trash',
        danger: true,
        // The server refuses it too (409 `erase_self`).
        disabledReason: this.isSelf(p) ? this.i18n.translate('admin.users.erase.notSelf') : null,
      });
    }
    return [{ items }];
  }

  protected onMenu(item: RowMenuItem, p: AdminPrincipal): void {
    if (item.id === 'merge') this.mergeSource.set(p);
    if (item.id === 'revoke') this.revokeSource.set(p);
    // The privacy page holds the one erasure path with its confirmation (D1).
    if (item.id === 'erase') void this.router.navigate(['/admin/privacy'], { queryParams: { person: p.sub } });
  }

  /** The revoke ran: the groups and roles of the row changed. Reload the list. */
  protected onRevoked(): void {
    this.search.refresh();
  }

  /** The merge ran: the old account is now a reference. Reload the list. */
  protected onMerged(): void {
    this.search.refresh();
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
