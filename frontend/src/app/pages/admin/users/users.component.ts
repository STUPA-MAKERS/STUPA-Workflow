import { SlicePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  IconComponent,
  RowDetailDirective,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, Role, RoleAssignment } from '../admin.models';

/** Local form state for assigning a role per user. */
interface AssignDraft {
  roleId: string;
  validFrom: string;
  validUntil: string;
}

function emptyDraft(): AssignDraft {
  return { roleId: '', validFrom: '', validUntil: '' };
}

/**
 * Users & roles as a **table** (modeled on the Nextcloud user table).
 *
 * One row per principal: name, e-mail, OIDC subject, assigned roles (tags,
 * revocable), last login. Assigning a role happens via a per-row expandable
 * mini-form (role + optional tz validity window = substitution). **Gremium
 * membership** is deliberately no longer maintained here — that happens per
 * gremium in the gremien administration. The role **permissions** live on their
 * own page (`/admin/roles`). FE is a UX gate; the server stays authoritative.
 */
@Component({
  selector: 'app-admin-users',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    SlicePipe,
    TranslatePipe,
    CapitalizePipe,
    ButtonComponent,
    BadgeComponent,
    SelectComponent,
    DatepickerComponent,
    DataTableComponent,
    CellDirective,
    RowDetailDirective,
    IconComponent,
  ],
  providers: [CapitalizePipe],
  templateUrl: './users.component.html',
  styleUrl: './users.component.scss',
})
export class UsersComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly capitalize = inject(CapitalizePipe);
  private readonly auth = inject(AuthService);

  /** OIDC `sub` of the logged-in user — for self-protection. */
  protected readonly mySub = computed(() => this.auth.principal()?.sub ?? null);

  protected readonly query = signal('');
  protected readonly principals = signal<AdminPrincipal[]>([]);
  protected readonly roles = signal<Role[]>([]);
  protected readonly drafts = signal<Record<string, AssignDraft>>({});
  /** Which rows have the "assign role" form expanded. */
  protected readonly expanded = signal<Set<string>>(new Set());

  protected readonly rolesById = computed(() => new Map(this.roles().map((r) => [r.id, r])));

  protected readonly roleOptions = computed<SelectOption[]>(() =>
    this.roles().map((r) => ({
      value: r.id,
      label: this.capitalize.transform(this.roleLabel(r.id)),
    })),
  );

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.users.col.name'), width: '22rem' },
    { key: 'email', label: this.i18n.translate('admin.users.col.email') },
    { key: 'roles', label: this.i18n.translate('admin.users.col.roles') },
    { key: 'lastLogin', label: this.i18n.translate('admin.users.col.lastLogin') },
    { key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' },
  ]);

  /** Show only global roles (without gremium scope) in the roles column. */
  protected globalAssignments(p: AdminPrincipal): RoleAssignment[] {
    return p.assignments.filter((a) => !a.gremiumId);
  }
  protected readonly rowId = (p: unknown): string => (p as AdminPrincipal).id;
  /** Detail row (assign form) for expanded principals. */
  protected readonly rowExpanded = (p: unknown): boolean => this.isExpanded((p as AdminPrincipal).id);

  constructor() {
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    this.search();
  }

  // --- Search ---------------------------------------------------------------
  protected search(): void {
    this.api.listPrincipals(this.query()).subscribe({
      next: (list) => this.principals.set(list),
      error: () => this.toast.error(this.i18n.translate('admin.users.loadFailed')),
    });
  }

  protected roleLabel(roleId: string): string {
    const role = this.rolesById().get(roleId);
    if (!role) return roleId;
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  protected userLabel(p: AdminPrincipal): string {
    return p.displayName || p.email || p.sub;
  }

  /** Protected roles (admin, member) — no revoke cross. */
  protected isAdminRole(roleId: string): boolean {
    const key = this.rolesById().get(roleId)?.key;
    return key === 'admin' || key === 'member';
  }

  /** Own account — deactivation is blocked. */
  protected isSelf(p: AdminPrincipal): boolean {
    return this.mySub() !== null && p.sub === this.mySub();
  }

  // --- Expand ---------------------------------------------------------------
  protected isExpanded(id: string): boolean {
    return this.expanded().has(id);
  }

  protected toggleAssign(id: string): void {
    this.expanded.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // --- Assign ---------------------------------------------------------------
  protected draftFor(principalId: string): AssignDraft {
    return this.drafts()[principalId] ?? emptyDraft();
  }

  protected patchDraft(principalId: string, patch: Partial<AssignDraft>): void {
    this.drafts.update((d) => ({
      ...d,
      [principalId]: { ...this.draftFor(principalId), ...patch },
    }));
  }

  protected assign(principal: AdminPrincipal): void {
    const draft = this.draftFor(principal.id);
    if (!draft.roleId) return;
    this.api
      .assignRole({
        principalId: principal.id,
        roleId: draft.roleId,
        gremiumId: null,
        validFrom: isoOrNull(draft.validFrom),
        validUntil: isoOrNull(draft.validUntil),
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.users.assigned'));
          this.drafts.update((d) => ({ ...d, [principal.id]: emptyDraft() }));
          this.expanded.update((set) => {
            const next = new Set(set);
            next.delete(principal.id);
            return next;
          });
          this.search();
        },
        error: () => this.toast.error(this.i18n.translate('admin.users.assignFailed')),
      });
  }

  /** Activate/deactivate a user. */
  protected setActive(principal: AdminPrincipal, active: boolean): void {
    this.api.setPrincipalActive(principal.id, active).subscribe({
      next: () => {
        this.toast.success(
          this.i18n.translate(active ? 'admin.users.activated' : 'admin.users.deactivated'),
        );
        this.search();
      },
      error: () => this.toast.error(this.i18n.translate('admin.users.actionFailed')),
    });
  }

  protected revoke(assignment: RoleAssignment): void {
    this.api.revokeRole(assignment.id).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.users.revoked'));
        this.search();
      },
      error: () => this.toast.error(this.i18n.translate('admin.users.revokeFailed')),
    });
  }
}

/** Empty date → null; a `YYYY-MM-DD` value → ISO UTC midnight. */
function isoOrNull(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.length === 10 ? `${trimmed}T00:00:00Z` : trimmed;
}
