import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { NoteComponent, PageHeaderComponent, SkeletonComponent } from '@shared/ui';
import {
  ButtonComponent,
  CheckboxComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { ROLE_KEY_PATTERN, type Role } from '../admin.models';
import { permissionSections } from './permission-sections';

/** Draft for a new global role. */
interface RoleDraft {
  key: string;
  labelDe: string;
  labelEn: string;
}

/** The fixed global roles: the server refuses to delete them (409). */
const FIXED_ROLES = new Set(['admin', 'member']);

/**
 * Roles and rights (boards Admin-Rollen, Admin-Rollen-Dialog). One expandable row per
 * global role.
 *
 * The head of a row shows the name, "fest" for the fixed roles `admin` and `member`
 * (N40), the key and "n / total" of the catalogue. An open row renames the role (the
 * key never changes) and edits its rights in sections. The sections come from the
 * catalogue of the API (`GET /admin/permissions`), so a removed key never shows. The
 * admin role always holds every right and is read-only here; the rights of `member`
 * can change. A dialog creates a role; the key must match `ROLE_KEY_PATTERN` (A10), and
 * the server answers 422 for any other key. This page lists global roles only; the
 * gremien pages manage the roles of a gremium.
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
    IconComponent,
    InputComponent,
    NoteComponent,
    PageHeaderComponent,
    SkeletonComponent,
  ],
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
  /** The trimmed draft key matches ROLE_KEY_PATTERN. The server refuses other keys with 422. */
  protected readonly keyValid = computed(() => ROLE_KEY_PATTERN.test(this.draft().key.trim()));
  /** The error text under the key input. Empty for a blank key or a valid key. */
  protected readonly keyError = computed(() => {
    if (this.serverKeyError()) return this.serverKeyError();
    return this.draft().key.trim() && !this.keyValid()
      ? this.i18n.translate('admin.common.roleKeyInvalid')
      : '';
  });
  /** The answer of the server to the last create, shown under the key (409, 422). */
  private readonly serverKeyError = signal('');
  protected readonly creating = signal(false);
  /** The role that waits for a delete confirmation. */
  protected readonly confirmRole = signal<Role | null>(null);

  /** True until the first answer, so the table does not claim there are no roles. */
  protected readonly loading = signal(true);

  constructor() {
    this.api.listRoles().subscribe({
      next: (r) => {
        this.roles.set(r);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
    this.api.listPermissions().subscribe((p) => this.permissions.set(p));
  }

  protected roleLabel(role: Role): string {
    return role.label[this.i18n.locale()] ?? role.label['de'] ?? role.key;
  }

  /** The admin role holds every right; its rights are read-only here. */
  protected isLocked(role: Role): boolean {
    return role.key === 'admin';
  }

  /** A fixed role (`admin`, `member`) cannot be deleted. */
  protected isFixed(role: Role): boolean {
    return FIXED_ROLES.has(role.key);
  }

  /** The rights of the catalogue in sections. */
  protected readonly sections = computed(() => permissionSections(this.permissions()));

  /** The number of catalogue rights the role holds. The admin role holds them all. */
  protected count(role: Role): number {
    if (this.isLocked(role)) return this.permissions().length;
    const catalogue = new Set(this.permissions());
    return role.permissions.filter((p) => catalogue.has(p)).length;
  }

  protected isOpen(role: Role): boolean {
    return this.expanded().has(role.id);
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
    // Only keys of the catalogue go out: a key the server removed would make it refuse
    // the whole list. Without a catalogue the button is disabled.
    const catalogue = new Set(this.permissions());
    const permissions = role.permissions.filter((p) => catalogue.has(p));
    this.api.saveRolePermissions(role.id, permissions).subscribe({
      next: (saved) => {
        this.roles.update((list) => list.map((r) => (r.id === saved.id ? saved : r)));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  // A rename changes the display name only. The key never changes.
  private readonly nameDrafts = signal<Record<string, { de: string; en: string }>>({});
  /** The current name draft. It starts from the current label. */
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

  protected openAdd(): void {
    this.draft.set({ key: '', labelDe: '', labelEn: '' });
    this.serverKeyError.set('');
    this.addOpen.set(true);
  }

  protected patchDraft<K extends keyof RoleDraft>(key: K, value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
    if (key === 'key') this.serverKeyError.set('');
  }

  /** Create the role and open its row, where the rights are set next. */
  protected createRole(): void {
    const d = this.draft();
    if (!this.keyValid() || this.creating()) return;
    const label: Record<string, string> = {};
    if (d.labelDe.trim()) label['de'] = d.labelDe.trim();
    if (d.labelEn.trim()) label['en'] = d.labelEn.trim();
    this.creating.set(true);
    this.api.createRole({ key: d.key.trim(), label, permissions: [] }).subscribe({
      next: (role) => {
        this.creating.set(false);
        this.roles.update((list) => [...list, role]);
        this.expanded.update((set) => new Set(set).add(role.id));
        this.addOpen.set(false);
        this.toast.success(this.i18n.translate('admin.roles.created'));
      },
      error: (err: { status?: number }) => {
        this.creating.set(false);
        // A wrong or taken key is an answer about the field, so it shows there.
        if (err?.status === 422) {
          this.serverKeyError.set(this.i18n.translate('admin.common.roleKeyInvalid'));
        } else if (err?.status === 409) {
          this.serverKeyError.set(this.i18n.translate('admin.roles.keyTaken'));
        } else {
          this.toast.error(this.i18n.translate('admin.common.saveFailed'));
        }
      },
    });
  }
}
