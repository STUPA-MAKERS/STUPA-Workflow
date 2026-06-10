import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { BudgetTreeApi, type Account } from '../../budget/budget-tree.api';

/**
 * Konten-Verwaltung (Verwaltung → Konten). Konto = Name + IBAN (Freitext); **nicht**
 * an Kostenstellen gebunden. Bei Buchungen optional referenzierbar. P(``account.manage``).
 */
@Component({
  selector: 'app-accounts',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
  ],
  template: `
    <header class="acc__head">
      <div>
        <h1 class="acc__title">{{ 'admin.accounts.title' | t }}</h1>
        <p class="acc__subtitle">{{ 'admin.accounts.desc' | t }}</p>
      </div>
      <app-button size="sm" (click)="openCreate()">{{ 'admin.accounts.add' | t }}</app-button>
    </header>

    <app-data-table [columns]="columns()" [rows]="accounts()" [rowKey]="rowId" [emptyText]="'admin.accounts.empty' | t">
      <ng-template appCell="name" let-row>{{ $any(row).name }}</ng-template>
      <ng-template appCell="iban" let-row><span class="acc__mono">{{ $any(row).iban || '—' }}</span></ng-template>
      <ng-template appCell="active" let-row>
        <app-badge [variant]="$any(row).active ? 'success' : 'neutral'">{{ ($any(row).active ? 'admin.accounts.active' : 'admin.accounts.inactive') | t }}</app-badge>
      </ng-template>
      <ng-template appCell="actions" let-row>
        <span class="acc__actions">
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.edit' | t" (click)="openEdit($any(row))"><app-icon name="edit" /></app-button>
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.delete' | t" (click)="confirmDelete.set($any(row))"><app-icon name="delete" /></app-button>
        </span>
      </ng-template>
    </app-data-table>

    <app-dialog [open]="dialogOpen()" [title]="(editing() ? 'admin.accounts.edit' : 'admin.accounts.add') | t" [closeLabel]="'action.cancel' | t" (closed)="dialogOpen.set(false)">
      <form id="acc-form" class="acc__form" (submit)="save($event)">
        <label class="acc__label" for="acc-name">{{ 'admin.accounts.name' | t }}
          <input id="acc-name" [ngModel]="fName()" (ngModelChange)="fName.set($event)" name="name" /></label>
        <label class="acc__label" for="acc-iban">{{ 'admin.accounts.iban' | t }}
          <input id="acc-iban" [ngModel]="fIban()" (ngModelChange)="fIban.set($event)" name="iban" [placeholder]="'admin.accounts.ibanPlaceholder' | t" /></label>
        <label class="acc__check">
          <input type="checkbox" [checked]="fActive()" (change)="fActive.set($any($event.target).checked)" />
          <span>{{ 'admin.accounts.active' | t }}</span>
        </label>
      </form>
      <div dialog-footer class="acc__foot">
        <app-button variant="ghost" (click)="dialogOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!fName().trim()" [loading]="saving()" (click)="save($event)">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <app-dialog [open]="!!confirmDelete()" [title]="'admin.accounts.delete' | t" [closeLabel]="'action.cancel' | t" (closed)="confirmDelete.set(null)">
      <p>{{ 'admin.accounts.deleteBody' | t: { name: confirmDelete()?.name ?? '' } }}</p>
      <div dialog-footer class="acc__foot">
        <app-button variant="ghost" (click)="confirmDelete.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" [loading]="saving()" (click)="doDelete()">{{ 'admin.accounts.deleteConfirm' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host { display: block; }
      .acc__head { display: flex; align-items: start; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-5); flex-wrap: wrap; }
      .acc__title { margin: 0; }
      .acc__subtitle { color: var(--color-text-muted); margin: var(--space-1) 0 0; }
      .acc__mono { font-variant-numeric: tabular-nums; }
      .acc__actions { display: inline-flex; gap: var(--space-1); justify-content: flex-end; }
      .acc__form { display: flex; flex-direction: column; gap: var(--space-3); }
      .acc__label { display: flex; flex-direction: column; gap: var(--space-1); }
      .acc__label input { padding: var(--space-2) var(--space-3); border: var(--border-width) solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); font: inherit; }
      .acc__check { display: flex; align-items: center; gap: var(--space-2); }
      .acc__foot { display: flex; gap: var(--space-3); }
    `,
  ],
})
export class AccountsComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly accounts = signal<Account[]>([]);
  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.accounts.name') },
    { key: 'iban', label: this.i18n.translate('admin.accounts.iban') },
    { key: 'active', label: this.i18n.translate('admin.accounts.status') },
    { key: 'actions', label: '', align: 'end', width: '6rem' },
  ]);
  readonly rowId = (r: unknown): string => (r as Account).id;

  readonly dialogOpen = signal(false);
  readonly editing = signal<Account | null>(null);
  readonly fName = signal('');
  readonly fIban = signal('');
  readonly fActive = signal(true);
  readonly saving = signal(false);
  readonly confirmDelete = signal<Account | null>(null);

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.api.listAccounts().subscribe({
      next: (a) => this.accounts.set(a),
      error: () => this.accounts.set([]),
    });
  }

  openCreate(): void {
    this.editing.set(null);
    this.fName.set('');
    this.fIban.set('');
    this.fActive.set(true);
    this.dialogOpen.set(true);
  }

  openEdit(a: Account): void {
    this.editing.set(a);
    this.fName.set(a.name);
    this.fIban.set(a.iban);
    this.fActive.set(a.active);
    this.dialogOpen.set(true);
  }

  save(event: Event): void {
    event.preventDefault();
    if (!this.fName().trim() || this.saving()) return;
    this.saving.set(true);
    const body = { name: this.fName().trim(), iban: this.fIban().trim(), active: this.fActive() };
    const current = this.editing();
    const req = current
      ? this.api.updateAccount(current.id as Uuid, body)
      : this.api.createAccount(body);
    req.subscribe({
      next: () => {
        this.saving.set(false);
        this.dialogOpen.set(false);
        this.toast.success(this.i18n.translate('admin.accounts.toastSaved'));
        this.reload();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.accounts.toastFailed'));
      },
    });
  }

  doDelete(): void {
    const a = this.confirmDelete();
    if (!a || this.saving()) return;
    this.saving.set(true);
    this.api.deleteAccount(a.id as Uuid).subscribe({
      next: () => {
        this.saving.set(false);
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.accounts.toastDeleted'));
        this.reload();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.accounts.toastFailed'));
      },
    });
  }
}
