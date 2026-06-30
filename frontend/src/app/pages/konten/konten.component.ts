import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
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
  type ExpenseKind,
  type FintsCredentialStatus,
  type StatementLine,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { PALETTE } from '../budget/budget-year-tree.component';

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
    DatepickerComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    IconComponent,
    InputComponent,
    SelectComponent,
  ],
  templateUrl: './konten.component.html',
  styleUrl: './konten.component.scss',
})
export class KontenComponent implements OnDestroy {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  // Schreibrechte (#review): Sync/Import/Link/Unlink nur mit budget.book; View-only blendet sie aus.
  readonly canBook = computed(() => this.auth.can('budget.book'));

  // --- accounts (left list) ---
  readonly accounts = signal<AccountOption[]>([]);
  readonly accountId = signal<string>('');
  readonly selectedAccount = computed<AccountOption | null>(
    () => this.accounts().find((a) => a.id === this.accountId()) ?? null,
  );

  // --- transactions (serverseitig gefiltert + paginiert, #fints-konten) ---
  private readonly PAGE = 30;
  readonly lines = signal<StatementLine[]>([]);
  readonly loadingLines = signal(false);
  readonly loadingMore = signal(false);
  readonly total = signal(0);
  private nextOffset = 0;
  readonly hasMore = computed(() => this.lines().length < this.total());
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  // --- filter/sort (serverseitig) ---
  readonly filterState = signal<'' | 'open' | 'linked'>('');
  readonly kind = signal<'' | ExpenseKind>('');
  readonly searchQ = signal('');
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
  readonly sortField = signal<'date' | 'amount'>('date');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');
  readonly activeFilterCount = computed(
    () =>
      (this.filterState() ? 1 : 0) +
      (this.kind() ? 1 : 0) +
      (this.dateFrom() || this.dateTo() ? 1 : 0),
  );
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  // Linker Baum mobil einklappbar (wie Buchungen-Tab).
  readonly treeOpen = signal(false);

  // --- FinTS credential / connect (je Bucher) — in Verbindungs-Dialog, nicht inline ---
  readonly credStatus = signal<FintsCredentialStatus | null>(null);
  readonly connectOpen = signal(false);
  readonly credLogin = signal('');
  readonly credPin = signal('');
  readonly savingCred = signal(false);
  readonly configured = computed(() => !!this.credStatus()?.configured);
  readonly connected = computed(() => !!this.credStatus()?.hasCredential);
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

