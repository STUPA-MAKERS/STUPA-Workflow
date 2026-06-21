import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { type Account, type AccountBody, BudgetTreeApi } from '../../budget/budget-tree.api';

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
    InputComponent,
    CheckboxComponent,
  ],
  templateUrl: './accounts.component.html',
  styleUrl: './accounts.component.scss',
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
  // FinTS-Zugangsdaten (#fints). `fPin` ist write-only: leer beim Bearbeiten = unverändert
  // (sofern schon eine PIN hinterlegt ist), ein gesetzter Wert ersetzt sie.
  readonly fEndpoint = signal('');
  readonly fBlz = signal('');
  readonly fLogin = signal('');
  readonly fPin = signal('');
  /** Eine PIN ist bereits (verschlüsselt) hinterlegt → Eingabefeld nur „ändern". */
  readonly pinStored = signal(false);
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
    this.fEndpoint.set('');
    this.fBlz.set('');
    this.fLogin.set('');
    this.fPin.set('');
    this.pinStored.set(false);
    this.dialogOpen.set(true);
  }

  openEdit(a: Account): void {
    this.editing.set(a);
    this.fName.set(a.name);
    this.fIban.set(a.iban);
    this.fActive.set(a.active);
    this.fEndpoint.set(a.fintsEndpoint ?? '');
    this.fBlz.set(a.fintsBlz ?? '');
    this.fLogin.set(a.fintsLogin ?? '');
    this.fPin.set('');
    this.pinStored.set(a.fintsConfigured);
    this.dialogOpen.set(true);
  }

  save(event: Event): void {
    event.preventDefault();
    if (!this.fName().trim() || this.saving()) return;
    this.saving.set(true);
    const body: AccountBody = {
      name: this.fName().trim(),
      iban: this.fIban().trim(),
      active: this.fActive(),
      fintsEndpoint: this.fEndpoint().trim() || null,
      fintsBlz: this.fBlz().trim() || null,
      fintsLogin: this.fLogin().trim() || null,
    };
    // PIN nur senden, wenn der Nutzer etwas eingegeben hat — sonst bliebe die
    // gespeicherte PIN beim Bearbeiten unangetastet (leeres Feld ≠ löschen).
    if (this.fPin().trim()) body.fintsPin = this.fPin().trim();
    const current = this.editing();
    const req = current
      ? this.api.updateAccount(current.id as Uuid, body)
      : this.api.createAccount(body);
    req.subscribe({
      next: () => {
        this.saving.set(false);
        this.dialogOpen.set(false);
        // Klartext-PIN nicht im Component-State (Angular DevTools) liegen lassen (#fints-review).
        this.fPin.set('');
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
