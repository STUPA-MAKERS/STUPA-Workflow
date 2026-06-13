import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  type SelectOption,
  SelectComponent,
  ToastService,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import type { DeadlineKind, DeadlinePolicy } from '../admin.models';

const KINDS: DeadlineKind[] = ['absolute', 'relative_submitted', 'relative_changed'];

interface PolicyDraft {
  key: string;
  labelDe: string;
  labelEn: string;
  kind: DeadlineKind;
  absoluteAt: string;
  offsetDays: number | null;
}

function emptyDraft(): PolicyDraft {
  return { key: '', labelDe: '', labelEn: '', kind: 'absolute', absoluteAt: '', offsetDays: null };
}

/**
 * Fristen-Registry (#Deadlines): benannte Frist-Policies, die der Flow per `key`
 * referenziert. `absolute` trägt ein Datum (pro Semester pflegbar, ohne den Flow zu
 * ändern); die relativen Varianten leiten die Frist aus Einreichung bzw. letzter
 * Änderung + X Tagen ab. CRUD über die Admin-API (Dialog).
 */
@Component({
  selector: 'app-admin-deadlines',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    DatepickerComponent,
    DialogComponent,
    IconComponent,
    SelectComponent,
  ],
  templateUrl: './deadlines.component.html',
  styleUrl: './deadlines.component.scss',
})
export class AdminDeadlinesComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly policies = signal<DeadlinePolicy[]>([]);
  protected readonly draft = signal<PolicyDraft | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly confirmDelete = signal<DeadlinePolicy | null>(null);

  protected readonly kindOptions: SelectOption[] = KINDS.map((k) => ({
    value: k,
    label: this.kindLabel(k),
  }));

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'label', label: this.i18n.translate('admin.deadlines.col.name') },
    { key: 'key', label: this.i18n.translate('admin.common.key') },
    { key: 'kind', label: this.i18n.translate('admin.deadlines.col.kind') },
    { key: 'value', label: this.i18n.translate('admin.deadlines.col.value') },
    { key: 'actions', label: this.i18n.translate('admin.common.actions'), align: 'end', width: '7rem' },
  ]);

  constructor() {
    this.api.listDeadlinePolicies().subscribe((p) => this.policies.set(p));
  }

  protected label(p: DeadlinePolicy | null): string {
    if (!p) return '';
    return p.label[this.i18n.locale()] ?? p.label['de'] ?? p.key;
  }

  protected kindLabel(kind: DeadlineKind): string {
    return this.i18n.translate(`admin.deadlines.kind.${kind}` as TranslationKey);
  }

  /** Anzeige der konkreten Frist-Quelle: Datum bzw. „+ X Tage". */
  protected valueOf(p: DeadlinePolicy): string {
    if (p.kind === 'absolute') {
      return p.absoluteAt ? new Date(p.absoluteAt).toLocaleDateString(this.i18n.locale()) : '—';
    }
    return p.offsetDays != null ? `+ ${p.offsetDays} ${this.i18n.translate('admin.deadlines.days')}` : '—';
  }

  protected openAdd(): void {
    this.editingId.set(null);
    this.draft.set(emptyDraft());
  }

  protected openEdit(i: number): void {
    const p = this.policies()[i];
    this.editingId.set(p.id);
    this.draft.set({
      key: p.key,
      labelDe: p.label['de'] ?? '',
      labelEn: p.label['en'] ?? '',
      kind: p.kind,
      absoluteAt: p.absoluteAt ? p.absoluteAt.slice(0, 10) : '',
      offsetDays: p.offsetDays ?? null,
    });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingId.set(null);
  }

  protected patch<K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected canSave(): boolean {
    const d = this.draft();
    if (!d || !d.key.trim()) return false;
    return d.kind === 'absolute' ? !!d.absoluteAt : d.offsetDays != null && Number(d.offsetDays) >= 0;
  }

  protected save(): void {
    const d = this.draft();
    if (!d || !this.canSave()) return;
    const label = { de: d.labelDe.trim() || d.key, en: d.labelEn.trim() || d.labelDe.trim() || d.key };
    const absoluteAt = d.kind === 'absolute' ? new Date(d.absoluteAt).toISOString() : null;
    const offsetDays = d.kind === 'absolute' ? null : Number(d.offsetDays);
    const id = this.editingId();
    const req = id
      ? this.api.updateDeadlinePolicy(id, { label, kind: d.kind, absoluteAt, offsetDays })
      : this.api.createDeadlinePolicy({ key: d.key.trim(), label, kind: d.kind, absoluteAt, offsetDays });
    req.subscribe({
      next: (saved) => {
        this.policies.update((list) =>
          id ? list.map((p) => (p.id === id ? saved : p)) : [...list, saved],
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected askDelete(p: DeadlinePolicy): void {
    this.confirmDelete.set(p);
  }

  protected doDelete(): void {
    const p = this.confirmDelete();
    if (!p) return;
    this.api.deleteDeadlinePolicy(p.id).subscribe({
      next: () => {
        this.policies.update((list) => list.filter((x) => x.id !== p.id));
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
