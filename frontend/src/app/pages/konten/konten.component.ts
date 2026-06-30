import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  type AccountOption,
  type BankSyncResult,
  BudgetTreeApi,
  type Expense,
  type FintsCredentialStatus,
  type StatementLine,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';

/**
 * Konten-Tab (#fints-konten): pro Bankkonto **alle** abgerufenen Transaktionen + Kontostand;
 * jede Transaktion ist optional **genau einer** Buchung zugeordnet. Layout wie der Buchungen-Tab
 * (Liste links, Tabelle rechts). Aktionen: Synchronisieren / Login / Datei-Import; pro Zeile
 * Link (an bestehende Buchung) · Import (neue Buchung) · Unlink (Zuordnung lösen).
 *
 * FinTS-Login/Sync/TAN leben hier (nicht mehr im Buchungen-Dialog). Direkter DB-Bezug n/a — alles
 * über die API; Schreibrechte serverseitig (budget.book).
 */
@Component({
  selector: 'app-konten',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    SelectComponent,
  ],
  templateUrl: './konten.component.html',
  styleUrl: './konten.component.scss',
})
export class KontenComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  // --- accounts (left list) ---
  readonly accounts = signal<AccountOption[]>([]);
  readonly accountId = signal<string>('');
  readonly selectedAccount = computed<AccountOption | null>(
    () => this.accounts().find((a) => a.id === this.accountId()) ?? null,
  );

  // --- transactions ---
  readonly lines = signal<StatementLine[]>([]);
  readonly loadingLines = signal(false);

  // --- filter/sort (clientseitig, wie Buchungen) ---
  readonly filterState = signal<'' | 'open' | 'linked'>('');
  readonly searchQ = signal('');
  readonly sortField = signal<'date' | 'amount'>('date');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  readonly filtered = computed<StatementLine[]>(() => {
    const state = this.filterState();
    const q = this.searchQ().trim().toLowerCase();
    let rows = this.lines().filter((l) => {
      const linked = l.matchState === 'matched';
      if (state === 'open' && linked) return false;
      if (state === 'linked' && !linked) return false;
      if (q && !`${l.counterpartyName ?? ''} ${l.purpose ?? ''} ${l.counterpartyIban ?? ''}`
        .toLowerCase().includes(q)) return false;
      return true;
    });
    const dir = this.sortOrder() === 'asc' ? 1 : -1;
    const field = this.sortField();
    rows = [...rows].sort((a, b) =>
      field === 'amount'
        ? (Math.abs(Number(a.amount)) - Math.abs(Number(b.amount))) * dir
        : ((a.valueDate || a.bookingDate || '').localeCompare(b.valueDate || b.bookingDate || '')) * dir,
    );
    return rows;
  });

  // --- FinTS credential / connect (je Bucher) ---
  readonly credStatus = signal<FintsCredentialStatus | null>(null);
  readonly editingCred = signal(false);
  readonly credLogin = signal('');
  readonly credPin = signal('');
  readonly savingCred = signal(false);
  readonly needsConnect = computed(() => {
    const s = this.credStatus();
    return !!s && s.configured && !s.hasCredential;
  });
  readonly connected = computed(() => !!this.credStatus()?.hasCredential);
  readonly showCredForm = computed(() => this.editingCred() || this.needsConnect());
  readonly connectedLabel = computed(() =>
    this.i18n.translate('fints.connectedAs', { login: this.credStatus()?.fintsLogin ?? '' }),
  );
  readonly locked = computed(() => {
    const until = this.credStatus()?.fintsLockedUntil;
    return !!until && new Date(until).getTime() > Date.now();
  });
  readonly lockedUntilLabel = computed(() => {
    const until = this.credStatus()?.fintsLockedUntil;
    return until ? new Date(until).toLocaleString() : '';
  });

  // --- sync / TAN ---
  readonly syncing = signal(false);
  readonly importing = signal(false);
  readonly sessionToken = signal<string>('');
  readonly challenge = signal<string>('');
  readonly challengeImage = signal<string>('');
  readonly decoupled = signal(false);
  readonly tanCode = signal('');
  readonly tanBusy = signal(false);
  readonly hasPendingTan = computed(() => !!this.sessionToken());

  // OTP (6 Boxen) — identisch zum bisherigen Dialog.
  readonly otpLength = 6;
  readonly otpSlots = Array.from({ length: 6 }, (_, i) => i);
  readonly otpDigits = signal<string[]>(Array.from({ length: 6 }, () => ''));
  readonly otpMode = signal(true);
  readonly tanReady = computed(() => {
    const t = this.tanCode().trim();
    return this.otpMode() ? t.length === this.otpLength : t.length > 0;
  });

  // --- reconcile: cost-centre tree + fiscal years ---
  private readonly costOptionsSig = signal<SelectOption[]>([]);
  readonly costCentreOptions = computed<SelectOption[]>(() => this.costOptionsSig());
  readonly fiscalYearOptions = signal<SelectOption[]>([]);
  /** Knoten-Id → Top-Budget-Id (für die HHJ-Auswahl beim Import). */
  private idToTopId = signal<Map<string, string>>(new Map());

  // --- Import dialog ---
  readonly importLine = signal<StatementLine | null>(null);
  readonly impBudgetId = signal('');
  readonly impFiscalYearId = signal('');
  readonly impDescription = signal('');
  readonly booking = signal(false);

  // --- Link dialog ---
  readonly linkLine = signal<StatementLine | null>(null);
  readonly linkCandidates = signal<Expense[]>([]);
  readonly linkExpenseId = signal('');
  readonly linkLoading = signal(false);
  readonly linkCandidateOptions = computed<SelectOption[]>(() =>
    this.linkCandidates().map((e) => ({
      value: e.id,
      label: `${e.description} · ${this.money(e.amount)}${e.correspondent ? ' · ' + e.correspondent : ''}`,
    })),
  );

  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  constructor() {
    this.api.listAccountOptions().subscribe({
      next: (accs) => {
        this.accounts.set(accs);
        if (!this.accountId() && accs.length) this.accountId.set(accs[0].id);
      },
      error: () => this.accounts.set([]),
    });
    this.api.tree().subscribe({
      next: (tree) => {
        this.costOptionsSig.set(flattenBudgetOptions(tree));
        const map = new Map<string, string>();
        const walk = (node: { id: string; children: unknown[] }, topId: string): void => {
          map.set(node.id, topId);
          for (const c of node.children) walk(c as { id: string; children: unknown[] }, topId);
        };
        for (const top of tree) walk(top, top.id);
        this.idToTopId.set(map);
      },
      error: () => this.costOptionsSig.set([]),
    });
    // Konto gewählt → Transaktionen + Verbindungs-Status laden.
    effect(() => {
      const acc = this.accountId();
      if (acc) {
        this.reloadLines();
        this.loadCredStatus(acc);
      }
    });
  }

  selectAccount(id: string): void {
    if (id === this.accountId()) return;
    this.accountId.set(id);
    this.resetTan();
  }

  reloadLines(): void {
    const acc = this.accountId();
    if (!acc) return;
    this.loadingLines.set(true);
    this.api.listStatementLines({ account: acc as Uuid }).subscribe({
      next: (rows) => {
        this.lines.set(rows);
        this.loadingLines.set(false);
      },
      error: () => {
        this.lines.set([]);
        this.loadingLines.set(false);
      },
    });
  }

  money(amount: string): string {
    const n = Math.abs(Number(amount));
    return n.toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
      style: 'currency',
      currency: 'EUR',
    });
  }

  signedMoney(l: StatementLine): string {
    return (l.kind === 'income' ? '+' : '−') + this.money(l.amount);
  }

  /** Gegenkonto in Name + IBAN trennen (#fints) — wie im alten Dialog. */
  counterparty(l: StatementLine): { name: string; iban: string } {
    let iban = (l.counterpartyIban ?? '').trim();
    let name = (l.counterpartyName ?? '').trim();
    if (iban && name.startsWith(iban)) name = name.slice(iban.length).trim();
    else if (!iban) {
      const m = /^([A-Z]{2}\d{13,30})(.*)$/.exec(name);
      if (m) {
        iban = m[1];
        name = m[2].trim();
      }
    }
    return { name, iban };
  }

  // ----------------------------------------------------- filter/sort
  setState(s: '' | 'open' | 'linked'): void {
    this.filterState.set(s);
  }
  onSearch(v: string): void {
    this.searchQ.set(v);
  }
  onSort(field: 'date' | 'amount'): void {
    if (this.sortField() === field) this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
  }
  sortInd(field: 'date' | 'amount'): string {
    if (this.sortField() !== field) return '';
    return this.sortOrder() === 'asc' ? ' ↑' : ' ↓';
  }

  // ----------------------------------------------------- credential / connect
  private loadCredStatus(accountId: string): void {
    this.api.fintsCredentialStatus(accountId as Uuid).subscribe({
      next: (s) => {
        this.credStatus.set(s);
        this.credLogin.set(s.fintsLogin ?? '');
        this.credPin.set('');
        this.editingCred.set(false);
      },
      error: () => this.credStatus.set(null),
    });
  }
  editCred(): void {
    this.credLogin.set(this.credStatus()?.fintsLogin ?? '');
    this.credPin.set('');
    this.editingCred.set(true);
  }
  cancelEditCred(): void {
    this.editingCred.set(false);
    this.credPin.set('');
  }
  saveCred(): void {
    const acc = this.accountId();
    const login = this.credLogin().trim();
    const pin = this.credPin();
    if (!acc || !login || !pin || this.savingCred()) return;
    this.savingCred.set(true);
    this.api.setFintsCredential(acc as Uuid, { fintsLogin: login, fintsPin: pin }).subscribe({
      next: (s) => {
        this.savingCred.set(false);
        this.credStatus.set(s);
        this.credPin.set('');
        this.editingCred.set(false);
        this.toast.success(this.i18n.translate('fints.credSaved'));
      },
      error: (e) => {
        this.savingCred.set(false);
        this.toast.error(this.syncError(e));
      },
    });
  }
  removeCred(): void {
    const acc = this.accountId();
    if (!acc || this.savingCred()) return;
    this.savingCred.set(true);
    this.api.deleteFintsCredential(acc as Uuid).subscribe({
      next: () => {
        this.savingCred.set(false);
        this.resetTan();
        this.loadCredStatus(acc);
        this.toast.success(this.i18n.translate('fints.credRemoved'));
      },
      error: () => {
        this.savingCred.set(false);
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  // ----------------------------------------------------- sync / TAN
  startSync(): void {
    const acc = this.accountId();
    if (!acc || this.syncing() || this.locked()) return;
    this.resetTan();
    this.syncing.set(true);
    this.api.fintsSync(acc as Uuid).subscribe({
      next: (res) => {
        this.syncing.set(false);
        this.handleSync(res);
      },
      error: (e) => {
        this.syncing.set(false);
        this.toast.error(this.syncError(e));
        this.refreshOnLock(e);
      },
    });
  }
  submitTan(): void {
    const acc = this.accountId();
    const token = this.sessionToken();
    if (!acc || !token || this.tanBusy()) return;
    this.tanBusy.set(true);
    this.api.fintsSubmitTan(acc as Uuid, token as Uuid, this.tanCode().trim()).subscribe({
      next: (res) => {
        this.tanBusy.set(false);
        if (res.status === 'needs_tan') {
          this.toast.show(this.i18n.translate('fints.tanPending'), 'info');
          return;
        }
        this.resetTan();
        this.handleSync(res);
      },
      error: (e) => {
        this.tanBusy.set(false);
        this.toast.error(this.syncError(e));
        this.refreshOnLock(e);
      },
    });
  }
  private handleSync(res: BankSyncResult): void {
    if (res.status === 'needs_tan') {
      this.sessionToken.set(res.sessionToken ?? '');
      this.challenge.set(res.challenge ?? '');
      const img = res.challengeImage ?? '';
      this.challengeImage.set(/^data:image\/(png|jpe?g|gif|webp);base64,/i.test(img) ? img : '');
      this.decoupled.set(res.decoupled);
      return;
    }
    this.toast.success(
      this.i18n.translate('fints.imported', {
        imported: String(res.imported),
        duplicates: String(res.duplicates),
      }),
    );
    this.reloadLines();
    this.loadCredStatus(this.accountId()); // refresh balance/last-sync
  }
  private refreshOnLock(e: unknown): void {
    const code = (e as { error?: { code?: string } })?.error?.code;
    const acc = this.accountId();
    if (acc && (code === 'fints_bank_locked' || code === 'fints_auth_rejected')) {
      this.loadCredStatus(acc);
    }
  }
  private syncError(e: unknown): string {
    const code = (e as { error?: { code?: string } })?.error?.code;
    if (code === 'fints_not_configured') return this.i18n.translate('fints.errNotConfigured');
    if (code === 'fints_no_credential') return this.i18n.translate('fints.errNoCredential');
    if (code === 'fints_pin_undecryptable') return this.i18n.translate('fints.errPin');
    if (code === 'fints_tan_expired') return this.i18n.translate('fints.errTanExpired');
    if (code === 'fints_bank_locked') return this.i18n.translate('fints.errBankLocked');
    if (code === 'fints_auth_rejected') return this.i18n.translate('fints.errAuthRejected');
    return this.i18n.translate('fints.errSync');
  }
  private resetTan(): void {
    this.sessionToken.set('');
    this.challenge.set('');
    this.challengeImage.set('');
    this.decoupled.set(false);
    this.tanCode.set('');
    this.resetOtp();
    this.otpMode.set(true);
  }

  // OTP handlers (wie Dialog)
  onOtpInput(i: number, ev: Event): void {
    const el = ev.target as HTMLInputElement;
    const digit = el.value.replace(/\D/g, '').slice(-1);
    this.otpDigits.update((d) => {
      const n = [...d];
      n[i] = digit;
      return n;
    });
    el.value = digit;
    this.syncTanFromDigits();
    if (digit && i < this.otpLength - 1) this.focusOtp(i + 1);
  }
  onOtpKeydown(i: number, ev: KeyboardEvent): void {
    if (ev.key === 'Backspace' && !this.otpDigits()[i] && i > 0) {
      ev.preventDefault();
      this.otpDigits.update((d) => {
        const n = [...d];
        n[i - 1] = '';
        return n;
      });
      this.syncTanFromDigits();
      this.focusOtp(i - 1);
    }
  }
  onOtpPaste(ev: ClipboardEvent): void {
    const digits = (ev.clipboardData?.getData('text') ?? '').replace(/\D/g, '');
    if (!digits) return;
    ev.preventDefault();
    const chars = digits.slice(0, this.otpLength).split('');
    this.otpDigits.set(Array.from({ length: this.otpLength }, (_, k) => chars[k] ?? ''));
    this.syncTanFromDigits();
    this.focusOtp(Math.min(chars.length, this.otpLength) - 1);
  }
  useSingleTanField(): void {
    this.otpMode.set(false);
    this.tanCode.set('');
    this.resetOtp();
  }
  private syncTanFromDigits(): void {
    this.tanCode.set(this.otpDigits().join(''));
  }
  private resetOtp(): void {
    this.otpDigits.set(Array.from({ length: this.otpLength }, () => ''));
  }
  private focusOtp(i: number): void {
    this.host.nativeElement.querySelector<HTMLInputElement>(`[data-otp="${i}"]`)?.focus();
  }

  // ----------------------------------------------------- file import (MT940/CAMT)
  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.uploadFile(file);
    input.value = '';
  }
  private uploadFile(file: File): void {
    const acc = this.accountId();
    if (!acc || this.importing()) return;
    this.importing.set(true);
    this.api.importStatementFile(acc as Uuid, file).subscribe({
      next: (res) => {
        this.importing.set(false);
        this.toast.success(
          this.i18n.translate('fints.imported', {
            imported: String(res.imported),
            duplicates: String(res.duplicates),
          }),
        );
        this.reloadLines();
        this.loadCredStatus(acc);
      },
      error: () => {
        this.importing.set(false);
        this.toast.error(this.i18n.translate('fints.errFile'));
      },
    });
  }

  // ----------------------------------------------------- per-row: Import
  openImport(line: StatementLine): void {
    this.importLine.set(line);
    this.impBudgetId.set(line.suggestedBudgetId ?? '');
    this.impDescription.set(line.purpose ?? '');
    this.impFiscalYearId.set('');
    if (line.suggestedBudgetId) this.loadFiscalYears(line.suggestedBudgetId);
    else this.fiscalYearOptions.set([]);
  }
  onPickImportBudget(id: string): void {
    this.impBudgetId.set(id);
    this.loadFiscalYears(id);
  }
  private loadFiscalYears(budgetId: string): void {
    const topId = this.idToTopId().get(budgetId);
    this.impFiscalYearId.set('');
    this.fiscalYearOptions.set([]);
    if (!topId) return;
    this.api.listFiscalYears(topId as Uuid).subscribe({
      next: (fys) => {
        this.fiscalYearOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        if (fys.length === 1) this.impFiscalYearId.set(fys[0].id);
      },
      error: () => this.fiscalYearOptions.set([]),
    });
  }
  closeImport(): void {
    this.importLine.set(null);
  }
  confirmImport(): void {
    const line = this.importLine();
    if (!line || !this.impBudgetId() || this.booking()) return;
    this.booking.set(true);
    this.api
      .confirmStatementLine(line.id, {
        budgetId: this.impBudgetId() as Uuid,
        fiscalYearId: (this.impFiscalYearId() || undefined) as Uuid | undefined,
        description: this.impDescription().trim() || undefined,
      })
      .subscribe({
        next: () => {
          this.booking.set(false);
          this.closeImport();
          this.toast.success(this.i18n.translate('fints.booked'));
          this.reloadLines();
        },
        error: (e) => {
          this.booking.set(false);
          this.toast.error(this.syncError(e));
        },
      });
  }

  // ----------------------------------------------------- per-row: Link
  openLink(line: StatementLine): void {
    this.linkLine.set(line);
    this.linkExpenseId.set('');
    this.linkCandidates.set([]);
    this.linkLoading.set(true);
    const amount = Math.abs(Number(line.amount)).toFixed(2);
    this.api
      .listExpenses({
        account: this.accountId() as Uuid,
        kind: line.kind,
        amountMin: Number(amount),
        amountMax: Number(amount),
        unallocated: true,
        limit: 50,
      })
      .subscribe({
        next: (page) => {
          this.linkCandidates.set(page.items);
          this.linkLoading.set(false);
        },
        error: () => {
          this.linkCandidates.set([]);
          this.linkLoading.set(false);
        },
      });
  }
  closeLink(): void {
    this.linkLine.set(null);
  }
  confirmLink(): void {
    const line = this.linkLine();
    if (!line || !this.linkExpenseId() || this.booking()) return;
    this.booking.set(true);
    this.api
      .confirmStatementLine(line.id, { matchExpenseId: this.linkExpenseId() as Uuid })
      .subscribe({
        next: () => {
          this.booking.set(false);
          this.closeLink();
          this.toast.success(this.i18n.translate('fints.linked'));
          this.reloadLines();
        },
        error: (e) => {
          this.booking.set(false);
          this.toast.error(this.syncError(e));
        },
      });
  }

  // ----------------------------------------------------- per-row: Unlink
  unlink(line: StatementLine): void {
    if (this.booking()) return;
    this.booking.set(true);
    this.api.unlinkStatementLine(line.id).subscribe({
      next: () => {
        this.booking.set(false);
        this.toast.success(this.i18n.translate('fints.unlinked'));
        this.reloadLines();
      },
      error: () => {
        this.booking.set(false);
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }
}
