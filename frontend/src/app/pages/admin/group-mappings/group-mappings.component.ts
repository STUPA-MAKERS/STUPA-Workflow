import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import type { Observable } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type {
  Gremium,
  GremiumMembershipMapping,
  GremiumRole,
  GremiumRoleMapping,
  GroupMapping,
  Role,
} from '../admin.models';

/** The three separate mapping kinds. Each has its own table and dialog. */
export type MappingKind = 'global' | 'membership' | 'role';

interface GlobalRow {
  id: string;
  oidcGroup: string;
  roleLabel: string;
}

interface MembershipRow {
  id: string;
  oidcGroup: string;
  gremiumLabel: string;
}

interface RoleRow {
  id: string;
  oidcGroup: string;
  gremiumLabel: string;
  roleLabel: string;
}

/** The RBAC resolver reserves this group prefix. The backend refuses it with 422. */
const RESERVED_GROUP_PREFIX = 'vote:';

/**
 * OIDC group mappings at `/admin/group-mappings` (P `admin.group_mappings`).
 *
 * At each login the platform reads the OIDC groups of the person. Three separate
 * mappings use them, and they do not depend on each other:
 *
 * 1. group → global role,
 * 2. group → gremium membership (default gremium role `member`),
 * 3. group → gremium role. It applies only to members of that gremium (2) and
 *    never gives a membership. If more than one applies in a gremium, the role
 *    with the most permissions wins.
 *
 * Nobody sets a membership or a role by hand. The frontend only gates the UX. The
 * backend stays authoritative.
 */
