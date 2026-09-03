import { SlicePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  RowDetailDirective,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { HScrollSyncDirective } from '@shared/h-scroll-sync.directive';
import type { AdminPrincipal, Role, RoleAssignment, RoleAssignmentPatch } from '../admin.models';

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
 * Users and roles as a table. The table follows the Nextcloud user table.
 *
 * Each row holds one principal: name, e-mail, OIDC subject, the assigned roles as
 * revocable tags, and the last login. A per-row expandable mini-form assigns a role. It
 * takes the role and an optional time-zone-aware validity window that models a
 * substitution. This page does not maintain Gremium membership on purpose. The gremien
 * administration maintains it per Gremium. The role permissions have their own page
 * (`/admin/roles`). The frontend only gates the UX. The server stays authoritative.
 */
@Component({
  selector: 'app-admin-users',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    HScrollSyncDirective,
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
    DialogComponent,
    RowDetailDirective,
    IconComponent,
    PageHeaderComponent,
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
  private readonly route = inject(ActivatedRoute);

  /** OIDC `sub` of the logged-in user. The view uses it to block self-deactivation. */
  protected readonly mySub = computed(() => this.auth.principal()?.sub ?? null);

  protected readonly query = signal('');
  protected readonly principals = signal<AdminPrincipal[]>([]);
  protected readonly roles = signal<Role[]>([]);
  protected readonly drafts = signal<Record<string, AssignDraft>>({});
  /** The rows that show the expanded assign-role form. */
  protected readonly expanded = signal<Set<string>>(new Set());

  /** The assignment being edited, plus its dialog form state. */
  protected readonly editing = signal<RoleAssignment | null>(null);
  protected readonly editDraft = signal<AssignDraft>(emptyDraft());
  protected readonly savingEdit = signal(false);

  /** `admin.users` gates the whole page server-side. The controls follow it, so
   *  no row action is offered that would answer 403. */
  protected readonly canManageUsers = computed(() => this.auth.can('admin.users'));

  protected readonly rolesById = computed(() => new Map(this.roles().map((r) => [r.id, r])));

  protected readonly roleOptions = computed<SelectOption[]>(() =>
    this.roles().map((r) => ({
      value: r.id,
      label: this.capitalize.transform(this.roleLabel(r.id)),
    })),
  );

  /**
   * Widths are floors: the table scrolls rather than crushing a column. Without them the
   * name column asked for 22rem and was measured at 107px, so every name broke onto two
   * lines and every row was a different height.
   */
  /**
   * True until the first answer. Without it the table showed "Keine Treffer" while the
   * request was still out, which asserts there is nothing when nothing has arrived yet.
   */
  protected readonly loading = signal(true);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.users.col.name'), width: '14rem' },
    // Long enough for a full university address without a mid-domain break.
    { key: 'email', label: this.i18n.translate('admin.users.col.email'), width: '22rem' },
    { key: 'roles', label: this.i18n.translate('admin.users.col.roles'), width: '20rem' },
    { key: 'lastLogin', label: this.i18n.translate('admin.users.col.lastLogin'), width: '9rem' },
    {
      key: 'actions',
      label: this.i18n.translate('admin.users.col.actions'),
      align: 'end',
      // Pinned, so the row's actions stay reachable while the rest scrolls under them.
      sticky: 'end',
      width: '7rem',
    },
  ]);

  /** Roles column: global roles only, without a Gremium scope. */
  protected globalAssignments(p: AdminPrincipal): RoleAssignment[] {
    return p.assignments.filter((a) => !a.gremiumId);
  }
  protected readonly rowId = (p: unknown): string => (p as AdminPrincipal).id;
  /** Detail row with the assign form for an expanded principal. */
  protected readonly rowExpanded = (p: unknown): boolean =>
    this.isExpanded((p as AdminPrincipal).id);

  constructor() {
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    // `/admin/users?q=…` is where a global-search hit on a person lands. Without it the
    // hit opened the unfiltered list and the reader searched the same name twice.
    //
    // The subscription and not one read of the snapshot: the palette can send us here
    // while we are already here, and a hit on another person changes only the query
    // string. The router keeps this component, so a snapshot read would never run again.
    // The first emission arrives before the initial search, so there is one request.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      const q = qp.get('q') ?? '';
      if (q === this.query()) return;
      this.query.set(q);
      this.search();
    });
    this.search();
  }

  protected search(): void {
    this.loading.set(true);
    this.api.listPrincipals(this.query()).subscribe({
      next: (list) => {
        this.principals.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.toast.error(this.i18n.translate('admin.users.loadFailed'));
      },
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

  /** Protected roles admin and member. The view shows no revoke cross for them. */
  protected isAdminRole(roleId: string): boolean {
    const key = this.rolesById().get(roleId)?.key;
    return key === 'admin' || key === 'member';
  }

  /** The account of the logged-in user. The view blocks a deactivation of it. */
  protected isSelf(p: AdminPrincipal): boolean {
    return this.mySub() !== null && p.sub === this.mySub();
  }

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

  /** Open the edit dialog for one assignment. A date arrives as ISO. The
   *  datepicker needs the `YYYY-MM-DD` part only. */
  protected openEdit(assignment: RoleAssignment): void {
    this.editDraft.set({
      roleId: assignment.roleId,
      validFrom: (assignment.validFrom ?? '').slice(0, 10),
      validUntil: (assignment.validUntil ?? '').slice(0, 10),
    });
    this.editing.set(assignment);
  }

  protected closeEdit(): void {
    this.editing.set(null);
  }

  protected patchEdit(patch: Partial<AssignDraft>): void {
    this.editDraft.update((d) => ({ ...d, ...patch }));
  }

  /**
   * Save the changed assignment.
   *
   * The route treats a missing field as "do not touch", so an emptied date is
   * left out instead of sent as null. The dialog states that, because clearing
   * an expiry needs a revoke and a fresh assignment.
   */
  protected saveEdit(): void {
    const assignment = this.editing();
    const draft = this.editDraft();
    if (!assignment || !draft.roleId || this.savingEdit()) return;
    const patch: RoleAssignmentPatch = {};
    if (draft.roleId !== assignment.roleId) patch.roleId = draft.roleId;
    const from = isoOrNull(draft.validFrom);
    if (from) patch.validFrom = from;
    const until = isoOrNull(draft.validUntil);
    if (until) patch.validUntil = until;
    if (!Object.keys(patch).length) {
      this.editing.set(null);
      return;
    }
    this.savingEdit.set(true);
    this.api.updateRoleAssignment(assignment.id, patch).subscribe({
      next: () => {
        this.savingEdit.set(false);
        this.editing.set(null);
        this.toast.success(this.i18n.translate('admin.users.editSaved'));
        this.search();
      },
      error: (err: { status?: number }) => {
        this.savingEdit.set(false);
        // 403 = the self-lockout guard. An admin must not change their own
        // admin assignment. Name that reason instead of a generic failure.
        const key = err.status === 403 ? 'admin.users.editSelfBlocked' : 'admin.users.editFailed';
        this.toast.error(this.i18n.translate(key));
      },
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

/** An empty date becomes null. A `YYYY-MM-DD` value becomes ISO UTC midnight. */
function isoOrNull(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.length === 10 ? `${trimmed}T00:00:00Z` : trimmed;
}
