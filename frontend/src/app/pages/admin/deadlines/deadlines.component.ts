import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
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
    DialogComponent,
    IconComponent,
    SelectComponent,
  ],
  template: `
    <section class="dl">
      <header class="dl__head">
        <div>
          <h1 class="dl__title">{{ 'admin.deadlines.title' | t }}</h1>
          <p class="dl__sub">{{ 'admin.deadlines.subtitle' | t }}</p>
        </div>
        <app-button size="sm" (click)="openAdd()">{{ 'admin.deadlines.add' | t }}</app-button>
      </header>

      <app-data-table [columns]="columns()" [rows]="policies()" [emptyText]="'admin.deadlines.empty' | t">
        <ng-template appCell="label" let-r>{{ label($any(r)) }}</ng-template>
        <ng-template appCell="key" let-r><span class="dl__mono">{{ $any(r).key }}</span></ng-template>
        <ng-template appCell="kind" let-r>{{ kindLabel($any(r).kind) }}</ng-template>
        <ng-template appCell="value" let-r>{{ valueOf($any(r)) }}</ng-template>
        <ng-template appCell="actions" let-r let-i="index">
          <span class="dl__actions">
            <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.edit' | t" (click)="openEdit(i)">
              <app-icon name="edit" />
            </app-button>
            <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.remove' | t" (click)="askDelete($any(r))">
              <app-icon name="delete" />
            </app-button>
          </span>
        </ng-template>
      </app-data-table>
    </section>

    <app-dialog
      [open]="draft() !== null"
      [title]="(editingId() === null ? 'admin.deadlines.add' : 'admin.common.edit') | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="close()"
    >
      @if (draft(); as d) {
        <form class="dl__form" (submit)="$event.preventDefault(); save()">
          <label class="field">
            <span class="field__label">{{ 'admin.common.key' | t }}</span>
            <input class="field__control" [ngModel]="d.key" (ngModelChange)="patch('key', $event)" name="key" [disabled]="editingId() !== null" placeholder="z. B. semester_frist" />
          </label>
          <label class="field">
            <span class="field__label">{{ 'admin.common.labelDe' | t }}</span>
            <input class="field__control" [ngModel]="d.labelDe" (ngModelChange)="patch('labelDe', $event)" name="labelDe" />
          </label>
          <label class="field">
            <span class="field__label">{{ 'admin.common.labelEn' | t }}</span>
            <input class="field__control" [ngModel]="d.labelEn" (ngModelChange)="patch('labelEn', $event)" name="labelEn" />
          </label>
          <app-select
            [label]="'admin.deadlines.kind' | t"
            [options]="kindOptions"
            [ngModel]="d.kind"
            (ngModelChange)="patch('kind', $event)"
            name="kind"
          />
          @if (d.kind === 'absolute') {
            <label class="field">
              <span class="field__label">{{ 'admin.deadlines.date' | t }}</span>
              <input class="field__control" type="date" [ngModel]="d.absoluteAt" (ngModelChange)="patch('absoluteAt', $event)" name="absoluteAt" />
            </label>
          } @else {
            <label class="field">
              <span class="field__label">{{ 'admin.deadlines.offsetDays' | t }}</span>
              <input class="field__control" type="number" min="0" [ngModel]="d.offsetDays" (ngModelChange)="patch('offsetDays', $event)" name="offsetDays" />
            </label>
          }
        </form>
      }
      <div dialog-footer class="dl__foot">
        <app-button variant="ghost" (click)="close()">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!canSave()" (click)="save()">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <app-dialog
      [open]="confirmDelete() !== null"
      [title]="'admin.deadlines.deleteTitle' | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="confirmDelete.set(null)"
    >
      <p>{{ 'admin.deadlines.deleteConfirm' | t: { name: label(confirmDelete()) } }}</p>
      <div dialog-footer class="dl__foot">
        <app-button variant="ghost" (click)="confirmDelete.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" (click)="doDelete()">{{ 'admin.common.remove' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host { display: flex; flex-direction: column; gap: var(--space-5); }
      .dl__head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
      .dl__title { margin: 0; }
      .dl__sub { color: var(--color-text-muted); font-size: var(--fs-sm); margin: var(--space-1) 0 0; }
      .dl__mono { font-family: var(--font-mono, monospace); font-size: var(--fs-xs); }
      .dl__actions { display: inline-flex; align-items: center; gap: var(--space-1); justify-content: flex-end; }
      .dl__form { display: flex; flex-direction: column; gap: var(--space-4); }
      .field { display: flex; flex-direction: column; gap: var(--space-2); }
      .field__label { font-size: var(--fs-sm); font-weight: var(--fw-medium); }
      .field__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .field__control:disabled { opacity: 0.6; cursor: not-allowed; }
      .dl__foot { display: flex; justify-content: flex-end; gap: var(--space-3); }
    `,
  ],
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