  // --- Link dialog: Typeahead wie der Mitglieder-Picker (/admin/gremien) ---
  readonly linkLine = signal<StatementLine | null>(null);
  readonly linkQuery = signal('');
  readonly linkCandidates = signal<Expense[]>([]);
  readonly linkSelected = signal<Expense | null>(null);
  readonly linkLoading = signal(false);
  private linkTimer: ReturnType<typeof setTimeout> | null = null;
  candidateLabel(e: Expense): string {
    const parts = [e.description, this.money(e.amount)];
    if (e.correspondent) parts.push(e.correspondent);
    if (e.pathKey) parts.push(e.pathKey);
    return parts.join(' · ');
  }

  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  constructor() {
    this.refreshAccounts();
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
    // Infinite Scroll: Sentinel am Tabellenende sichtbar → nächste Seite (wie Buchungen).
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) this.loadMore();
      });
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  ngOnDestroy(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    if (this.linkTimer) clearTimeout(this.linkTimer);
  }

  /** Konten-Liste (inkl. aktuellem Kontostand) laden/auffrischen, Auswahl beibehalten (#review). */
  private refreshAccounts(): void {
    this.api.listAccountOptions().subscribe({
      next: (accs) => {
        this.accounts.set(accs);
        if (!this.accountId() && accs.length) this.accountId.set(accs[0].id);
      },
      error: () => this.accounts.set([]),
    });
  }

  selectAccount(id: string): void {
    if (id === this.accountId()) return;
    this.accountId.set(id);
    this.resetTan();
  }

  /** Erste Seite (neu) laden — nach Konto-/Filterwechsel. */
  reloadLines(): void {
    if (!this.accountId()) return;
    this.nextOffset = 0;
    this.lines.set([]);
    this.total.set(0);
    this.loadingLines.set(true);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loadingMore() || this.loadingLines() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  private fetch(initial: boolean): void {
    const linked =
      this.filterState() === 'linked' ? true : this.filterState() === 'open' ? false : undefined;
    this.api
      .listStatementLines({
        account: this.accountId() as Uuid,
        linked,
        kind: this.kind() || undefined,
        q: this.searchQ().trim() || undefined,
        dateFrom: this.dateFrom() || undefined,
        dateTo: this.dateTo() || undefined,
        sort: this.sortField(),
        order: this.sortOrder(),
        limit: this.PAGE,
        offset: this.nextOffset,
      })
      .subscribe({
        next: (page) => {
          this.total.set(page.total);
          this.lines.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loadingLines.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          if (initial) this.lines.set([]);
          this.loadingLines.set(false);
          this.loadingMore.set(false);
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

  /** Kontostand **mit Vorzeichen** (negativ = überzogen) — #review: nicht abs() wie money(). */
  balanceMoney(amount: string): string {
    return Number(amount).toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
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

  // ----------------------------------------------------- filter/sort (serverseitig)
  setState(s: '' | 'open' | 'linked'): void {
    this.filterState.set(s);
    this.reloadLines();
  }
  setKind(k: '' | ExpenseKind): void {
    this.kind.set(k);
    this.reloadLines();
  }
  onDateFilter(which: 'from' | 'to', value: string): void {
    (which === 'from' ? this.dateFrom : this.dateTo).set(value || '');
    this.reloadLines();
  }
  resetFilters(): void {
    this.filterState.set('');
    this.kind.set('');
    this.dateFrom.set('');
    this.dateTo.set('');
    this.reloadLines();
  }
  onSearch(v: string): void {
    this.searchQ.set(v);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reloadLines(), 400);
  }
  onSort(field: 'date' | 'amount'): void {
    if (this.sortField() === field) this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
    this.reloadLines();
  }
  sortInd(field: 'date' | 'amount'): string {
    if (this.sortField() !== field) return '';
    return this.sortOrder() === 'asc' ? ' ↑' : ' ↓';
  }
  ariaSort(field: 'date' | 'amount'): 'ascending' | 'descending' | 'none' {
    if (this.sortField() !== field) return 'none';
    return this.sortOrder() === 'asc' ? 'ascending' : 'descending';
  }

  // ----------------------------------------------------- account selector look
  /** Farbpunkt je Konto wie im Budget-Selektor (#fints-konten) — Index-rotiert. */
  dotColor(index: number): string {
    return PALETTE[((index % PALETTE.length) + PALETTE.length) % PALETTE.length];
  }
  accountBalance(a: AccountOption): string {
    return a.fintsLastBalance !== null ? this.balanceMoney(a.fintsLastBalance) : '';
  }

  // ----------------------------------------------------- credential / connect (dialog)
  private loadCredStatus(accountId: string): void {
    this.api.fintsCredentialStatus(accountId as Uuid).subscribe({
      next: (s) => {
        this.credStatus.set(s);
        this.credLogin.set(s.fintsLogin ?? '');
        this.credPin.set('');
      },
      error: () => this.credStatus.set(null),
    });
  }
  openConnect(): void {
    this.credLogin.set(this.credStatus()?.fintsLogin ?? '');
    this.credPin.set('');
    this.connectOpen.set(true);
  }
  closeConnect(): void {
    this.connectOpen.set(false);
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
        this.closeConnect();
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
        this.closeConnect();
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
    if (!this.connected()) {
      // Noch keine Zugangsdaten → Verbindungs-Dialog statt Fehler.
      this.openConnect();
      return;
    }
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
    this.loadCredStatus(this.accountId());
    this.refreshAccounts(); // Kontostand/Anzeige nach Sync aktualisieren (#review)
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
  /** TAN-Dialog abbrechen (#fints-konten) — laufende Sitzung verwerfen. */
  closeTan(): void {
    this.resetTan();
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

  // ----------------------------------------------------- per-row: Link (Typeahead)
  openLink(line: StatementLine): void {
    this.linkLine.set(line);
    this.linkQuery.set('');
    this.linkSelected.set(null);
    this.linkCandidates.set([]);
    // Vorschlag: gleicher Betrag + Art (häufigster Treffer) — danach frei durchsuchbar.
    this.searchLinkCandidates('', line, Math.abs(Number(line.amount)));
  }
  onLinkSearch(q: string): void {
    this.linkQuery.set(q);
    this.linkSelected.set(null);
    const line = this.linkLine();
    if (!line) return;
    if (this.linkTimer) clearTimeout(this.linkTimer);
    this.linkTimer = setTimeout(() => this.searchLinkCandidates(q.trim(), line), 300);
  }
  private searchLinkCandidates(q: string, line: StatementLine, amount?: number): void {
    this.linkLoading.set(true);
    this.api
      .listExpenses({
        account: this.accountId() as Uuid,
        kind: line.kind,
        unallocated: true,
        q: q || undefined,
        // Ohne Suchtext auf den exakten Betrag eingrenzen (offensichtliche Treffer zuerst);
        // sobald gesucht wird, frei über alle offenen Buchungen des Kontos.
        amountMin: q ? undefined : amount,
        amountMax: q ? undefined : amount,
        limit: 10,
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
  pickLinkCandidate(e: Expense): void {
    this.linkSelected.set(e);
    this.linkCandidates.set([]);
    this.linkQuery.set(this.candidateLabel(e));
  }
  closeLink(): void {
    this.linkLine.set(null);
    if (this.linkTimer) clearTimeout(this.linkTimer);
  }
  confirmLink(): void {
    const line = this.linkLine();
    const sel = this.linkSelected();
    if (!line || !sel || this.booking()) return;
    this.booking.set(true);
    this.api
      .confirmStatementLine(line.id, { matchExpenseId: sel.id as Uuid })
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
