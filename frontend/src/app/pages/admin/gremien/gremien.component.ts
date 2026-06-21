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

/** Editier-Formularzustand eines Gremiums (Slug wird automatisch erzeugt). */
interface GremiumForm {
  name: string;
  cdVariant: string;
  defaultLang: string;
  allowVoteDelegation: boolean;
  /** Vorlauf in Minuten vor Sitzungsbeginn für Nicht-Pool-Delegationen (#delegation-rework). */
  delegationLeadMinutes: number;
  /** Delegation an Externe (außerhalb Gremium/Pool) erlauben. */
  delegationAllowExternal: boolean;
  /** Default-Quorum in % der Stimmberechtigten; null = keins. */
  quorumPercent: number | null;
  /** Zusatz-Protokoll-Empfänger, eine Adresse je Zeile (#protocol-recipients). */
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

/** Textarea-Inhalt → Adressliste (Zeilen/Kommas/Semikolons als Trenner). */
function parseRecipients(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Gremien-Verwaltung (#18). Tabelle aller Gremien; Anlegen/Bearbeiten über einen
 * **Dialog** (nicht inline). CD-Variante als Dropdown, der Slug wird automatisch
 * aus dem Namen erzeugt, Stimm-Delegation ist eine Gremium-Einstellung (#14).
 * »Mitglieder« führt auf die **Unterseite** je Gremium (`/admin/gremien/:id`).
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

  /** Vorschau des automatisch erzeugten Slugs. */
  readonly slugPreview = computed(() => slugify(this.form().name) || '—');

  constructor() {
    this.reload();
  }

  patch<K extends keyof GremiumForm>(key: K, value: GremiumForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  /** Vorlauf-Eingabe (#delegation-rework): leer/ungültig → 0, sonst ≥ 0 ganzzahlig. */
  patchLead(value: number | string | null): void {
    const n = Math.round(Number(value));
    this.form.update((f) => ({
      ...f,
      delegationLeadMinutes: Number.isFinite(n) && n > 0 ? n : 0,
    }));
  }

  /** Quorum-Eingabe: leer → null (kein Default), sonst auf 0–100 geklemmt. */
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
    // Zusatz-Empfänger nachladen (eigener Endpunkt, #protocol-recipients).
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

  /** Zusatz-Protokoll-Empfänger nach den Stammdaten speichern (#protocol-recipients). */
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
