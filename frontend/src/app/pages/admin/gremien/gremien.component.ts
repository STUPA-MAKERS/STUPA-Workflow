import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import {
  CD_VARIANTS,
  type Gremium,
  type GremiumCreateBody,
  type GremiumUpdateBody,
  slugify,
} from '../admin.models';

/** Edit form state of a gremium (the slug is generated automatically). */
interface GremiumForm {
  name: string;
  cdVariant: string;
  defaultLang: string;
  allowVoteDelegation: boolean;
  /** Lead time in minutes before meeting start for non-pool delegations. */
  delegationLeadMinutes: number;
  /** Allow delegation to externals (outside gremium/pool). */
  delegationAllowExternal: boolean;
  /** Default quorum in % of eligible voters; null = none. */
  quorumPercent: number | null;
  /** Extra protocol recipients, one address per line. */
  mailRecipients: string;
}

function emptyForm(): GremiumForm {
  return {
    name: '',
    cdVariant: 'stupa',
    defaultLang: 'de',
    allowVoteDelegation: false,
    delegationLeadMinutes: 0,
    delegationAllowExternal: false,
    quorumPercent: null,
    mailRecipients: '',
  };
}

/** Textarea content → address list (newlines/commas/semicolons as separators). */
function parseRecipients(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Gremien administration. Table of all gremien; create/edit via a **dialog** (not
 * inline). CD variant as a dropdown, the slug is generated automatically from the
 * name, vote delegation is a per-gremium setting. "Members" leads to the
 * **subpage** per gremium (`/admin/gremien/:id`).
 */
@Component({
  selector: 'app-admin-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    InputComponent,
    SelectComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
  ],
  templateUrl: './gremien.component.html',
  styleUrl: './gremien.component.scss',
})
export class AdminGremienComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremien = signal<Gremium[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  readonly saving = signal(false);
  readonly dialogOpen = signal(false);
  readonly editingId = signal<Uuid | null>(null);
  readonly form = signal<GremiumForm>(emptyForm());
  readonly confirmDelete = signal<Gremium | null>(null);
  readonly deleting = signal(false);

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.gremien.name') },
    { key: 'slug', label: this.i18n.translate('admin.gremien.slug') },
    { key: 'cdVariant', label: this.i18n.translate('admin.gremien.cdVariant') },
    { key: 'defaultLang', label: this.i18n.translate('admin.gremien.defaultLang') },
    { key: 'delegation', label: this.i18n.translate('admin.gremien.delegationShort'), align: 'start', width: '7rem' },
    { key: 'actions', label: this.i18n.translate('admin.gremien.actions'), align: 'end' },
  ]);
  readonly rowId = (g: unknown): string => (g as Gremium).id;

  readonly cdOptions: SelectOption[] = CD_VARIANTS.map((v) => ({ value: v, label: v }));
  readonly langOptions = computed<SelectOption[]>(() => [
    { value: 'de', label: this.i18n.translate('admin.gremien.langDe') },
    { value: 'en', label: this.i18n.translate('admin.gremien.langEn') },
  ]);

  /** Preview of the automatically generated slug. */
  readonly slugPreview = computed(() => slugify(this.form().name) || '—');

  constructor() {
    this.reload();
  }

  patch<K extends keyof GremiumForm>(key: K, value: GremiumForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  /** Lead-time input: empty/invalid → 0, otherwise a non-negative integer. */
  patchLead(value: number | string | null): void {
    const n = Math.round(Number(value));
    this.form.update((f) => ({
      ...f,
      delegationLeadMinutes: Number.isFinite(n) && n > 0 ? n : 0,
    }));
  }

  /** Quorum input: empty → null (no default), otherwise clamped to 0–100. */
  patchQuorum(value: number | string | null): void {
    let next: number | null;
    if (value === null || value === '' || value === undefined) {
      next = null;
    } else {
      const n = Math.round(Number(value));
      next = Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : null;
    }
    this.form.update((f) => ({ ...f, quorumPercent: next }));
  }

  openCreate(): void {
    this.editingId.set(null);
    this.form.set(emptyForm());
    this.dialogOpen.set(true);
  }

  openEdit(g: Gremium): void {
    this.editingId.set(g.id);
    this.form.set({
      name: g.name,
      cdVariant: g.cdVariant,
      defaultLang: g.defaultLang,
      allowVoteDelegation: g.allowVoteDelegation,
      delegationLeadMinutes: g.delegationLeadMinutes ?? 0,
      delegationAllowExternal: g.delegationAllowExternal ?? false,
      quorumPercent: g.quorumPercent ?? null,
      mailRecipients: '',
    });
    this.dialogOpen.set(true);
    // Load extra recipients (dedicated endpoint).
    this.api.getGremiumMailRecipients(g.id).subscribe({
      next: ({ recipients }) =>
        this.form.update((f) => ({ ...f, mailRecipients: recipients.join('\n') })),
      error: () => {},
    });
  }

  closeDialog(): void {
    this.dialogOpen.set(false);
  }

  submit(event: Event): void {
    event.preventDefault();
    const f = this.form();
    if (!f.name.trim() || this.saving()) return;
    this.saving.set(true);
    const id = this.editingId();
    if (id) {
      const body: GremiumUpdateBody = {
        name: f.name.trim(),
        cdVariant: f.cdVariant,
        defaultLang: f.defaultLang,
        allowVoteDelegation: f.allowVoteDelegation,
        delegationLeadMinutes: f.delegationLeadMinutes,
        delegationAllowExternal: f.delegationAllowExternal,
        quorumPercent: f.quorumPercent,
      };
      this.api.updateGremium(id, body).subscribe({
        next: () => this.saveRecipients(id, 'admin.gremien.toast.updated'),
        error: () => this.onSaveError(),
      });
    } else {
      const body: GremiumCreateBody = {
        name: f.name.trim(),
        slug: slugify(f.name) || f.name.trim().toLowerCase(),
        cdVariant: f.cdVariant,
        defaultLang: f.defaultLang,
        allowVoteDelegation: f.allowVoteDelegation,
        delegationLeadMinutes: f.delegationLeadMinutes,
        delegationAllowExternal: f.delegationAllowExternal,
        quorumPercent: f.quorumPercent,
      };
      this.api.createGremium(body).subscribe({
        next: (created) => this.saveRecipients(created.id, 'admin.gremien.toast.created'),
        error: () => this.onSaveError(),
      });
    }
  }

  /** Save extra protocol recipients after the base data. */
  private saveRecipients(
    id: Uuid,
    key: 'admin.gremien.toast.created' | 'admin.gremien.toast.updated',
  ): void {
    this.api.setGremiumMailRecipients(id, parseRecipients(this.form().mailRecipients)).subscribe({
      next: () => this.onSaved(key),
      error: () => this.onSaveError(),
    });
  }

  private onSaved(key: 'admin.gremien.toast.created' | 'admin.gremien.toast.updated'): void {
    this.saving.set(false);
    this.dialogOpen.set(false);
    this.toast.success(this.i18n.translate(key));
    this.reload();
  }

  private onSaveError(): void {
    this.saving.set(false);
    this.toast.error(this.i18n.translate('admin.gremien.toast.failed'));
  }

  askDelete(g: Gremium): void {
    this.confirmDelete.set(g);
  }

  doDelete(): void {
    const g = this.confirmDelete();
    if (!g || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteGremium(g.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.gremien.toast.deleted'));
        this.reload();
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('admin.gremien.toast.failed'));
      },
    });
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listGremien({ quiet: true }).subscribe({
      next: (g) => {
        this.gremien.set(g);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
