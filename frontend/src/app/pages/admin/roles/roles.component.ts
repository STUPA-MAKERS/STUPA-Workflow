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
} from '@stupa-makers/ui-kit';
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
  templateUrl: './roles.component.html',
  styleUrl: './roles.component.scss',
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

  // --- Umbenennen (Anzeigename; Key unveränderlich) ------------------------
  private readonly nameDrafts = signal<Record<string, { de: string; en: string }>>({});
  /** Aktueller Namens-Entwurf (initial aus dem aktuellen Label). */
  protected nameDraft(role: Role): { de: string; en: string } {
    return (
      this.nameDrafts()[role.id] ?? {
        de: role.label['de'] ?? '',
        en: role.label['en'] ?? '',
      }
    );
  }
  protected patchName(role: Role, lang: 'de' | 'en', value: string): void {
    const cur = this.nameDraft(role);
    this.nameDrafts.update((m) => ({ ...m, [role.id]: { ...cur, [lang]: value } }));
  }
  protected renameRole(role: Role): void {
    const d = this.nameDraft(role);
    this.api.renameRole(role.id, { de: d.de, en: d.en }).subscribe({
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
