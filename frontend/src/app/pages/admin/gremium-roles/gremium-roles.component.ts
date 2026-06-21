import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import {
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { GREMIUM_PERMISSIONS, type GremiumRole } from '../admin.models';
import type { TranslationKey } from '@core/i18n/translations';

interface RoleDraft {
  key: string;
  labelDe: string;
  labelEn: string;
  permissions: string[];
}

function emptyDraft(): RoleDraft {
  return { key: '', labelDe: '', labelEn: '', permissions: ['vote.cast'] };
}

/**
 * Gremium-Rollen-Katalog (#42): der **eigene** Rollensatz für Gremien, getrennt von
 * den globalen Rollen. CRUD über die Admin-API; Anlegen/Bearbeiten als Dialog (#19).
 * Die konkrete (zeitlich begrenzte) Zuordnung passiert je Gremium auf dessen
 * Mitglieder-Unterseite.
 */
@Component({
  selector: 'app-gremium-roles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    CapitalizePipe,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
    InputComponent,
    CheckboxComponent,
  ],
  templateUrl: './gremium-roles.component.html',
  styleUrl: './gremium-roles.component.scss',
})
export class GremiumRolesComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  /** Gremium, dessen Rollen hier verwaltet werden (#62 — Rollen sind pro Gremium). */
  private readonly gremiumId = this.route.snapshot.paramMap.get('id') as Uuid;

  protected readonly roles = signal<GremiumRole[]>([]);
  protected readonly draft = signal<RoleDraft | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly confirmDelete = signal<GremiumRole | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.gremiumRoles.col.name') },
    { key: 'key', label: this.i18n.translate('admin.gremiumRoles.col.key') },
    { key: 'permissions', label: this.i18n.translate('admin.gremiumRoles.permissions') },
    { key: 'actions', label: this.i18n.translate('admin.common.actions'), align: 'end', width: '7rem' },
  ]);

  protected readonly allPermissions = GREMIUM_PERMISSIONS;

  protected permLabel(p: string): TranslationKey {
    return `admin.gremiumPerm.${p}` as TranslationKey;
  }

  protected togglePerm(perm: string, on: boolean): void {
    this.draft.update((d) => {
      if (!d) return d;
      const set = new Set(d.permissions);
      if (on) set.add(perm);
      else set.delete(perm);
      return { ...d, permissions: GREMIUM_PERMISSIONS.filter((p) => set.has(p)) };
    });
  }

  constructor() {
    this.api.listGremiumRoles(this.gremiumId).subscribe((r) => this.roles.set(r));
  }

  protected label(r: GremiumRole | null): string {
    if (!r) return '';
    return r.name[this.i18n.locale()] ?? r.name['de'] ?? r.key;
  }

  protected openAdd(): void {
    this.editingId.set(null);
    this.draft.set(emptyDraft());
  }

  protected openEdit(i: number): void {
    const r = this.roles()[i];
    this.editingId.set(r.id);
    this.draft.set({
      key: r.key,
      labelDe: r.name['de'] ?? '',
      labelEn: r.name['en'] ?? '',
      permissions: [...(r.permissions ?? [])],
    });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingId.set(null);
  }

  protected patch<K extends keyof RoleDraft>(key: K, value: RoleDraft[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected save(): void {
    const d = this.draft();
    if (!d || !d.key.trim()) return;
    const name = { de: d.labelDe.trim() || d.key, en: d.labelEn.trim() || d.labelDe.trim() || d.key };
    const permissions = [...d.permissions];
    const id = this.editingId();
    const req = id
      ? this.api.updateGremiumRole(id, { name, permissions })
      : this.api.createGremiumRole(this.gremiumId, { key: d.key.trim(), name, permissions });
    req.subscribe({
      next: (saved) => {
        this.roles.update((list) =>
          id ? list.map((r) => (r.id === id ? saved : r)) : [...list, saved],
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected askDelete(r: GremiumRole): void {
    this.confirmDelete.set(r);
  }

  protected doDelete(): void {
    const r = this.confirmDelete();
    if (!r) return;
    this.api.deleteGremiumRole(r.id).subscribe({
      next: () => {
        this.roles.update((list) => list.filter((x) => x.id !== r.id));
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
