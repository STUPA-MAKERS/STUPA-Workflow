import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import {
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  RowDetailDirective,
  ToastService,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import type { Role } from '../admin.models';

/** Entwurf für eine neue globale Rolle. */
interface RoleDraft {
  key: string;
  labelDe: string;
  labelEn: string;
}

/**
 * Rollen & Rechte (#21) als **Baum-Tabelle**: jede (globale) Rolle ist eine Zeile;
 * Aufklappen zeigt ihre Berechtigungen als Checkbox-Detail. Im selben View ein
 * **Dialog** zum Anlegen globaler Rollen. Die Admin-Rolle ist gesperrt (immer alle
 * Rechte). Gremium-Rollen werden pro Gremium verwaltet — hier nur globale.
 */
@Component({
  selector: 'app-admin-roles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    CapitalizePipe,
    ButtonComponent,
    CheckboxComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    RowDetailDirective,
    IconComponent,
  ],
  providers: [CapitalizePipe],
  template: `
    <section class="roles">
      <header class="roles__head">
        <div>
          <h1>{{ 'admin.roles.title' | t }}</h1>
          <p class="roles__sub">{{ 'admin.roles.subtitle' | t }}</p>
        </div>
        <app-button size="sm" (click)="openAdd()">{{ 'admin.roles.addGlobalRole' | t }}</app-button>
      </header>

      <app-data-table [columns]="columns()" [rows]="roles()" [rowKey]="rowId" [isExpanded]="rowExpanded" [clickable]="true" (rowClick)="onRowClick($event)">
        <ng-template appCell="name" let-r>
          <span class="roles__name-cell">
            <app-icon name="chevron-down" class="roles__chevron" [class.roles__chevron--open]="expanded().has($any(r).id)" [size]="16" />
            <span class="roles__name">{{ roleLabel($any(r)) | capitalize }}</span>
          </span>
        </ng-template>
        <ng-template appCell="key" let-r><span class="roles__key">{{ $any(r).key }}</span></ng-template>
        <ng-template appCell="perms" let-r>{{ $any(r).permissions.length }} / {{ permissions().length }}</ng-template>
        <ng-template appCell="actions" let-r>
          @if (canDelete($any(r))) {
            <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.roles.deleteRole' | t" (click)="$event.stopPropagation(); askDelete($any(r))"><app-icon name="delete" /></app-button>
          }
        </ng-template>

        <ng-template appRowDetail let-r>
          <div class="roles__detail">
            @if (isLocked($any(r))) {
              <p class="roles__locked">{{ 'admin.roles.adminLocked' | t }}</p>
              <div class="roles__grid">
                @for (perm of permissions(); track perm) {
                  <span class="roles__perm-on">✓ {{ perm }}</span>
                }
              </div>
            } @else {
              <fieldset class="roles__grid">
                @for (perm of permissions(); track perm) {
                  <app-checkbox
                    [ngModel]="$any(r).permissions.includes(perm)"
                    (ngModelChange)="togglePerm($any(r), perm, $event)"
                    [name]="$any(r).id + '-' + perm"
                  >{{ perm }}</app-checkbox>
                }
              </fieldset>
              <div class="roles__foot">
                <app-button size="sm" (click)="saveRole($any(r))">{{ 'action.save' | t }}</app-button>
              </div>
            }
          </div>
        </ng-template>
      </app-data-table>
    </section>

    <!-- Löschen bestätigen (#40) -->
    <app-dialog [open]="!!confirmRole()" [title]="'admin.roles.deleteRole' | t" [closeLabel]="'admin.gremien.cancel' | t" (closed)="confirmRole.set(null)">
      @if (confirmRole(); as r) {
        <p>{{ 'admin.roles.deleteConfirm' | t: { role: roleLabel(r) } }}</p>
      }
      <div dialog-footer class="roles__foot">
        <app-button variant="ghost" (click)="confirmRole.set(null)">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button variant="danger" (click)="confirmDelete()">{{ 'admin.roles.deleteRole' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Globale Rolle anlegen (Dialog, #21/#19) -->
    <app-dialog [open]="addOpen()" [title]="'admin.roles.addGlobalRole' | t" [closeLabel]="'admin.gremien.cancel' | t" (closed)="addOpen.set(false)">
      <div class="roles__add">
        <label class="roles__lbl">{{ 'admin.roles.roleKey' | t }}
          <input [ngModel]="draft().key" (ngModelChange)="patchDraft('key', $event)" name="roleKey" placeholder="z. B. referent" /></label>
        <label class="roles__lbl">{{ 'admin.common.labelDe' | t }}
          <input [ngModel]="draft().labelDe" (ngModelChange)="patchDraft('labelDe', $event)" name="roleLabelDe" /></label>
        <label class="roles__lbl">{{ 'admin.common.labelEn' | t }}
          <input [ngModel]="draft().labelEn" (ngModelChange)="patchDraft('labelEn', $event)" name="roleLabelEn" /></label>
      </div>
      <div dialog-footer class="roles__foot">
        <app-button variant="ghost" (click)="addOpen.set(false)">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button [disabled]="!draft().key.trim()" (click)="createRole()">{{ 'admin.gremien.add' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      .roles {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .roles__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .roles__sub {
        color: var(--color-text-muted);
      }
      .roles__name-cell {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .roles__chevron {
        color: var(--color-text-muted);
        transition: transform var(--motion-fast) var(--ease-standard);
      }
      .roles__chevron--open {
        transform: rotate(180deg);
        color: var(--color-primary);
      }
      .roles__name {
        font-weight: var(--fw-medium);
      }
      .roles__row-actions {
        display: inline-flex;
        gap: var(--space-1);
        justify-content: flex-end;
      }
      .roles__key {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .roles__detail {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        padding: var(--space-4);
      }
      .roles__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
        align-items: center;
        gap: var(--space-2);
        margin: 0;
        padding: 0;
        border: 0;
      }
      .roles__foot {
        display: flex;
        justify-content: flex-end;
        gap: var(--space-3);
      }
      .roles__locked {
        margin: 0;
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .roles__perm-on {
        font-size: var(--fs-sm);
        color: var(--color-success);
      }
      .roles__add {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .roles__lbl {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
      }
      .roles__lbl input {
        height: var(--control-height);
        box-sizing: border-box;
        padding: 0 var(--space-3);
        font: inherit;
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
      }
    `,
  ],
})
export class AdminRolesComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly roles = signal<Role[]>([]);
  protected readonly permissions = signal<string[]>([]);
  protected readonly expanded = signal<Set<string>>(new Set());
  protected readonly addOpen = signal(false);
  protected readonly draft = signal<RoleDraft>({ key: '', labelDe: '', labelEn: '' });
  /** Rolle, deren Löschung gerade bestätigt wird (#40). */
  protected readonly confirmRole = signal<Role | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.roles.col.name') },
    { key: 'key', label: this.i18n.translate('admin.roles.col.key') },
    { key: 'perms', label: this.i18n.translate('admin.roles.col.perms') },
    { key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' },
  ]);
  protected readonly rowId = (r: unknown): string => (r as Role).id;
  protected readonly rowExpanded = (r: unknown): boolean => this.expanded().has((r as Role).id);

  constructor() {
    this.api.listRoles().subscribe((r) => this.roles.set(r));
    this.api.listPermissions().subscribe((p) => this.permissions.set(p));
  }

  protected roleLabel(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  protected isLocked(role: Role): boolean {
    return role.key === 'admin';
  }

  /** Alle Rollen außer admin/member sind löschbar (#38). */
  protected canDelete(role: Role): boolean {
    return role.key !== 'admin' && role.key !== 'member';
  }

  /** Zeilen-Klick klappt die Rechte auf/zu (#40). */
  protected onRowClick(row: unknown): void {
    this.toggle((row as Role).id);
  }

  protected askDelete(role: Role): void {
    this.confirmRole.set(role);
  }

  protected confirmDelete(): void {
    const role = this.confirmRole();
    if (!role) return;
    this.confirmRole.set(null);
    this.api.deleteRole(role.id).subscribe({
      next: () => {
        this.roles.update((list) => list.filter((r) => r.id !== role.id));
        this.toast.success(this.i18n.translate('admin.roles.deleted'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected toggle(id: string): void {
    this.expanded.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected togglePerm(role: Role, perm: string, on: boolean): void {
    const permissions = on
      ? [...role.permissions, perm]
      : role.permissions.filter((p) => p !== perm);
    this.roles.update((list) => list.map((r) => (r.id === role.id ? { ...r, permissions } : r)));
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

  // --- globale Rolle anlegen -----------------------------------------------
  protected openAdd(): void {
    this.draft.set({ key: '', labelDe: '', labelEn: '' });
    this.addOpen.set(true);
  }

  protected patchDraft<K extends keyof RoleDraft>(key: K, value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
  }

  protected createRole(): void {
    const d = this.draft();
    if (!d.key.trim()) return;
    const label: Record<string, string> = {};
    if (d.labelDe.trim()) label['de'] = d.labelDe.trim();
    if (d.labelEn.trim()) label['en'] = d.labelEn.trim();
    this.api.createRole({ key: d.key.trim(), label, permissions: [] }).subscribe({
      next: (role) => {
        this.roles.update((list) => [...list, role]);
        this.addOpen.set(false);
        this.toast.success(this.i18n.translate('admin.roles.created'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
