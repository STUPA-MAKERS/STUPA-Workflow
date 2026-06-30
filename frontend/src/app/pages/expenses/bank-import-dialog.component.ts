import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CurrencyInputComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import {
  type AccountOption,
  type BankSyncResult,
  BudgetTreeApi,
  type ExpenseKind,
  type FintsCredentialStatus,
  type StatementLine,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';

/**
 * Bank-Abgleich-Dialog (#fints): Kontoumsätze per **FinTS** abrufen (Option A) oder aus
 * einer **CAMT.053/MT940-Datei** importieren (Option D), dann gestaget abgleichen — je
 * Umsatz eine Kostenstelle wählen und buchen (oder ignorieren).
 *
 * FinTS verlangt eine TAN (PSD2/SCA): der Server pausiert den Dialog und liefert eine
 * Challenge; der Nutzer gibt die TAN ein (oder gibt bei *decoupled* pushTAN in der Banking-
 * App frei und pollt). Self-contained: lädt Konten/Baum/Umsätze selbst; meldet `changed`,
 * damit die Buchungsliste neu lädt.
 */
@Component({
  selector: 'app-bank-import-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    CurrencyInputComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    IconComponent,
    InputComponent,
    SelectComponent,
  ],
  templateUrl: './bank-import-dialog.component.html',
  styleUrl: './bank-import-dialog.component.scss',
})
export class BankImportDialogComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** Sichtbarkeit (vom Eltern-Tab gesteuert). */
  readonly open = input(false);
  /** Dialog geschlossen. */
  readonly closed = output<void>();
  /** Es wurde gebucht/ignoriert → Buchungsliste im Eltern-Tab neu laden. */
  readonly changed = output<void>();

  readonly tab = signal<'fints' | 'file'>('fints');
  readonly accounts = signal<AccountOption[]>([]);
  readonly accountId = signal<string>('');
  readonly lines = signal<StatementLine[]>([]);
  /** Pro Umsatz gewählte Kostenstelle (Vorschlag vorbelegt). */
  readonly chosenBudget = signal<Record<string, string>>({});

  readonly loadingLines = signal(false);
  readonly syncing = signal(false);
  readonly importing = signal(false);
  readonly confirmingId = signal<string>('');

  /** Drag&Drop-Overlay der Datei-Lasche (wie Anhänge-Panel). `dragDepth` zählt
   * enter/leave verschachtelter Kinder, damit das Overlay nicht flackert. */
  readonly dragActive = signal(false);
  private dragDepth = 0;

  // --- FinTS persönliche Zugangsdaten (#fints-percred) ---
  /** Verbindungs-Status des Buchers für das gewählte Konto (`null` = noch nicht geladen). */
  readonly credStatus = signal<FintsCredentialStatus | null>(null);
  /** Login/PIN-Formular sichtbar (erstes Verbinden oder Zugangsdaten ändern). */
  readonly editingCred = signal(false);
  /** Verbindungs-/Login-Bereich eingeklappt (mehr Platz für die Umsatz-Tabelle). */
  readonly connectCollapsed = signal(false);
  readonly credLogin = signal('');
  readonly credPin = signal('');
  readonly savingCred = signal(false);

  /** Konto FinTS-fähig, aber dieser Bucher hat noch keine eigenen Zugangsdaten. */
  readonly needsConnect = computed(() => {
    const s = this.credStatus();
    return !!s && s.configured && !s.hasCredential;
  });
  /** Dieser Bucher ist mit eigenen Zugangsdaten verbunden. */
  readonly connected = computed(() => !!this.credStatus()?.hasCredential);
  /** Login/PIN-Formular zeigen (erstes Verbinden erzwungen oder manuell geöffnet). */
  readonly showCredForm = computed(() => this.editingCred() || this.needsConnect());
  /** „Verbunden als <login>" für den Status-Hinweis. */
  readonly connectedLabel = computed(() =>
    this.i18n.translate('fints.connectedAs', { login: this.credStatus()?.fintsLogin ?? '' }),
  );
  /** Sperr-Cooldown aktiv (#fints-review): der Server lehnt jeden Sync ab → Button sperren
   *  und warnen, NICHT erneut zu versuchen (sonst droht die Bank-Vollsperre). */
  readonly locked = computed(() => {
    const until = this.credStatus()?.fintsLockedUntil;
    return !!until && new Date(until).getTime() > Date.now();
  });
  /** Lokalisierter „bis <Zeitpunkt>" für den Sperr-Hinweis. */
  readonly lockedUntilLabel = computed(() => {
    const until = this.credStatus()?.fintsLockedUntil;
    return until ? new Date(until).toLocaleString() : '';
  });

  // --- FinTS-TAN-Schritt ---
  readonly sessionToken = signal<string>('');
  readonly challenge = signal<string>('');
  /** Optischer Challenge (photoTAN/QR-TAN) als Data-URL — leer = nur Text/Code (#fints-qrtan). */
  readonly challengeImage = signal<string>('');
  readonly decoupled = signal(false);
  readonly tanCode = signal('');
  readonly tanBusy = signal(false);

  // --- TAN-OTP-Eingabe (#fints): 6 Boxen mit Auto-Advance/Paste; Fallback ein Freitextfeld,
  //     falls die Bank eine TAN abweichender Länge schickt (otpMode=false). ---
  readonly otpLength = 6;
  readonly otpSlots = Array.from({ length: 6 }, (_, i) => i);
  readonly otpDigits = signal<string[]>(Array.from({ length: 6 }, () => ''));
  readonly otpMode = signal(true);
  /** TAN absendebereit: im OTP-Modus alle Stellen gefüllt, sonst irgendein Wert. */
  readonly tanReady = computed(() => {
    const t = this.tanCode().trim();
    return this.otpMode() ? t.length === this.otpLength : t.length > 0;
  });

  private readonly costOptionsSig = signal<SelectOption[]>([]);
  readonly costCentreOptions = computed<SelectOption[]>(() => this.costOptionsSig());

  // --- Staging-Filter/Sortierung (#fints): clientseitig — die offenen Umsätze sind bereits
  //     vollständig geladen, also keine Server-Roundtrips nötig. ---
  readonly filterKind = signal<'' | ExpenseKind>('');
  readonly searchQ = signal('');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly sortField = signal<'date' | 'amount'>('date');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  readonly activeFilterCount = computed(
    () =>
      [
        this.filterKind(),
        this.searchQ().trim(),
        this.amountMin().trim(),
        this.amountMax().trim(),
      ].filter(Boolean).length,
  );

  /** Gefilterte + sortierte Umsätze für die Tabelle. */
  readonly filteredLines = computed<StatementLine[]>(() => {
    const acc = this.accountId();
    const kind = this.filterKind();
    const q = this.searchQ().trim().toLowerCase();
    const min = this.amountMin().trim() ? Number(this.amountMin()) : null;
    const max = this.amountMax().trim() ? Number(this.amountMax()) : null;
    const rows = this.lines().filter((l) => {
      if (acc && l.accountId !== acc) return false;
      if (kind && l.kind !== kind) return false;
      const abs = Math.abs(Number(l.amount));
      if (min !== null && abs < min) return false;
      if (max !== null && abs > max) return false;
      if (q && !`${l.counterpartyName ?? ''} ${l.purpose ?? ''}`.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
    const dir = this.sortOrder() === 'asc' ? 1 : -1;
    const field = this.sortField();
    return [...rows].sort((a, b) =>
      field === 'amount'
        ? (Math.abs(Number(a.amount)) - Math.abs(Number(b.amount))) * dir
        : this._lineDate(a).localeCompare(this._lineDate(b)) * dir,
    );
  });

  private _lineDate(l: StatementLine): string {
    return l.valueDate || l.bookingDate || '';
  }

  // --- Inkrementelles Rendern (#fints): pro Zeile steckt ein vollständiges Kostenstellen-
  //     <app-select> → bei vielen Umsätzen friert die UI ein. Daher nur ``visibleCount`` Zeilen
  //     rendern und beim Scrollen ans Ende nachladen (Infinite Scroll, alles clientseitig). ---
  private readonly PAGE = 25;
  readonly visibleCount = signal(25);
  readonly pagedLines = computed<StatementLine[]>(() =>
    this.filteredLines().slice(0, this.visibleCount()),
  );
  readonly hasMoreLines = computed(() => this.filteredLines().length > this.visibleCount());
  private readonly linesSentinel = viewChild<ElementRef<HTMLElement>>('linesSentinel');
  private readonly tableScroll = viewChild<ElementRef<HTMLElement>>('tableScroll');

  loadMoreLines(): void {
    if (this.hasMoreLines()) this.visibleCount.update((n) => n + this.PAGE);
  }

  /** Konten für die FinTS-Lasche: nur sync-fähige (`fintsConfigured`). */
  readonly fintsAccountOptions = computed<SelectOption[]>(() =>
    this.accounts()
      .filter((a) => a.fintsConfigured)
      .map((a) => ({ value: a.id, label: a.name })),
  );
  /** Konten für die Datei-Lasche: alle aktiven. */
  readonly fileAccountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  readonly hasPendingTan = computed(() => !!this.sessionToken());

  constructor() {
    // Beim Öffnen: Konten + Kostenstellen-Baum + offene Umsätze laden.
    effect(() => {
      if (this.open()) this.onOpen();
    });
    // FinTS-Lasche + Konto gewählt → persönlichen Verbindungs-Status laden (#fints-percred).
    effect(() => {
      const acc = this.accountId();
      if (this.open() && this.tab() === 'fints' && acc) this.loadCredStatus(acc);
    });
    // Filter/Konto/Sortierung geändert → Seitenfenster zurücksetzen (sonst rendert man nach
    // einem Filterwechsel weiter alle zuvor aufgedeckten Zeilen).
    effect(() => {
      this.accountId();
      this.filterKind();
      this.searchQ();
      this.amountMin();
      this.amountMax();
      this.sortField();
      this.sortOrder();
      this.visibleCount.set(this.PAGE);
    });
    // Infinite Scroll: Sentinel am Tabellenende beobachten (Root = scrollbarer Wrapper).
    effect((onCleanup) => {
      const sentinel = this.linesSentinel()?.nativeElement;
      const root = this.tableScroll()?.nativeElement ?? null;
      if (!sentinel || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMoreLines();
        },
        { root, rootMargin: '200px' },
      );
      obs.observe(sentinel);
      onCleanup(() => obs.disconnect());
    });
  }

  private onOpen(): void {
    this.resetTan();
    this.api.listAccountOptions().subscribe({
      next: (accs) => {
        this.accounts.set(accs);
        if (!this.accountId() && accs.length) this.accountId.set(accs[0].id);
      },
      error: () => this.accounts.set([]),
    });
    this.api.tree().subscribe({
      next: (tree) => this.costOptionsSig.set(flattenBudgetOptions(tree)),
      error: () => this.costOptionsSig.set([]),
    });
    this.reloadLines();
  }

  reloadLines(): void {
    this.loadingLines.set(true);
    // Nur offene Umsätze (unmatched/suggested) — gebuchte/ignorierte ausblenden.
    this.api.listStatementLines({}).subscribe({
      next: (all) => {
        const open = all.filter((l) => l.matchState === 'unmatched' || l.matchState === 'suggested');
        this.lines.set(open);
        const chosen: Record<string, string> = {};
        for (const l of open) chosen[l.id] = l.suggestedBudgetId ?? '';
        this.chosenBudget.set(chosen);
        this.loadingLines.set(false);
      },
      error: () => {
        this.lines.set([]);
        this.loadingLines.set(false);
      },
    });
  }

  // ---------------------------------------------- persönliche Zugangsdaten (#fints-percred)
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
    this.connectCollapsed.set(false);
  }

  toggleConnect(): void {
    this.connectCollapsed.update((v) => !v);
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

  // ------------------------------------------------------------------ FinTS
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
          // decoupled: noch nicht freigegeben.
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

  /** Nach Sperr-/Ablehnungsfehler den Verbindungs-Status neu laden, damit der Cooldown
   *  (``fintsLockedUntil``) den Abruf-Button sperrt (#fints-review). */
  private refreshOnLock(e: unknown): void {
    const code = (e as { error?: { code?: string } })?.error?.code;
    const acc = this.accountId();
    if (acc && (code === 'fints_bank_locked' || code === 'fints_auth_rejected')) {
      this.loadCredStatus(acc);
    }
  }

  private handleSync(res: BankSyncResult): void {
    if (res.status === 'needs_tan') {
      this.sessionToken.set(res.sessionToken ?? '');
      this.challenge.set(res.challenge ?? '');
      // Nur echte Bild-Data-URLs ins <img>-Binding lassen (Defense-in-Depth, #fints-review):
      // der Server liefert sie zwar geprüft, aber wir vertrauen dem String nicht blind.
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

  // ------------------------------------------------------------------- file
  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.uploadFile(file);
    input.value = ''; // gleiche Datei erneut wählbar
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
      },
      error: () => {
        this.importing.set(false);
        this.toast.error(this.i18n.translate('fints.errFile'));
      },
    });
  }

  // Drag&Drop in der Datei-Lasche (Muster wie Anhänge-Panel).
  onDragEnter(event: DragEvent): void {
    if (!this.accountId() || !this.hasFiles(event)) return;
    event.preventDefault();
    this.dragDepth++;
    this.dragActive.set(true);
  }

  onDragOver(event: DragEvent): void {
    if (!this.accountId() || !this.hasFiles(event)) return;
    event.preventDefault();
  }

  onDragLeave(event: DragEvent): void {
    if (!this.dragActive()) return;
    event.preventDefault();
    this.dragDepth = Math.max(0, this.dragDepth - 1);
    if (this.dragDepth === 0) this.dragActive.set(false);
  }

  onDrop(event: DragEvent): void {
    if (!this.accountId()) return;
    event.preventDefault();
    this.dragDepth = 0;
    this.dragActive.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.uploadFile(file);
  }

  private hasFiles(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes('Files');
  }

  // -------------------------------------------------------------- reconcile
  setChosen(lineId: string, budgetId: string): void {
    this.chosenBudget.update((m) => ({ ...m, [lineId]: budgetId }));
  }

  confirm(line: StatementLine): void {
    const budgetId = this.chosenBudget()[line.id];
    if (!budgetId || this.confirmingId()) return;
    this.confirmingId.set(line.id);
    this.api.confirmStatementLine(line.id, { budgetId: budgetId as Uuid }).subscribe({
      next: () => {
        this.confirmingId.set('');
        this.lines.update((ls) => ls.filter((l) => l.id !== line.id));
        this.toast.success(this.i18n.translate('fints.booked'));
        this.changed.emit();
      },
      error: () => {
        this.confirmingId.set('');
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  ignore(line: StatementLine): void {
    if (this.confirmingId()) return;
    this.confirmingId.set(line.id);
    this.api.ignoreStatementLine(line.id).subscribe({
      next: () => {
        this.confirmingId.set('');
        this.lines.update((ls) => ls.filter((l) => l.id !== line.id));
        this.changed.emit();
      },
      error: () => {
        this.confirmingId.set('');
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  // ----------------------------------------------------- Filter/Sortierung
  setKind(k: '' | ExpenseKind): void {
    this.filterKind.set(k);
  }

  onSearch(value: string): void {
    this.searchQ.set(value);
  }

  onAmountFilter(which: 'min' | 'max', value: string): void {
    (which === 'min' ? this.amountMin : this.amountMax).set(value);
  }

  resetFilters(): void {
    this.filterKind.set('');
    this.searchQ.set('');
    this.amountMin.set('');
    this.amountMax.set('');
  }

  onSort(field: 'date' | 'amount'): void {
    if (this.sortField() === field) {
      this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    } else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
  }

  sortInd(field: 'date' | 'amount'): string {
    if (this.sortField() !== field) return '';
    return this.sortOrder() === 'asc' ? ' ↑' : ' ↓';
  }

  ariaSort(field: 'date' | 'amount'): 'ascending' | 'descending' | 'none' {
    if (this.sortField() !== field) return 'none';
    return this.sortOrder() === 'asc' ? 'ascending' : 'descending';
  }

  // ---------------------------------------------------------- TAN-OTP-Eingabe
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
    } else if (ev.key === 'ArrowLeft' && i > 0) {
      this.focusOtp(i - 1);
    } else if (ev.key === 'ArrowRight' && i < this.otpLength - 1) {
      this.focusOtp(i + 1);
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

  /** Fallback aktivieren, falls die Bank eine TAN ≠ 6 Stellen schickt (#fints). */
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
    this.host.nativeElement
      .querySelector<HTMLInputElement>(`[data-otp="${i}"]`)
      ?.focus();
  }

  /** IBAN-Längen je Land (ISO 13616) — Spiegel der Backend-Tabelle. Eine an den Namen geklebte
   *  Gegen-IBAN wird über die feste Länge abgespalten, daher klappt das auch für NL/GB & Co.,
   *  deren BBAN Buchstaben enthält (z. B. ``NL70CITI…``) — eine reine „Ziffern"-Regel scheiterte. */
  private static readonly IBAN_LEN: Record<string, number> = {
    AD: 24, AT: 20, BE: 16, BG: 22, CH: 21, CY: 28, CZ: 24, DE: 22, DK: 18, EE: 20,
    ES: 24, FI: 18, FR: 27, GB: 22, GR: 27, HR: 21, HU: 28, IE: 22, IS: 26, IT: 27,
    LI: 21, LT: 20, LU: 20, LV: 21, MC: 27, MT: 31, NL: 18, NO: 15, PL: 28, PT: 25,
    RO: 24, SE: 24, SI: 19, SK: 24, SM: 27,
  };

  /** ISO-13616-mod-97-Prüfung (stückweise, ohne BigInt): erste 4 Zeichen ans Ende, Buchstaben
   *  → Zahl (A=10…Z=35), fortlaufend mod 97 — Ergebnis muss 1 sein. */
  private static ibanMod97Ok(iban: string): boolean {
    let rem = 0;
    const r = iban.slice(4) + iban.slice(0, 4);
    for (const ch of r) {
      const v = Number.parseInt(ch, 36);
      if (Number.isNaN(v)) return false;
      rem = (rem * (v > 9 ? 100 : 10) + v) % 97;
    }
    return rem === 1;
  }

  /** Führende (an den Namen geklebte) IBAN erkennen → `{ iban, rest }` oder `null`. */
  private detectIban(text: string): { iban: string; rest: string } | null {
    const m = /^[A-Z]{2}\d{2}[A-Z0-9]+/.exec(text);
    if (!m) return null;
    const len = BankImportDialogComponent.IBAN_LEN[text.slice(0, 2)];
    if (!len || m[0].length < len) return null;
    const cand = text.slice(0, len);
    if (!BankImportDialogComponent.ibanMod97Ok(cand)) return null;
    return { iban: cand, rest: text.slice(len).trim() };
  }

  /** IBAN in Vierergruppen darstellen (`DE70 1203 0000 1076 8788 08`). */
  formatIban(iban: string): string {
    const compact = iban.replace(/\s+/g, '').toUpperCase();
    return (compact.match(/.{1,4}/g) ?? [compact]).join(' ');
  }

  /** Sparkassen-Zusatz „… DATUM dd.mm.yyyy, hh.mm UHR" für die Anzeige vom Zweck lösen.
   *  Neu importierte Umsätze sind bereits sauber; das greift nur für vor dem Parser-Fix
   *  gestagete Altbestände. */
  purposeClean(purpose: string | null | undefined): string {
    return (purpose ?? '')
      .replace(/\s*DATUM\s+\d{2}\.\d{2}\.\d{4},?\s+\d{2}[.:]\d{2}\s*UHR\s*$/i, '')
      .trim();
  }

  /** Gegenkonto in Name + (gruppierte) IBAN trennen (#fints). Manche Bank-Felder liefern beides
   *  in EINEM Feld ohne Trenner ("DE70…808Quentin Walz") und ein leeres IBAN-Feld → führende
   *  IBAN abspalten, damit Name und IBAN je auf eigener Zeile stehen. */
  counterparty(l: StatementLine): { name: string; iban: string } {
    let iban = (l.counterpartyIban ?? '').trim();
    let name = (l.counterpartyName ?? '').trim();
    if (iban && name.startsWith(iban)) {
      name = name.slice(iban.length).trim();
    } else if (!iban) {
      const det = this.detectIban(name);
      if (det) {
        iban = det.iban;
        name = det.rest;
      }
    }
    return { name, iban: iban ? this.formatIban(iban) : '' };
  }

  money(amount: string): string {
    const n = Math.abs(Number(amount));
    return n.toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
      style: 'currency',
      currency: 'EUR',
    });
  }

  close(): void {
    // Einmal-TAN + Challenge nicht über das Schließen hinaus im (dauerhaft gemounteten)
    // Component-State liegen lassen (#fints-review). Ebenso die eingetippte PIN.
    this.resetTan();
    this.editingCred.set(false);
    this.credPin.set('');
    this.closed.emit();
  }
}
