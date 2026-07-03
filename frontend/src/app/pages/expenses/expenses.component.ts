import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import {
  BadgeComponent,
  ButtonComponent,
  CheckboxComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { downloadBlob } from '@shared/download.util';
import type { Uuid } from '@core/api/models';
import {
  type AccountOption,
  BudgetTreeApi,
  type BudgetTreeNode,
  type Expense,
  type ExpenseKind,
  type ExpenseUpdate,
  type FiscalYear,
  type Invoice,
  type PaymentMethod,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { SimplifyPathPipe } from '@shared/budget-path';
import { HScrollSyncDirective } from '@shared/h-scroll-sync.directive';

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
    CheckboxComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    IconComponent,
    SelectComponent,
    CostCentreTreeComponent,
    HScrollSyncDirective,
    RouterLink,
  ],
  templateUrl: './expenses.component.html',
  styleUrl: './expenses.component.scss',
})
export class ExpensesComponent implements OnDestroy {
  private readonly api = inject(BudgetTreeApi);
  private readonly apps = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly canManage = computed(() => this.auth.can('budget.book'));

  private readonly PAGE = 20;
  readonly budgetTree = signal<BudgetTreeNode[]>([]);
  readonly items = signal<Expense[]>([]);
  readonly total = signal(0);
  private nextOffset = 0;
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  /** Nach-Mutations-Refresh läuft: Liste bleibt sichtbar, nur `aria-busy` (#expenses-ux). */
  readonly refreshing = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());

  readonly kind = signal<'' | ExpenseKind>('');
  readonly q = signal('');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Konto-Filter (#expenses-ux): leer = alle Konten. */
  readonly accountId = signal('');
  /** Mobil: Baum hinter einklappbarem Toggle (Desktop immer sichtbar). */
  readonly treeOpen = signal(false);
  readonly sortField = signal<'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate'>(
    'paymentDate',
  );
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  // Beschreibungen kürzen + per Klick aufklappen (#expenses-ux).
  readonly DESC_LIMIT = 90;
  readonly expandedDesc = signal<ReadonlySet<string>>(new Set());
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  // Unterbuchungen (#subbookings): aufgeklappte Buchungen + geladene Kinder + Lade-/Import-Status.
  readonly expandedSub = signal<ReadonlySet<string>>(new Set());
  readonly subRows = signal<ReadonlyMap<string, Expense[]>>(new Map());
  readonly loadingSub = signal<ReadonlySet<string>>(new Set());
  readonly subImporting = signal<ReadonlySet<string>>(new Set());
  // Manuelles Anlegen einer Unterbuchung (Dialog).
  readonly subParent = signal<Expense | null>(null);
  readonly subAmount = signal('');
  readonly subDescription = signal('');
  readonly subPaymentDate = signal('');
  readonly subCorrespondent = signal('');

  /** Zahl aktiver Filter (für den Indikator am Filter-Button). */
  readonly activeFilterCount = computed(
    () =>
      [
        this.kind(),
        this.accountId(),
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
  readonly editInvoiceDate = signal('');
  readonly editPaymentDate = signal('');
  readonly editCorrespondent = signal('');
  readonly editReferenceNumber = signal('');
  readonly editPaymentMethod = signal('');
  readonly editCategory = signal('');
  readonly editNote = signal('');
  readonly confirmDelete = signal<Expense | null>(null);

  // --- Batch / Sammel-Aktionen (#expenses-ux) ---
  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkBusy = signal(false);
  readonly selectedCount = computed(() => this.selected().size);
  readonly allSelected = computed(() => {
    const list = this.items();
    return list.length > 0 && list.every((e) => this.selected().has(e.id));
  });
  /** Sammel-Bestätigung: null = zu, sonst die auszuführende Ja/Nein-Aktion. */
  readonly bulkConfirm = signal<null | 'delete' | 'export'>(null);
  // Sammel-Umbuchung (Kostenstelle/Kategorie) im eigenen Dialog.
  readonly bulkReassignOpen = signal(false);
  readonly bulkBudgetId = signal('');
  readonly bulkCategory = signal('');
  readonly canSubmitReassign = computed(
    () => !!this.bulkBudgetId() || !!this.bulkCategory().trim(),
  );

  // --- Export + Konten ---
  readonly canExport = computed(() => this.auth.can('budget.export'));
  readonly exporting = signal(false);
  readonly accounts = signal<AccountOption[]>([]);
  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );
  /** Konto-Filter-Optionen inkl. „Alle Konten" (Wert ''). */
  readonly accountFilterOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('expenses.filter.allAccounts') },
    ...this.accountOptions(),
  ]);

  // --- Rechnungs-Verknüpfung (#invoices): 1 Rechnung : N Buchungen. ---
  readonly invoices = signal<Invoice[]>([]);
  readonly newInvoiceId = signal('');
  readonly editInvoiceId = signal('');
  /** Detail-Dialog der verknüpften Rechnung einer Buchung (#invoices, read-only). */
  readonly viewingInvoice = signal<Invoice | null>(null);
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
    // Filter aus der URL übernehmen (teilbar + überlebt echten Reload; Ziel von
    // Budget-/Konten-Cross-Links, #expenses-ux) — vor dem ersten reload().
    this.applyQueryParams();
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

  isDescLong(desc: string): boolean {
    return desc.length > this.DESC_LIMIT;
  }

  descExpanded(id: string): boolean {
    return this.expandedDesc().has(id);
  }

  toggleDesc(id: string): void {
    this.expandedDesc.update((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  money(amount: string): string {
    return Number(amount).toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
      style: 'currency',
      currency: 'EUR',
    });
  }

  // ----------------------------------------------------- sub-bookings (#subbookings)
  isSubExpanded(id: string): boolean {
    return this.expandedSub().has(id);
  }
  subOf(id: string): Expense[] {
    return this.subRows().get(id) ?? [];
  }
  isLoadingSub(id: string): boolean {
    return this.loadingSub().has(id);
  }
  isSubImporting(id: string): boolean {
    return this.subImporting().has(id);
  }
  toggleSub(e: Expense): void {
    const open = new Set(this.expandedSub());
    if (open.has(e.id)) {
      open.delete(e.id);
      this.expandedSub.set(open);
      return;
    }
    open.add(e.id);
    this.expandedSub.set(open);
    if (!this.subRows().has(e.id)) this.loadSub(e.id);
  }
  private loadSub(id: string): void {
    this.loadingSub.update((s) => new Set(s).add(id));
    this.api.listSubBookings(id as Uuid).subscribe({
      next: (rows) => {
        this.subRows.update((m) => new Map(m).set(id, rows));
        this.loadingSub.update((s) => {
          const n = new Set(s);
          n.delete(id);
          return n;
        });
      },
      error: () => {
        this.loadingSub.update((s) => {
          const n = new Set(s);
          n.delete(id);
          return n;
        });
        this.toast.error(this.i18n.translate('expenses.sub.loadError'));
      },
    });
  }
  onSubFile(e: Expense, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    this.subImporting.update((s) => new Set(s).add(e.id));
    this.api.importSubBookings(e.id as Uuid, file).subscribe({
      next: (children) => {
        // Vollständige Kinderliste neu laden (Antwort enthält nur den Import-Batch) + Eltern
        // aufklappen; Eltern-Betrag/childCount via reload aktualisieren.
        this.expandedSub.update((s) => new Set(s).add(e.id));
        this.loadSub(e.id);
        this.subImporting.update((s) => {
          const n = new Set(s);
          n.delete(e.id);
          return n;
        });
        this.toast.success(
          this.i18n.translate('expenses.sub.imported', { count: String(children.length) }),
        );
        this.refresh(); // Eltern-Betrag = Σ Kinder hat sich geändert
      },
      error: (err) => {
        this.subImporting.update((s) => {
          const n = new Set(s);
          n.delete(e.id);
          return n;
        });
        const code = (err as { error?: { code?: string } })?.error?.code;
        this.toast.error(
          this.i18n.translate(
            code === 'bank_statement_unparseable' ? 'fints.errFile' : 'expenses.sub.importError',
          ),
        );
      },
    });
  }

  openCreateSub(parent: Expense): void {
    this.subParent.set(parent);
    this.subAmount.set('');
    this.subDescription.set('');
    this.subPaymentDate.set('');
    this.subCorrespondent.set('');
  }
  closeCreateSub(): void {
    this.subParent.set(null);
  }
  canSubmitSub(): boolean {
    return !!this.subAmount().trim() && !!this.subDescription().trim();
  }
  createSub(event?: Event): void {
    event?.preventDefault();
    const parent = this.subParent();
    if (!parent || !this.canSubmitSub() || this.saving()) return;
    this.saving.set(true);
    this.api
      .createSubBooking(parent.id as Uuid, {
        amount: this.subAmount(),
        description: this.subDescription().trim(),
        paymentDate: this.subPaymentDate() || null,
        correspondent: this.subCorrespondent().trim() || null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.closeCreateSub();
          this.expandedSub.update((s) => new Set(s).add(parent.id));
          this.loadSub(parent.id);
          this.toast.success(this.i18n.translate('expenses.sub.added'));
          this.refresh(); // Eltern-Betrag = Σ Kinder
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('expenses.toast.failed'));
        },
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

  selectAccount(id: string): void {
    this.accountId.set(id);
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
    this.accountId.set('');
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

  ngOnDestroy(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }

  private reload(): void {
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loading.set(true);
    this.selected.set(new Set()); // neuer Datensatz → Auswahl verwerfen
    this.syncUrl(); // Filter in die URL spiegeln (teilbar + reload-fest)
    this.fetch(true);
  }

  /** Filter beim Laden aus den Query-Params übernehmen (#expenses-ux): Ziel von
   *  Budget-/Konten-Cross-Links und macht die Filter teilbar. */
  private applyQueryParams(): void {
    const qp = this.route.snapshot.queryParamMap;
    const budget = qp.get('budget');
    const account = qp.get('account');
    const kind = qp.get('kind');
    const q = qp.get('q');
    if (budget) this.budgetId.set(budget);
    if (account) this.accountId.set(account);
    if (kind === 'expense' || kind === 'income') this.kind.set(kind);
    if (q) this.q.set(q);
  }

  /** Aktive Filter in die URL schreiben (merge + replaceUrl), analog Budget-Dashboard. */
  private syncUrl(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        budget: this.budgetId() || null,
        account: this.accountId() || null,
        kind: this.kind() || null,
        q: this.q().trim() || null,
      },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** Deep-Link-Ziel für die Kostenstellen-Zelle → Budget-Tab, auf diese KS gedrillt
   *  (#expenses-ux). Top-Budget wird aus dem geladenen Baum aufgelöst; HHJ steckt in der Zeile. */
  ksLink(e: Expense): { budget: string | null; ks: string; fy: string } {
    const top = this.findTop(this.budgetTree(), e.budgetId);
    return { budget: top?.id ?? null, ks: e.budgetId, fy: e.fiscalYearId };
  }

  /** Nach einer Mutation: das AKTUELL geladene Fenster (offset 0, EIN Request) neu holen
   *  und die Liste atomar ersetzen — kein clear, kein `loading`-Flip → Tabelle bleibt
   *  gemountet, Scroll-Position + alle per Infinite-Scroll geladenen Seiten bleiben (#expenses-ux). */
  private refresh(): void {
    if (this.refreshing()) return;
    const windowLimit = Math.max(this.PAGE, Math.ceil(this.items().length / this.PAGE) * this.PAGE);
    this.refreshing.set(true);
    this.api
      .listExpenses({ ...this.filterParams(), limit: windowLimit, offset: 0 })
      .subscribe({
        next: (page) => {
          this.total.set(page.total);
          this.items.set(page.items);
          this.nextOffset = page.offset + page.items.length;
          this.pruneSelection();
          this.refreshing.set(false);
        },
        error: () => this.refreshing.set(false),
      });
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

  /** Aktive Filter als Query-Teil — Basis für {@link fetch} und {@link refresh}. */
  private filterParams() {
    return {
      budget: this.budgetId() || undefined,
      account: this.accountId() || undefined,
      kind: this.kind() || undefined,
      q: this.q().trim() || undefined,
      amountMin: this.amountMin().trim() ? Number(this.amountMin()) : undefined,
      amountMax: this.amountMax().trim() ? Number(this.amountMax()) : undefined,
      createdFrom: this.createdFrom() || undefined,
      createdTo: this.createdTo() || undefined,
      sort: this.sortField(),
      order: this.sortOrder(),
    };
  }

  private fetch(initial: boolean): void {
    this.api
      .listExpenses({ ...this.filterParams(), limit: this.PAGE, offset: this.nextOffset })
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
          this.refresh();
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
          this.refresh();
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

  // --- verknüpfte Rechnung anzeigen (#invoices) ---
  /** Detail-Dialog zur verknüpften Rechnung öffnen. Die volle Rechnung steckt im
   *  bereits geladenen ``invoices()``-Cache (1 Rechnung : N Buchungen); ohne
   *  ``invoiceId`` ist der Button ohnehin deaktiviert. */
  openInvoiceDialog(e: Expense): void {
    if (!e.invoiceId) return;
    const cached = this.invoices().find((i) => i.id === e.invoiceId);
    if (cached) {
      this.viewingInvoice.set(cached);
      return;
    }
    // Verknüpfte Rechnung (oft bezahlt/älter) kann außerhalb des 200er-Caches
    // liegen → gezielt per ID nachladen, statt den Button stumm verpuffen zu lassen.
    this.api.getInvoice(e.invoiceId).subscribe({
      next: (inv) => this.viewingInvoice.set(inv),
      error: (err) => this.toast.error(this.problemDetail(err)),
    });
  }

  /** Beleg-PDF streamen + herunterladen (MinIO nur intern erreichbar → Blob). */
  openInvoiceFile(inv: Invoice): void {
    this.api.invoiceFileBlob(inv.id).subscribe({
      next: (blob) => downloadBlob(blob, inv.fileName || 'beleg.pdf'),
      error: (err) => this.toast.error(this.problemDetail(err)),
    });
  }

  // --- edit ---
  openEdit(e: Expense): void {
    this.editing.set(e);
    this.editAmount.set(e.amount);
    this.editDescription.set(e.description);
    this.editBudgetId.set(e.budgetId);
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
    // Betrag nur senden, wenn geändert: bei einer Eltern-Buchung (childCount>0) ist er = Σ der
    // Unterbuchungen und serverseitig schreibgeschützt (#subbookings) — unverändert nicht senden.
    const amountChanged = this.editAmount() !== e.amount;
    this.api
      .updateExpense(e.id, {
        ...(amountChanged ? { amount: this.editAmount() } : {}),
        description: this.editDescription().trim(),
        ...(budgetChanged ? { budgetId: this.editBudgetId() } : {}),
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
          if (e.parentExpenseId) {
            // Unterbuchung bearbeitet (#subbookings): Eltern-Panel + Eltern-Betrag aktualisieren.
            this.loadSub(e.parentExpenseId);
            this.refresh();
          } else {
            // childCount/parentExpenseId stehen in der Einzel-Antwort nicht zuverlässig (BE
            // berechnet sie nur im Betrags-Pfad) → aus der bekannten Zeile erhalten (#review).
            const merged = { ...updated, childCount: e.childCount, parentExpenseId: e.parentExpenseId };
            this.items.update((list) => list.map((x) => (x.id === merged.id ? merged : x)));
          }
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
        if (e.parentExpenseId) {
          // Unterbuchung gelöscht (#subbookings): Eltern-Panel + Eltern-Betrag aktualisieren.
          this.loadSub(e.parentExpenseId);
          this.refresh();
        } else {
          this.items.update((list) => list.filter((x) => x.id !== e.id));
          this.total.update((t) => Math.max(0, t - 1));
        }
        this.toast.success(this.i18n.translate('expenses.toast.deleted'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('expenses.toast.failed'));
      },
    });
  }

  // ----------------------------------------------------- batch (#expenses-ux)
  isSelected(id: Uuid): boolean {
    return this.selected().has(id);
  }
  toggleSelect(id: Uuid, checked: boolean): void {
    this.selected.update((cur) => {
      const next = new Set(cur);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }
  toggleSelectAll(checked: boolean): void {
    this.selected.set(checked ? new Set(this.items().map((e) => e.id)) : new Set());
  }
  /** Auswahl auf noch vorhandene Zeilen eindampfen (nach refresh/Sammel-Aktion);
   *  fehlgeschlagene bleiben markiert (Retry möglich). */
  private pruneSelection(): void {
    const ids = new Set(this.items().map((e) => e.id));
    this.selected.update((cur) => new Set([...cur].filter((x) => ids.has(x))));
  }

  askBulk(kind: 'delete' | 'export'): void {
    if (!this.selectedCount()) return;
    this.bulkConfirm.set(kind);
  }
  runBulk(): void {
    if (this.bulkBusy()) return;
    if (this.bulkConfirm() === 'delete') this.runBulkDelete();
    else if (this.bulkConfirm() === 'export') this.runBulkExport();
  }

  private runBulkDelete(): void {
    const ids = [...this.selected()];
    if (!ids.length) return;
    this.bulkBusy.set(true);
    let done = 0;
    from(ids)
      .pipe(concatMap((id) => this.api.deleteExpense(id)))
      .subscribe({
        next: () => {
          done++;
        },
        error: () => this.afterBulk('delete', done, true),
        complete: () => this.afterBulk('delete', done, false),
      });
  }

  /** Nur die ausgewählten Buchungen als .xlsx (Server schränkt per ``ids`` ein). */
  private runBulkExport(): void {
    const ids = [...this.selected()];
    if (!ids.length) return;
    this.bulkBusy.set(true);
    this.api.exportExpensesXlsx({ ids }).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'buchungen-auswahl.xlsx');
        this.bulkBusy.set(false);
        this.bulkConfirm.set(null);
      },
      error: (err) => {
        this.bulkBusy.set(false);
        this.bulkConfirm.set(null);
        this.toast.error(this.problemDetail(err));
      },
    });
  }

  openBulkReassign(): void {
    if (!this.selectedCount()) return;
    this.bulkBudgetId.set('');
    this.bulkCategory.set('');
    this.bulkReassignOpen.set(true);
  }
  runBulkReassign(): void {
    const ids = [...this.selected()];
    if (!ids.length || this.bulkBusy() || !this.canSubmitReassign()) return;
    const byId = new Map(this.items().map((e) => [e.id, e]));
    const budgetId = this.bulkBudgetId();
    const category = this.bulkCategory().trim();
    this.bulkBusy.set(true);
    let done = 0;
    from(ids)
      .pipe(
        concatMap((id) => {
          const e = byId.get(id);
          const patch: ExpenseUpdate = {};
          if (category) patch.category = category;
          // KS nur für eigenständige Buchungen (gebundene/Unterbuchungen erben sie).
          if (budgetId && e && !e.applicationId && !e.parentExpenseId) {
            patch.budgetId = budgetId as Uuid;
          }
          return this.api.updateExpense(id, patch);
        }),
      )
      .subscribe({
        next: () => {
          done++;
        },
        error: () => this.afterBulk('reassign', done, true),
        complete: () => this.afterBulk('reassign', done, false),
      });
  }

  private afterBulk(kind: 'delete' | 'reassign', count: number, failed: boolean): void {
    this.bulkBusy.set(false);
    this.bulkConfirm.set(null);
    this.bulkReassignOpen.set(false);
    this.refresh(); // Server-Wahrheit (z.B. Transfer-Legs) + Auswahl auf Überlebende eindampfen
    if (failed) {
      const key = kind === 'delete' ? 'expenses.bulk.deleteError' : 'expenses.bulk.reassignError';
      this.toast.error(this.i18n.translate(key));
    } else {
      const key = kind === 'delete' ? 'expenses.bulk.deleteDone' : 'expenses.bulk.reassignDone';
      this.toast.success(this.i18n.translate(key, { count: String(count) }));
    }
  }
}
