import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
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
  TimeInputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { DeadlineKind, DeadlinePolicy } from '../admin.models';
import { GuestSettingsComponent } from './guest-settings/guest-settings.component';

/** The text of the "Frist" cell, with a tooltip and the muted look for a past schedule. */
export interface DeadlineValue {
  text: string;
  title: string;
  muted: boolean;
}

/** Today as `YYYY-MM-DD` in local time, for the comparison with the recurring dates. */
function localToday(now: Date): string {
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

const KINDS: DeadlineKind[] = [
  'absolute',
  'relative_submitted',
  'relative_changed',
  'recurring',
];

const DEFAULT_TZ = 'Europe/Berlin';

/** IANA zone list from the runtime. An old engine gets a small fallback list. */
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
 * Deadline registry (boards Admin-Fristen, Admin-Fristen-Dialog): the named deadline
 * policies that the flow references by `key`.
 *
 * `absolute` carries a date. An admin can edit that date per semester without a change
 * to the flow. The relative kinds derive the deadline from the submission date or the
 * last change date plus X days. `recurring` steps through a list of dates and takes the
 * earliest date that is still ahead. `atTime` and `timezone` pin the wall-clock time and
 * stay correct over a DST switch. The dialog creates, updates and deletes policies
 * through the admin API.
 *
 * Below the table, `app-guest-settings` holds the settings for applications without an
 * account (Z1): the discard window and the lifetime of the personal link.
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
    TimeInputComponent,
    PageHeaderComponent,
    GuestSettingsComponent,
  ],
  templateUrl: './deadlines.component.html',
  styleUrl: './deadlines.component.scss',
})
export class AdminDeadlinesComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /**
   * True until the first answer. Without it the table shows its empty text while the
   * request is still out, which asserts there is nothing when nothing has arrived yet.
   */
  protected readonly loading = signal(true);

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
    { key: 'label', label: this.i18n.translate('admin.deadlines.col.name'), card: 'title' },
    { key: 'key', label: this.i18n.translate('admin.common.key') },
    { key: 'kind', label: this.i18n.translate('admin.deadlines.col.kind') },
    { key: 'value', label: this.i18n.translate('admin.deadlines.col.value') },
    {
      key: 'actions',
      label: this.i18n.translate('admin.common.actions'),
      align: 'end',
      width: '6rem',
      card: 'actions',
    },
  ]);
  protected readonly rowId = (r: unknown): string => (r as DeadlinePolicy).id;

  constructor() {
    this.api.listDeadlinePolicies().subscribe({
      next: (p) => {
        this.policies.set(p);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  protected label(p: DeadlinePolicy | null): string {
    if (!p) return '';
    return p.label[this.i18n.locale()] ?? p.label['de'] ?? p.key;
  }

  protected kindLabel(kind: DeadlineKind): string {
    return this.i18n.translate(`admin.deadlines.kind.${kind}` as TranslationKey);
  }

  /**
   * The concrete deadline: "14 Tage", the date of an absolute deadline, or the next date of
   * a recurring one ("13.10.2026"), each with " · 18:00" when a time is set. The tooltip
   * names the time zone and, for a recurring deadline, the number of dates. A recurring
   * deadline without a date ahead reads "Kein Termin mehr" in muted text.
   */
  protected valueOf(p: DeadlinePolicy, now: Date = new Date()): DeadlineValue {
    const time = p.atTime ? ` · ${p.atTime}` : '';
    const zone = p.atTime && p.timezone ? p.timezone : '';
    if (p.kind === 'recurring') {
      const dates = [...(p.dates ?? [])].sort();
      const count =
        dates.length === 1
          ? this.i18n.translate('admin.deadlines.dateCountOne')
          : this.i18n.translate('admin.deadlines.dateCount', { n: dates.length });
      const next = dates.find((d) => d >= localToday(now));
      if (!next) {
        return { text: this.i18n.translate('admin.deadlines.noNextDate'), title: count, muted: true };
      }
      return { text: this.dateText(`${next}T12:00:00`) + time, title: [count, zone].filter(Boolean).join(' · '), muted: false };
    }
    if (p.kind === 'absolute') {
      const text = p.absoluteAt ? this.dateText(p.absoluteAt) + time : '—';
      return { text, title: zone, muted: !p.absoluteAt };
    }
    if (p.offsetDays == null) return { text: '—', title: '', muted: true };
    return {
      text: this.i18n.translate('admin.deadlines.daysValue', { n: p.offsetDays }) + time,
      title: zone,
      muted: false,
    };
  }

  private dateText(iso: string): string {
    return new Date(iso).toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
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

  /** The number field gives a string; an empty field means "no offset yet". */
  protected patchOffset(value: string | number | null): void {
    const text = String(value ?? '').trim();
    this.patch('offsetDays', text === '' ? null : Number(text));
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
