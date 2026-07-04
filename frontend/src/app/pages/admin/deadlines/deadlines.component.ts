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
  InputComponent,
  type SelectOption,
  SelectComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { DeadlineKind, DeadlinePolicy } from '../admin.models';

const KINDS: DeadlineKind[] = [
  'absolute',
  'relative_submitted',
  'relative_changed',
  'recurring',
];

const DEFAULT_TZ = 'Europe/Berlin';

/** Full IANA zone list from the runtime, with a small fallback for old engines. */
function buildTimezoneOptions(): SelectOption[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  let zones: string[] = [];
  try {
    zones = intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : [];
  } catch {
    zones = [];
  }
  if (zones.length === 0) {
    zones = ['UTC', 'Europe/Berlin', 'Europe/London', 'Europe/Vienna', 'Europe/Zurich'];
  }
  return zones.map((z) => ({ value: z, label: z }));
}

interface PolicyDraft {
  key: string;
  labelDe: string;
  labelEn: string;
  kind: DeadlineKind;
  absoluteAt: string;
  offsetDays: number | null;
  atTime: string;
  timezone: string;
  dates: string[];
}

function emptyDraft(): PolicyDraft {
  return {
    key: '',
    labelDe: '',
    labelEn: '',
    kind: 'absolute',
    absoluteAt: '',
    offsetDays: null,
    atTime: '',
    timezone: DEFAULT_TZ,
    dates: [],
  };
}

/**
 * Deadline registry: named deadline policies that the flow references via `key`.
 * `absolute` carries a date (editable per semester, without changing the flow); the
 * relative variants derive the deadline from submission or last change + X days;
 * `recurring` rolls through a list of dates (the earliest still ahead is used).
 * `atTime`/`timezone` optionally pin the wall-clock (DST-correct). CRUD via the
 * admin API (dialog).
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
    InputComponent,
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
  protected readonly timezoneOptions: SelectOption[] = buildTimezoneOptions();

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

  /** Display the concrete deadline source: a date, "+ X days", or a date count. */
  protected valueOf(p: DeadlinePolicy): string {
    const base = this.baseValue(p);
    return p.atTime ? `${base} · ${p.atTime}` : base;
  }

  private baseValue(p: DeadlinePolicy): string {
    if (p.kind === 'absolute') {
      return p.absoluteAt ? new Date(p.absoluteAt).toLocaleDateString(this.i18n.locale()) : '—';
    }
    if (p.kind === 'recurring') {
      const n = p.dates?.length ?? 0;
      return `${n} ${this.i18n.translate('admin.deadlines.dates')}`;
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
      atTime: p.atTime ?? '',
      timezone: p.timezone ?? DEFAULT_TZ,
      dates: p.dates ? [...p.dates] : [],
    });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingId.set(null);
  }

  protected patch<K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected addDate(): void {
    this.draft.update((d) => (d ? { ...d, dates: [...d.dates, ''] } : d));
  }

  protected removeDate(index: number): void {
    this.draft.update((d) => (d ? { ...d, dates: d.dates.filter((_, i) => i !== index) } : d));
  }

  protected setDate(index: number, value: string): void {
    this.draft.update((d) =>
      d ? { ...d, dates: d.dates.map((x, i) => (i === index ? value : x)) } : d,
    );
  }

  protected canSave(): boolean {
    const d = this.draft();
    if (!d || !d.key.trim()) return false;
    if (d.kind === 'absolute') return !!d.absoluteAt;
    if (d.kind === 'recurring') return d.dates.some((x) => !!x.trim());
    return d.offsetDays != null && Number(d.offsetDays) >= 0;
  }

  protected save(): void {
    const d = this.draft();
    if (!d || !this.canSave()) return;
    const label = { de: d.labelDe.trim() || d.key, en: d.labelEn.trim() || d.labelDe.trim() || d.key };
    const absoluteAt = d.kind === 'absolute' ? new Date(d.absoluteAt).toISOString() : null;
    const offsetDays =
      d.kind === 'relative_submitted' || d.kind === 'relative_changed' ? Number(d.offsetDays) : null;
    const dates = d.kind === 'recurring' ? d.dates.map((x) => x.trim()).filter(Boolean) : null;
    const atTime = d.atTime.trim() || null;
    const timezone = atTime || dates ? d.timezone || DEFAULT_TZ : null;
    const body = { label, kind: d.kind, absoluteAt, offsetDays, atTime, timezone, dates };
    const id = this.editingId();
    const req = id
      ? this.api.updateDeadlinePolicy(id, body)
      : this.api.createDeadlinePolicy({ key: d.key.trim(), ...body });
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