@Component({
  selector: 'app-group-mappings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    FormsModule,
    RouterLink,
    TranslatePipe,
    PageHeaderComponent,
    BadgeComponent,
    ButtonComponent,
    SelectComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
  ],
  templateUrl: './group-mappings.component.html',
  styleUrl: './group-mappings.component.scss',
})
export class GroupMappingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);

  /** The link to the gremium roles page needs its own permission. */
  protected readonly canManageGremiumRoles = computed(() => this.auth.can('admin.gremium_roles'));

  // --- data --------------------------------------------------------------------

  private readonly globalMappings = signal<GroupMapping[]>([]);
  private readonly membershipMappings = signal<GremiumMembershipMapping[]>([]);
  private readonly roleMappings = signal<GremiumRoleMapping[]>([]);
  private readonly roles = signal<Role[]>([]);
  private readonly gremien = signal<Gremium[]>([]);
  /** Gremium roles per gremium id. The page loads them on demand. */
  private readonly gremiumRoles = signal<ReadonlyMap<string, GremiumRole[]>>(new Map());

  /**
   * True until the first answer. Without it a table shows its empty text while the
   * request is still out, which asserts there is nothing when nothing has arrived yet.
   */
  protected readonly loading = signal<Record<MappingKind, boolean>>({
    global: true,
    membership: true,
    role: true,
  });

  // --- dialog state ------------------------------------------------------------

  /** The open add/edit dialog, or null. */
  readonly dialog = signal<MappingKind | null>(null);
  /** null = the dialog creates a new mapping. */
  readonly editId = signal<string | null>(null);
  readonly oidcGroup = signal('');
  readonly roleId = signal('');
  readonly gremiumId = signal('');
  readonly gremiumRoleId = signal('');
  readonly saving = signal(false);
  /** The mapping to delete, after the confirmation. */
  readonly confirm = signal<{ kind: MappingKind; id: string } | null>(null);

  /** The group name uses the reserved prefix. The dialog says so before the 422. */
  readonly groupReserved = computed(() =>
    this.oidcGroup().trim().startsWith(RESERVED_GROUP_PREFIX),
  );

  readonly valid = computed(() => {
    const kind = this.dialog();
    if (!kind || !this.oidcGroup().trim() || this.groupReserved()) return false;
    if (kind === 'global') return !!this.roleId();
    if (kind === 'membership') return !!this.gremiumId();
    return !!this.gremiumRoleId();
  });

  // --- tables ------------------------------------------------------------------

  private readonly groupCol = computed<ColumnDef>(() => ({
    key: 'oidcGroup',
    label: this.i18n.translate('admin.groupMappings.oidcGroup'),
    card: 'title',
  }));
  private readonly gremiumCol = computed<ColumnDef>(() => ({
    key: 'gremiumLabel',
    label: this.i18n.translate('admin.groupMappings.gremium'),
  }));
  private readonly actionsCol = computed<ColumnDef>(() => ({
    key: 'actions',
    label: this.i18n.translate('admin.users.col.actions'),
    align: 'end',
  }));

  readonly globalColumns = computed<ColumnDef[]>(() => [
    this.groupCol(),
    { key: 'roleLabel', label: this.i18n.translate('admin.groupMappings.role') },
    this.actionsCol(),
  ]);
  readonly membershipColumns = computed<ColumnDef[]>(() => [
    this.groupCol(),
    this.gremiumCol(),
    this.actionsCol(),
  ]);
  readonly roleColumns = computed<ColumnDef[]>(() => [
    this.groupCol(),
    this.gremiumCol(),
    { key: 'roleLabel', label: this.i18n.translate('admin.groupMappings.gremiumRole') },
    this.actionsCol(),
  ]);
  readonly rowId = (r: unknown): string => (r as { id: string }).id;

  private readonly gremienById = computed(
    () => new Map(this.gremien().map((g) => [g.id, g.name])),
  );

  readonly globalRows = computed<GlobalRow[]>(() => {
    const rolesById = new Map(this.roles().map((r) => [r.id, r]));
    return this.globalMappings().map((m) => {
      const role = rolesById.get(m.roleId);
      return {
        id: m.id,
        oidcGroup: m.oidcGroup,
        roleLabel: role ? this.roleName(role) : this.unknown(),
      };
    });
  });

  readonly membershipRows = computed<MembershipRow[]>(() =>
    this.membershipMappings().map((m) => ({
      id: m.id,
      oidcGroup: m.oidcGroup,
      gremiumLabel: this.gremiumName(m.gremiumId),
    })),
  );

  readonly roleRows = computed<RoleRow[]>(() => {
    const byGremium = this.gremiumRoles();
    return this.roleMappings().map((m) => {
      const role = byGremium.get(m.gremiumId)?.find((r) => r.id === m.gremiumRoleId);
      return {
        id: m.id,
        oidcGroup: m.oidcGroup,
        gremiumLabel: this.gremiumName(m.gremiumId),
        roleLabel: role ? this.gremiumRoleName(role) : this.unknown(),
      };
    });
  });

  // --- dialog options ----------------------------------------------------------

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.roles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );
  readonly gremiumOptions = computed<SelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );
  /** The roles of the gremium chosen in the role dialog. undefined = still loading. */
  readonly dialogGremiumRoles = computed<GremiumRole[] | undefined>(() => {
    const gid = this.gremiumId();
    return gid ? this.gremiumRoles().get(gid) : [];
  });
  readonly gremiumRoleOptions = computed<SelectOption[]>(() =>
    (this.dialogGremiumRoles() ?? []).map((r) => ({ value: r.id, label: this.gremiumRoleName(r) })),
  );

  constructor() {
    this.api.listRoles().subscribe({
      next: (r) => this.roles.set(r),
      error: () => this.roles.set([]),
    });
    this.api.listGremienOptions().subscribe({
      next: (g) => this.gremien.set(g),
      error: () => this.gremien.set([]),
    });
    this.refresh('global');
    this.refresh('membership');
    this.refresh('role');
  }

  // --- loading -----------------------------------------------------------------

  private refresh(kind: MappingKind): void {
    const done = (): void => this.loading.update((l) => ({ ...l, [kind]: false }));
    const fail = (): void => {
      done();
      this.toast.error(this.i18n.translate('admin.groupMappings.loadFailed'));
    };
    if (kind === 'global') {
      this.api.listGroupMappings().subscribe({
        next: (m) => {
          this.globalMappings.set(m);
          done();
        },
        error: fail,
      });
    } else if (kind === 'membership') {
      this.api.listMembershipMappings().subscribe({
        next: (m) => {
          this.membershipMappings.set(m);
          done();
        },
        error: fail,
      });
    } else {
      this.api.listRoleMappings().subscribe({
        next: (m) => {
          this.roleMappings.set(m);
          for (const gid of new Set(m.map((x) => x.gremiumId))) this.loadGremiumRoles(gid);
          done();
        },
        error: fail,
      });
    }
  }

  /** Load the roles of one gremium once. A failed load gives an empty list. */
  private loadGremiumRoles(gremiumId: string): void {
    if (this.gremiumRoles().has(gremiumId)) return;
    this.api.listGremiumRoles(gremiumId as Uuid, { quiet: true }).subscribe({
      next: (r) => this.setGremiumRoles(gremiumId, r),
      error: () => this.setGremiumRoles(gremiumId, []),
    });
  }

  private setGremiumRoles(gremiumId: string, roles: GremiumRole[]): void {
    this.gremiumRoles.update((m) => new Map(m).set(gremiumId, roles));
  }

  // --- labels ------------------------------------------------------------------

  private unknown(): string {
    return this.i18n.translate('admin.groupMappings.unknown');
  }

  private gremiumName(id: string): string {
    return this.gremienById().get(id) ?? this.unknown();
  }

  private roleName(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  private gremiumRoleName(role: GremiumRole): string {
    return role.name[this.i18n.locale()] ?? role.name['de'] ?? role.key;
  }

  /** The i18n key of one text of one section, e.g. `admin.groupMappings.role.add`. */
  private key(kind: MappingKind, suffix: 'add' | 'editTitle' | 'deleteBody'): TranslationKey {
    return `admin.groupMappings.${kind}.${suffix}` as TranslationKey;
  }

  protected readonly dialogTitle = computed<TranslationKey>(() => {
    const kind = this.dialog();
    return kind ? this.key(kind, this.editId() ? 'editTitle' : 'add') : 'admin.groupMappings.title';
  });

  protected readonly confirmBody = computed<TranslationKey>(() => {
    const c = this.confirm();
    return c ? this.key(c.kind, 'deleteBody') : 'admin.groupMappings.title';
  });

  // --- dialog ------------------------------------------------------------------

  openAdd(kind: MappingKind): void {
    this.editId.set(null);
    this.oidcGroup.set('');
    this.roleId.set('');
    this.gremiumId.set('');
    this.gremiumRoleId.set('');
    this.saving.set(false);
    this.dialog.set(kind);
  }

  openEdit(kind: MappingKind, id: string): void {
    const m = this.find(kind, id);
    if (!m) return;
    this.openAdd(kind);
    this.editId.set(id);
    this.oidcGroup.set(m.oidcGroup);
    if ('roleId' in m) this.roleId.set(m.roleId);
    if ('gremiumId' in m) this.gremiumId.set(m.gremiumId);
    if ('gremiumRoleId' in m) {
      this.loadGremiumRoles(m.gremiumId);
      this.gremiumRoleId.set(m.gremiumRoleId);
    }
  }

  private find(
    kind: MappingKind,
    id: string,
  ): GroupMapping | GremiumMembershipMapping | GremiumRoleMapping | undefined {
    const list =
      kind === 'global'
        ? this.globalMappings()
        : kind === 'membership'
          ? this.membershipMappings()
          : this.roleMappings();
    return (list as { id: string }[]).find((x) => x.id === id) as
      | GroupMapping
      | GremiumMembershipMapping
      | GremiumRoleMapping
      | undefined;
  }

  /** The gremium select of the role dialog only filters the role list. */
  onDialogGremium(gremiumId: string): void {
    if (gremiumId === this.gremiumId()) return;
    this.gremiumId.set(gremiumId);
    this.gremiumRoleId.set('');
    if (this.dialog() === 'role' && gremiumId) this.loadGremiumRoles(gremiumId);
  }

  closeDialog(): void {
    this.dialog.set(null);
  }

  save(): void {
    const kind = this.dialog();
    if (!kind || !this.valid() || this.saving()) return;
    const id = this.editId() as Uuid | null;
    const oidcGroup = this.oidcGroup().trim();
    let req: Observable<unknown>;
    if (kind === 'global') {
      const body = { oidcGroup, roleId: this.roleId() as Uuid };
      req = id ? this.api.updateGroupMapping(id, body) : this.api.createGroupMapping(body);
    } else if (kind === 'membership') {
      const body = { oidcGroup, gremiumId: this.gremiumId() as Uuid };
      req = id ? this.api.updateMembershipMapping(id, body) : this.api.createMembershipMapping(body);
    } else {
      const body = { oidcGroup, gremiumRoleId: this.gremiumRoleId() as Uuid };
      req = id ? this.api.updateRoleMapping(id, body) : this.api.createRoleMapping(body);
    }
    this.saving.set(true);
    req.subscribe({
      next: () => {
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.groupMappings.saved'));
        this.dialog.set(null);
        this.refresh(kind);
      },
      // The dialog stays open, so the admin can correct the input.
      error: (err: { status?: number }) => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate(this.errorKey(err?.status)));
      },
    });
  }

  private errorKey(status: number | undefined): TranslationKey {
    if (status === 409) return 'admin.groupMappings.conflict';
    if (status === 422) return 'admin.groupMappings.invalid';
    if (status === 404) return 'admin.groupMappings.notFound';
    return 'admin.groupMappings.failed';
  }

  // --- delete ------------------------------------------------------------------

  askDelete(kind: MappingKind, id: string): void {
    this.confirm.set({ kind, id });
  }

  remove(): void {
    const c = this.confirm();
    if (!c) return;
    const id = c.id as Uuid;
    const req =
      c.kind === 'global'
        ? this.api.deleteGroupMapping(id)
        : c.kind === 'membership'
          ? this.api.deleteMembershipMapping(id)
          : this.api.deleteRoleMapping(id);
    req.subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.groupMappings.deleted'));
        this.confirm.set(null);
        this.refresh(c.kind);
      },
      error: () => this.toast.error(this.i18n.translate('admin.groupMappings.failed')),
    });
  }
}
