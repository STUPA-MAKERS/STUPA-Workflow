import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminApiService } from '../admin-api.service';
import type { Gremium, GroupMapping, Role } from '../admin.models';

interface Row {
  id: string;
  oidcGroup: string;
  roleLabel: string;
  gremiumLabel: string;
}

/**
 * OIDC-Gruppen → Rolle(+ optional Gremium) Mappings (#5-4). Eigene Admin-Seite
 * (`/admin/group-mappings`, P `admin.roles`): beim Login werden OIDC-Gruppen des
 * Nutzers auf Plattform-Rollen abgebildet. Tabelle + Anlegen/Bearbeiten-Dialog.
 */
@Component({
  selector: 'app-group-mappings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
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

  private readonly mappings = signal<GroupMapping[]>([]);
  private readonly roles = signal<Role[]>([]);
  private readonly gremien = signal<Gremium[]>([]);

  readonly dialogOpen = signal(false);
  readonly editId = signal<string | null>(null);
  readonly oidcGroup = signal('');
  readonly roleId = signal('');
  /** '' = global (kein Gremium). */
  readonly gremiumId = signal('');
  readonly confirmId = signal<string | null>(null);

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'oidcGroup', label: this.i18n.translate('admin.groupMappings.oidcGroup') },
    { key: 'roleLabel', label: this.i18n.translate('admin.groupMappings.role') },
    { key: 'gremiumLabel', label: this.i18n.translate('admin.groupMappings.gremium') },
    { key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' },
  ]);
  readonly rowId = (r: unknown): string => (r as Row).id;

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.roles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );
  readonly gremiumOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.groupMappings.global') },
    ...this.gremien().map((g) => ({ value: g.id, label: g.name })),
  ]);

  readonly rows = computed<Row[]>(() => {
    const rolesById = new Map(this.roles().map((r) => [r.id, r]));
    const gremienById = new Map(this.gremien().map((g) => [g.id, g.name]));
    return this.mappings().map((m) => {
      const role = rolesById.get(m.roleId);
      return {
        id: m.id,
        oidcGroup: m.oidcGroup,
        roleLabel: role ? this.roleName(role) : m.roleId,
        gremiumLabel: m.gremiumId ? (gremienById.get(m.gremiumId) ?? m.gremiumId) : '',
      };
    });
  });

  constructor() {
    this.refresh();
    this.api.listRoles().subscribe({
      next: (r) => this.roles.set(r),
      error: () => this.roles.set([]),
    });
    this.api.listGremienOptions().subscribe({
      next: (g) => this.gremien.set(g),
      error: () => this.gremien.set([]),
    });
  }

  private refresh(): void {
    this.api.listGroupMappings().subscribe({
      next: (m) => this.mappings.set(m),
      error: () => {
        this.mappings.set([]);
        this.toast.error(this.i18n.translate('admin.groupMappings.loadFailed'));
      },
    });
  }

  private roleName(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  openAdd(): void {
    this.editId.set(null);
    this.oidcGroup.set('');
    this.roleId.set('');
    this.gremiumId.set('');
    this.dialogOpen.set(true);
  }

  openEdit(id: string): void {
    const m = this.mappings().find((x) => x.id === id);
    if (!m) return;
    this.editId.set(id);
    this.oidcGroup.set(m.oidcGroup);
    this.roleId.set(m.roleId);
    this.gremiumId.set(m.gremiumId ?? '');
    this.dialogOpen.set(true);
  }

  save(): void {
    const body = {
      oidcGroup: this.oidcGroup().trim(),
      roleId: this.roleId() as Uuid,
      gremiumId: this.gremiumId() ? (this.gremiumId() as Uuid) : null,
    };
    if (!body.oidcGroup || !body.roleId) return;
    const id = this.editId();
    const req = id
      ? this.api.updateGroupMapping(id as Uuid, body)
      : this.api.createGroupMapping(body);
    req.subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.groupMappings.saved'));
        this.dialogOpen.set(false);
        this.refresh();
      },
      error: () => this.toast.error(this.i18n.translate('admin.groupMappings.failed')),
    });
  }

  remove(): void {
    const id = this.confirmId();
    if (!id) return;
    this.api.deleteGroupMapping(id as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.groupMappings.deleted'));
        this.confirmId.set(null);
        this.refresh();
      },
      error: () => this.toast.error(this.i18n.translate('admin.groupMappings.failed')),
    });
  }
}
