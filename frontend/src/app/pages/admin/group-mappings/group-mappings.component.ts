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
  template: `
    <header class="gm__head">
      <div>
        <h1 class="gm__title">{{ 'admin.groupMappings.title' | t }}</h1>
        <p class="gm__subtitle">{{ 'admin.groupMappings.subtitle' | t }}</p>
      </div>
      <app-button size="sm" (click)="openAdd()">{{ 'admin.groupMappings.add' | t }}</app-button>
    </header>

    <app-data-table
      [columns]="columns()"
      [rows]="rows()"
      [rowKey]="rowId"
      [emptyText]="'admin.groupMappings.empty' | t"
    >
      <ng-template appCell="gremiumLabel" let-r>
        @if ($any(r).gremiumLabel) {
          {{ $any(r).gremiumLabel }}
        } @else {
          <span class="gm__muted">{{ 'admin.groupMappings.global' | t }}</span>
        }
      </ng-template>
      <ng-template appCell="actions" let-r>
        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.edit' | t" (click)="openEdit($any(r).id)">
          <app-icon name="edit" />
        </app-button>
        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.delete' | t" (click)="confirmId.set($any(r).id)">
          <app-icon name="delete" />
        </app-button>
      </ng-template>
    </app-data-table>

    <!-- Anlegen/Bearbeiten -->
    <app-dialog
      [open]="dialogOpen()"
      [title]="(editId() ? 'admin.groupMappings.editTitle' : 'admin.groupMappings.add') | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="dialogOpen.set(false)"
    >
      <div class="gm__form">
        <label class="gm__lbl" for="gm-oidc">{{ 'admin.groupMappings.oidcGroup' | t }}</label>
        <input
          id="gm-oidc"
          class="gm__control"
          autocomplete="off"
          [placeholder]="'admin.groupMappings.oidcGroupPlaceholder' | t"
          [ngModel]="oidcGroup()"
          (ngModelChange)="oidcGroup.set($event)"
          name="oidcGroup"
        />
        <app-select
          [label]="'admin.groupMappings.role' | t"
          [placeholder]="'admin.groupMappings.rolePlaceholder' | t"
          [options]="roleOptions()"
          [ngModel]="roleId()"
          (ngModelChange)="roleId.set($event)"
          name="role"
        />
        <app-select
          [label]="'admin.groupMappings.gremium' | t"
          [options]="gremiumOptions()"
          [ngModel]="gremiumId()"
          (ngModelChange)="gremiumId.set($event)"
          name="gremium"
        />
      </div>
      <div dialog-footer class="gm__foot">
        <app-button variant="ghost" (click)="dialogOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!oidcGroup().trim() || !roleId()" (click)="save()">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Löschen -->
    <app-dialog
      [open]="!!confirmId()"
      [title]="'admin.groupMappings.deleteTitle' | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="confirmId.set(null)"
    >
      <p>{{ 'admin.groupMappings.deleteBody' | t }}</p>
      <div dialog-footer class="gm__foot">
        <app-button variant="ghost" (click)="confirmId.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" (click)="remove()">{{ 'action.delete' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .gm__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .gm__title {
        margin: 0;
      }
      .gm__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .gm__muted {
        color: var(--color-text-muted);
      }
      .gm__form {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .gm__lbl {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
      }
      .gm__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .gm__foot {
        display: flex;
        justify-content: flex-end;
        gap: var(--space-3);
      }
    `,
  ],
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
