import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CheckboxComponent,
  DatepickerComponent,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { AdminOptionsService } from '../admin-options.service';
import type { AdminPrincipal, Role, RoleAssignment } from '../admin.models';

/** Lokaler Formularzustand fürs Zuweisen einer Rolle je Benutzer. */
interface AssignDraft {
  roleId: string;
  gremiumId: string;
  validFrom: string;
  validUntil: string;
  delegateVoting: boolean;
}

/**
 * Benutzer & Rollen (#70/#72/#73, api.md `/admin/principals` + `/role-assignments`).
 *
 * Admins (RBAC `admin.roles`, serverseitig erzwungen) suchen Benutzer per OIDC-`sub`/
 * Name/E-Mail, weisen Rollen zu (optionales tz-aware Gültigkeitsfenster = Vertretung)
 * oder entziehen sie, und sehen/pflegen die Rechte je Rolle. Rollen-Tags werden
 * kapitalisiert angezeigt (#73), der Schlüssel-/Wert bleibt unverändert. Das FE ist
 * reines UX-Gate — der Server bleibt autoritativ.
 */
@Component({
  selector: 'app-admin-users',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    CapitalizePipe,
    ButtonComponent,
    BadgeComponent,
    CheckboxComponent,
    SelectComponent,
    DatepickerComponent,
  ],
  providers: [CapitalizePipe],
  templateUrl: './users.component.html',
  styleUrl: './users.component.scss',
})
export class UsersComponent {
  private readonly api = inject(AdminApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly capitalize = inject(CapitalizePipe);

  protected readonly query = signal('');
  protected readonly principals = signal<AdminPrincipal[]>([]);
  protected readonly roles = signal<Role[]>([]);
  protected readonly permissions = signal<string[]>([]);
  protected readonly drafts = signal<Record<string, AssignDraft>>({});
  /** Gremien als Dropdown — eine Rollenzuweisung ist gremium-scoped (#5). */
  protected readonly gremiumOptions = signal<SelectOption[]>([]);

  /** Rollen-Lookup (id → Role) für Tag-Beschriftung + Validierung. */
  protected readonly rolesById = computed(
    () => new Map(this.roles().map((r) => [r.id, r])),
  );

  /** Optionen fürs Rollen-Dropdown (#73: kapitalisierte Labels, Wert = id). */
  protected readonly roleOptions = computed<SelectOption[]>(() =>
    this.roles().map((r) => ({
      value: r.id,
      label: this.capitalize.transform(this.roleLabel(r.id)),
    })),
  );

  constructor() {
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    this.api.listPermissions().subscribe((p) => this.permissions.set(p));
    this.options.gremiumOptions().subscribe({
      next: (opts) => this.gremiumOptions.set(opts),
      error: () => this.gremiumOptions.set([]),
    });
    this.search();
  }

  // --- Benutzer-Suche -------------------------------------------------------
  protected search(): void {
    this.api.listPrincipals(this.query()).subscribe({
      next: (list) => this.principals.set(list),
      error: () => this.toast.error(this.i18n.translate('admin.users.loadFailed')),
    });
  }

  /**
   * Roher (lokalisierter) Rollen-Name; die Kapitalisierung fürs #73-Tag macht die
   * gemeinsame `CapitalizePipe` (Template `| capitalize`) bzw. `roleOptions`.
   */
  protected roleLabel(roleId: string): string {
    const role = this.rolesById().get(roleId);
    if (!role) return roleId;
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  // --- Zuweisen -------------------------------------------------------------
  protected draftFor(principalId: string): AssignDraft {
    return (
      this.drafts()[principalId] ?? {
        roleId: '',
        gremiumId: '',
        validFrom: '',
        validUntil: '',
        delegateVoting: false,
      }
    );
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
        gremiumId: draft.gremiumId || null,
        validFrom: isoOrNull(draft.validFrom),
        validUntil: isoOrNull(draft.validUntil),
        delegateVoting: draft.delegateVoting,
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.users.assigned'));
          this.drafts.update((d) => ({ ...d, [principal.id]: { roleId: '', gremiumId: '', validFrom: '', validUntil: '', delegateVoting: false } }));
          this.search();
        },
        error: () => this.toast.error(this.i18n.translate('admin.users.assignFailed')),
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

  // --- Rechte je Rolle ------------------------------------------------------
  protected hasPerm(role: Role, perm: string): boolean {
    return role.permissions.includes(perm);
  }

  protected togglePerm(role: Role, perm: string, on: boolean): void {
    const permissions = on
      ? [...role.permissions, perm]
      : role.permissions.filter((p) => p !== perm);
    this.roles.update((list) =>
      list.map((r) => (r.id === role.id ? { ...r, permissions } : r)),
    );
  }

  protected saveRole(role: Role): void {
    this.api.saveRolePermissions(role.id, role.permissions).subscribe({
      next: (saved) => {
        this.roles.update((list) => list.map((r) => (r.id === saved.id ? saved : r)));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected userLabel(p: AdminPrincipal): string {
    return p.displayName || p.email || p.sub;
  }
}

/** Leeres Datum → null; ein `YYYY-MM-DD`-Wert → ISO-UTC-Mitternacht. */
function isoOrNull(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.length === 10 ? `${trimmed}T00:00:00Z` : trimmed;
}
