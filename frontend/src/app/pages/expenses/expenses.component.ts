import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { downloadBlob } from '@shared/download.util';
import {
  type AccountOption,
  BudgetTreeApi,
  type BudgetTreeNode,
  type Expense,
  type ExpenseKind,
  type FiscalYear,
  type Invoice,
  type PaymentMethod,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { SimplifyPathPipe } from '@shared/budget-path';

/**
 * Ausgaben/Einnahmen-Tab (#25): tatsächliche Buchungen sehen/anlegen/verwalten.
 *
 * Eine Buchung ist **eigenständig** (Kostenstelle + HHJ wählbar) oder an einen
 * **Antrag gebunden** (ersetzt dessen gebundenen Betrag anteilig; Kostenstelle + HHJ
 * werden vom Antrag geerbt). Links filtert ein Kostenstellen-Baum (wie die Antragsliste);
 * die Liste lädt serverseitig per Infinite-Scroll nach.
 */
@Component({
  selector: 'app-expenses',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    LocalizedDatePipe,
    TranslatePipe,
    SimplifyPathPipe,
    BadgeComponent,
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    IconComponent,
    SelectComponent,
    CostCentreTreeComponent,
  ],
  templateUrl: './expenses.component.html',
  styleUrl: './expenses.component.scss',
})
export class ExpensesComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly apps = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly canManage = computed(() => this.auth.can('budget.book'));

  private readonly PAGE = 20;
  readonly budgetTree = signal<BudgetTreeNode[]>([]);
  readonly items = signal<Expense[]>([]);
  readonly total = signal(0);
  private nextOffset = 0;
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());

  readonly kind = signal<'' | ExpenseKind>('');
  readonly q = signal('');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Mobil: Baum hinter einklappbarem Toggle (Desktop immer sichtbar). */
  readonly treeOpen = signal(false);
  readonly sortField = signal<'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate'>(
    'invoiceDate',
  );
  readonly sortOrder = signal<'asc' | 'desc'>('desc');
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  /** Zahl aktiver Filter (für den Indikator am Filter-Button). */
  readonly activeFilterCount = computed(
    () =>
      [
        this.kind(),
        this.amountMin().trim(),
        this.amountMax().trim(),
        this.createdFrom(),
        this.createdTo(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  readonly costCentreOptions = computed<SelectOption[]>(() =>
    flattenBudgetOptions(this.budgetTree()),
  );

  // --- Anlegen-Dialog ---
  readonly createOpen = signal(false);
  readonly newKind = signal<ExpenseKind>('expense');
  readonly newAmount = signal('');
  readonly newDescription = signal('');
  readonly newBudgetId = signal('');
  readonly newFiscalYearId = signal('');
  readonly newApplicationId = signal('');
  readonly appQuery = signal('');
  /** Antrags-Treffer der Typeahead-Suche (max. 8). */
  readonly appCandidates = signal<{ id: string; title: string }[]>([]);
  readonly fiscalYearOptions = signal<SelectOption[]>([]);
  readonly saving = signal(false);
  // Zusatz-Metadaten im Anlegen-Dialog (#1-1/#1-2/#3/#4).
  readonly newInvoiceDate = signal('');
  readonly newPaymentDate = signal('');
  readonly newCorrespondent = signal('');
  readonly newReferenceNumber = signal('');
  readonly newPaymentMethod = signal('');
  readonly newCategory = signal('');
  readonly newNote = signal('');

  /** Zahlungsmethode-Auswahl (#1-2); leerer Wert = keine Angabe. */
  readonly paymentMethodOptions = computed<SelectOption[]>(() =>
    (['ueberweisung', 'bar', 'lastschrift', 'karte', 'paypal'] as const).map((v) => ({
      value: v,
      label: this.i18n.translate(`expenses.paymentMethod.${v}`),
    })),
  );

  // --- Bearbeiten/Löschen ---
  readonly editing = signal<Expense | null>(null);
  readonly editAmount = signal('');
  readonly editDescription = signal('');
  readonly editBudgetId = signal('');
  readonly editAccountId = signal('');
  readonly editInvoiceDate = signal('');
  readonly editPaymentDate = signal('');
  readonly editCorrespondent = signal('');
  readonly editReferenceNumber = signal('');
  readonly editPaymentMethod = signal('');
  readonly editCategory = signal('');
  readonly editNote = signal('');
  readonly confirmDelete = signal<Expense | null>(null);

  // --- Export + Konten ---
  readonly canExport = computed(() => this.auth.can('budget.export'));
  readonly exporting = signal(false);
  readonly accounts = signal<AccountOption[]>([]);
  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );
  readonly newAccountId = signal('');

  // --- Rechnungs-Verknüpfung (#invoices): 1 Rechnung : N Buchungen. ---
  readonly invoices = signal<Invoice[]>([]);
  readonly newInvoiceId = signal('');
  readonly editInvoiceId = signal('');
  /** Offene Rechnungen nach Rechnungsdatum (neueste zuerst, ohne Datum zuletzt). Beim
   *  Buchen wird die gewählte Rechnung serverseitig auf „bezahlt" gesetzt → eine bezahlte
   *  Rechnung darf nicht erneut verknüpft werden, taucht also nicht mehr im Dropdown auf. */
  private readonly openInvoices = computed<Invoice[]>(() =>
    this.invoices()
      .filter((i) => i.status === 'open')
      .sort((a, b) => (b.issueDate ?? '').localeCompare(a.issueDate ?? '')),
  );
  /** Anlegen-Dialog: nur offene Rechnungen. */
  readonly invoiceOptions = computed<SelectOption[]>(() =>
    this.openInvoices().map((i) => ({ value: i.id, label: this.invoiceLabel(i) })),
  );
  /** Bearbeiten-Dialog: offene Rechnungen + die aktuell verknüpfte (ggf. bereits
   *  bezahlte), damit die bestehende Auswahl nicht aus dem Dropdown verschwindet. */
  readonly editInvoiceOptions = computed<SelectOption[]>(() => {
    const opts = this.openInvoices().map((i) => ({ value: i.id, label: this.invoiceLabel(i) }));
    const linkedId = this.editInvoiceId();
    if (linkedId && !opts.some((o) => o.value === linkedId)) {
      const inv = this.invoices().find((i) => i.id === linkedId);
      if (inv) opts.unshift({ value: inv.id, label: this.invoiceLabel(inv) });
    }
    return opts;
  });

  // --- Übertrag-Dialog ---
  readonly transferOpen = signal(false);
  readonly tFromId = signal('');
  readonly tToId = signal('');
  readonly tFiscalYearId = signal('');
  readonly tAmount = signal('');
  readonly tDescription = signal('');
  readonly transferFyOptions = signal<SelectOption[]>([]);
  readonly canSubmitTransfer = computed(
    () =>
      !!this.tFromId() &&
      !!this.tToId() &&
      this.tFromId() !== this.tToId() &&
      !!this.tFiscalYearId() &&
      Number(this.tAmount()) > 0 &&
      !!this.tDescription().trim(),
  );

  readonly canSubmitCreate = computed(() => {
    if (!this.newDescription().trim() || !(Number(this.newAmount()) > 0)) return false;
    // Gebunden: Kostenstelle + HHJ werden vom Antrag geerbt.
    if (this.newApplicationId()) return true;
    // Eigenständig: Kostenstelle **und** HHJ explizit erforderlich (sonst 422).
    return !!this.newBudgetId() && !!this.newFiscalYearId();
  });

  constructor() {
    this.api.tree().subscribe({
      next: (tree) => this.budgetTree.set(tree),
      error: () => this.budgetTree.set([]),
    });
    // Konten-Auswahl (id+Name) für die Bankkonto-Zuordnung — Bucher dürfen das ohne
    // account.manage (#5-2/#2). Server liefert bereits nur aktive Konten.
    this.api.listAccountOptions().subscribe({
      next: (accs) => this.accounts.set(accs),
      error: () => this.accounts.set([]),
    });
    // Rechnungen für das Verknüpfungs-Dropdown (#invoices) — Bucher dürfen lesen.
    this.loadInvoices();
    this.reload();

    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  money(amount: string): string {
    return Number(amount).toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
      style: 'currency',
      currency: 'EUR',
    });
  }

  /** Rechnungs-Label fürs Dropdown: Nummer · Lieferant · Brutto. */
  private invoiceLabel(i: Invoice): string {
    return [i.number, i.supplier, this.money(i.grossAmount)]
      .filter((p) => !!p)
      .join(' · ');
  }

  /** Rechnung im Anlegen-Dialog wählen → relevante Felder aus der Rechnung
   *  übernehmen (Betrag, Empfänger/Zahler, Belegnummer, Rechnungsdatum) (#invoices). */
  onPickInvoice(id: string): void {
    this.newInvoiceId.set(id);
    const inv = this.invoices().find((i) => i.id === id);
    if (!inv) return;
    this.newAmount.set(inv.grossAmount ?? '');
    if (inv.supplier) this.newCorrespondent.set(inv.supplier);
    if (inv.number) this.newReferenceNumber.set(inv.number);
    if (inv.issueDate) this.newInvoiceDate.set(inv.issueDate);
  }

  /** Wie {@link onPickInvoice}, aber für den Bearbeiten-Dialog. */
  onPickEditInvoice(id: string): void {
    this.editInvoiceId.set(id);
    const inv = this.invoices().find((i) => i.id === id);
    if (!inv) return;
    this.editAmount.set(inv.grossAmount ?? '');
    if (inv.supplier) this.editCorrespondent.set(inv.supplier);
    if (inv.number) this.editReferenceNumber.set(inv.number);
    if (inv.issueDate) this.editInvoiceDate.set(inv.issueDate);
  }

  setKind(k: '' | ExpenseKind): void {
    this.kind.set(k);
    this.reload();
  }

  selectBudget(id: string): void {
    this.budgetId.set(id);
    this.reload();
  }

  onSearch(value: string): void {
    this.q.set(value);
    this.debouncedReload();
  }

  onAmountFilter(which: 'min' | 'max', value: string): void {
    (which === 'min' ? this.amountMin : this.amountMax).set(value);
    this.debouncedReload();
  }

  onDateFilter(which: 'from' | 'to', value: string): void {
    (which === 'from' ? this.createdFrom : this.createdTo).set(value);
    this.debouncedReload();
  }

  resetFilters(): void {
    this.kind.set('');
    this.amountMin.set('');
    this.amountMax.set('');
    this.createdFrom.set('');
    this.createdTo.set('');
    this.reload();
  }

  /** Spalten-Sortierung umschalten (gleiche Spalte → Richtung kippen). */
  onSort(field: 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate'): void {
    if (this.sortField() === field) {
      this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    } else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
    this.reload();
  }

  sortInd(field: 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate'): string {
    if (this.sortField() !== field) return '';
    return this.sortOrder() === 'asc' ? ' ↑' : ' ↓';
  }

  ariaSort(
    field: 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate',
  ): 'ascending' | 'descending' | 'none' {
    if (this.sortField() !== field) return 'none';
    return this.sortOrder() === 'asc' ? 'ascending' : 'descending';
  }

  private debouncedReload(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reload(), 400);
  }

  private reload(): void {
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loading.set(true);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  /** Rechnungsliste (neu) laden — nach dem Buchen wechselt eine verknüpfte Rechnung
   *  serverseitig auf „bezahlt" und fällt damit aus dem Offen-Dropdown. */
  private loadInvoices(): void {
    this.api.listInvoices().subscribe({
      next: (rows) => this.invoices.set(rows),
      error: () => this.invoices.set([]),
    });
  }

  private fetch(initial: boolean): void {
    this.api
      .listExpenses({
        budget: this.budgetId() || undefined,
        kind: this.kind() || undefined,
        q: this.q().trim() || undefined,
        amountMin: this.amountMin().trim() ? Number(this.amountMin()) : undefined,
        amountMax: this.amountMax().trim() ? Number(this.amountMax()) : undefined,
        createdFrom: this.createdFrom() || undefined,
        createdTo: this.createdTo() || undefined,
        sort: this.sortField(),
        order: this.sortOrder(),
        limit: this.PAGE,
        offset: this.nextOffset,
      })
      .subscribe({
        next: (page) => {
          this.total.set(page.total);
          this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loading.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          this.loading.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  // --- create ---
  openCreate(): void {
    this.newKind.set('expense');
    this.newAmount.set('');
    this.newDescription.set('');
    this.newBudgetId.set(this.budgetId() || '');
    this.newFiscalYearId.set('');
    this.newApplicationId.set('');
    this.newAccountId.set('');
    this.newInvoiceId.set('');
    this.newInvoiceDate.set('');
    this.newPaymentDate.set('');
    this.newCorrespondent.set('');
    this.newReferenceNumber.set('');
    this.newPaymentMethod.set('');
    this.newCategory.set('');
    this.newNote.set('');
    this.appQuery.set('');
    this.appCandidates.set([]);
    this.fiscalYearOptions.set([]);
    if (this.budgetId()) this.loadFiscalYears(this.budgetId());
    this.createOpen.set(true);
  }

  // --- Export ---
  onExport(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    this.api
      .exportExpensesXlsx({
        budget: this.budgetId() || undefined,
        kind: this.kind() || undefined,
        q: this.q().trim() || undefined,
        amountMin: this.amountMin().trim() || undefined,
        amountMax: this.amountMax().trim() || undefined,
        createdFrom: this.createdFrom() || undefined,
        createdTo: this.createdTo() || undefined,
      })
      .subscribe({
        next: (blob) => {
          downloadBlob(blob, 'buchungen.xlsx');
          this.exporting.set(false);
        },
        error: () => this.exporting.set(false),
      });
  }

  // --- Übertrag ---
  openTransfer(): void {
    this.tFromId.set(this.budgetId() || '');
    this.tToId.set('');
    this.tFiscalYearId.set('');
    this.tAmount.set('');
    this.tDescription.set('');
    this.transferFyOptions.set([]);
    if (this.tFromId()) this.loadTransferFy(this.tFromId());
    this.transferOpen.set(true);
  }

  onTransferFrom(id: string): void {
    this.tFromId.set(id);
    this.tFiscalYearId.set('');
    this.transferFyOptions.set([]);
    if (id) this.loadTransferFy(id);
  }

  private loadTransferFy(budgetId: string): void {
    const top = this.findTop(this.budgetTree(), budgetId);
    if (!top) return;
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys: FiscalYear[]) => {
        this.transferFyOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        const active = fys.filter((f) => f.active);
        if (active.length === 1) this.tFiscalYearId.set(active[0].id);
      },
      error: () => this.transferFyOptions.set([]),
    });
  }

  createTransfer(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitTransfer() || this.saving()) return;
    this.saving.set(true);
    this.api
      .createTransfer({
        fromBudgetId: this.tFromId(),
        toBudgetId: this.tToId(),
        fiscalYearId: this.tFiscalYearId(),
        amount: this.tAmount(),
        description: this.tDescription().trim(),
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.transferOpen.set(false);
          this.toast.success(this.i18n.translate('expenses.transferToast'));
          this.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  setNewKindIncome(): void {
    this.newKind.set('income');
    // Einnahmen sind nicht an Anträge bindbar.
    this.clearApp();
  }

  /** Antrags-Typeahead (wie die Nutzersuche): Treffer als Vorschlagsliste. */
  onAppSearch(value: string): void {
    this.appQuery.set(value);
    const q = value.trim();
    if (!q) {
      this.appCandidates.set([]);
      return;
    }
    this.apps.listApplications({ q, limit: 8 }).subscribe({
      next: (page) =>
        this.appCandidates.set(
          page.items.map((a) => ({ id: a.id, title: a.title || a.id })),
        ),
      error: () => this.appCandidates.set([]),
    });
  }

  pickApp(a: { id: string; title: string }): void {
    this.newApplicationId.set(a.id);
    this.appQuery.set(a.title);
    this.appCandidates.set([]);
  }

  clearApp(): void {
    this.newApplicationId.set('');
    this.appQuery.set('');
    this.appCandidates.set([]);
  }

  onPickBudget(id: string): void {
    this.newBudgetId.set(id);
    this.newFiscalYearId.set('');
    this.fiscalYearOptions.set([]);
    if (id) this.loadFiscalYears(id);
  }

  /** Top-Level-Knoten finden, dessen Unterbaum ``budgetId`` enthält, und HHJ laden. */
  private loadFiscalYears(budgetId: string): void {
    const top = this.findTop(this.budgetTree(), budgetId);
    if (!top) return;
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys: FiscalYear[]) => {
        // Alle HHJ anbieten (Backend lässt explizite, auch inaktive HHJ zu); ein
        // einzelnes aktives HHJ wird vorausgewählt.
        this.fiscalYearOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        const active = fys.filter((f) => f.active);
        if (active.length === 1) this.newFiscalYearId.set(active[0].id);
      },
      error: () => this.fiscalYearOptions.set([]),
    });
  }

  private findTop(nodes: BudgetTreeNode[], targetId: string): BudgetTreeNode | null {
    const contains = (n: BudgetTreeNode): boolean =>
      n.id === targetId || n.children.some(contains);
    return nodes.find((root) => contains(root)) ?? null;
  }

  create(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitCreate() || this.saving()) return;
    const linked = !!this.newApplicationId();
    this.saving.set(true);
    this.api
      .bookExpense({
        amount: this.newAmount(),
        description: this.newDescription().trim(),
        kind: this.newKind(),
        applicationId: linked ? this.newApplicationId() : null,
        budgetId: linked ? null : this.newBudgetId() || null,
        fiscalYearId: linked ? null : this.newFiscalYearId() || null,
        accountId: this.newAccountId() || null,
        invoiceId: this.newInvoiceId() || null,
        invoiceDate: this.newInvoiceDate() || null,
        paymentDate: this.newPaymentDate() || null,
        correspondent: this.newCorrespondent().trim() || null,
        referenceNumber: this.newReferenceNumber().trim() || null,
        paymentMethod: (this.newPaymentMethod() as PaymentMethod) || null,
        category: this.newCategory().trim() || null,
        note: this.newNote().trim() || null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.createOpen.set(false);
          this.toast.success(this.i18n.translate('expenses.toast.created'));
          this.loadInvoices();
          this.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  /** Lesbaren Fehlertext aus dem problem+json (``detail``) ziehen, sonst generisch. */
  private problemDetail(err: unknown): string {
    const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
    return detail || this.i18n.translate('expenses.toast.failed');
  }

  // --- edit ---
  openEdit(e: Expense): void {
    this.editing.set(e);
    this.editAmount.set(e.amount);
    this.editDescription.set(e.description);
    this.editBudgetId.set(e.budgetId);
    this.editAccountId.set(e.accountId ?? '');
    this.editInvoiceId.set(e.invoiceId ?? '');
    this.editInvoiceDate.set(e.invoiceDate ?? '');
    this.editPaymentDate.set(e.paymentDate ?? '');
    this.editCorrespondent.set(e.correspondent ?? '');
    this.editReferenceNumber.set(e.referenceNumber ?? '');
    this.editPaymentMethod.set(e.paymentMethod ?? '');
    this.editCategory.set(e.category ?? '');
    this.editNote.set(e.note ?? '');
  }

  saveEdit(event: Event): void {
    event.preventDefault();
    const e = this.editing();
    if (!e || this.saving()) return;
    this.saving.set(true);
    // Kostenstelle nur bei eigenständigen Buchungen umbuchbar; gebundene erben sie
    // vom Antrag (#25). Nur senden, wenn tatsächlich geändert → kein Audit-Rauschen.
    const budgetChanged =
      !e.applicationId && !!this.editBudgetId() && this.editBudgetId() !== e.budgetId;
    this.api
      .updateExpense(e.id, {
        amount: this.editAmount(),
        description: this.editDescription().trim(),
        ...(budgetChanged ? { budgetId: this.editBudgetId() } : {}),
        accountId: this.editAccountId() || null,
        invoiceId: this.editInvoiceId() || null,
        invoiceDate: this.editInvoiceDate() || null,
        paymentDate: this.editPaymentDate() || null,
        correspondent: this.editCorrespondent().trim() || null,
        referenceNumber: this.editReferenceNumber().trim() || null,
        paymentMethod: (this.editPaymentMethod() as PaymentMethod) || null,
        category: this.editCategory().trim() || null,
        note: this.editNote().trim() || null,
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.editing.set(null);
          this.items.update((list) => list.map((x) => (x.id === updated.id ? updated : x)));
          this.toast.success(this.i18n.translate('expenses.toast.saved'));
          this.loadInvoices();
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('expenses.toast.failed'));
        },
      });
  }

  // --- delete ---
  askDelete(e: Expense): void {
    this.confirmDelete.set(e);
  }

  doDelete(): void {
    const e = this.confirmDelete();
    if (!e || this.saving()) return;
    this.saving.set(true);
    this.api.deleteExpense(e.id).subscribe({
      next: () => {
        this.saving.set(false);
        this.confirmDelete.set(null);
        this.items.update((list) => list.filter((x) => x.id !== e.id));
        this.total.update((t) => Math.max(0, t - 1));
        this.toast.success(this.i18n.translate('expenses.toast.deleted'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('expenses.toast.failed'));
      },
    });
  }
}
