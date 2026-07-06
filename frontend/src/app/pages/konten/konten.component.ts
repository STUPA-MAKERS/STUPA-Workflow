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
import { RouterLink } from '@angular/router';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CheckboxComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  type AccountOption,
  BudgetTreeApi,
  type Expense,
  type ExpenseKind,
  type StatementLine,
} from '../budget/budget-tree.api';
import type { Uuid } from '@core/api/models';
import { PALETTE } from '../budget/budget-year-tree.component';
import { ariaSortDir, formatEur, sortIndicator } from '../budget/expense-display.util';
import { splitCounterparty } from './konten.util';
import { FintsSyncState } from './fints-sync.state';
import { KontenLinesState, type StatementSortField } from './konten-lines.state';
import { KontenReconcileState } from './konten-reconcile.state';
import { HScrollSyncDirective } from '@shared/h-scroll-sync.directive';
import { PressSelectDirective } from '@shared/press-select.directive';

/**
 * Accounts tab: per bank account all fetched transactions + balance; each line
 * is linked to at most one booking. FinTS login/sync/TAN live here. Thin facade
 * over the state modules below; its public surface also drives the specs.
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
    CheckboxComponent,
    HScrollSyncDirective,
    PressSelectDirective,
    RouterLink,
  ],
  templateUrl: './konten.component.html',
  styleUrl: './konten.component.scss',
})
export class KontenComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  // Referenced via the same root instances by the state modules; specs spy here.
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly api = inject(BudgetTreeApi);

  private readonly linesState = new KontenLinesState();
  private readonly sync = new FintsSyncState(this.linesState, this.host);
  private readonly reconcile = new KontenReconcileState(this.linesState);

  /** Sync/import/link/unlink need budget.book; view-only hides them. */
  readonly canBook = computed(() => this.auth.can('budget.book'));
  /** Ignoring/reactivating a line needs the dedicated audit-sensitive permission. */
  readonly canIgnore = computed(() => this.auth.can('budget.reconcile_ignore'));
  /** Mobile only: account list behind a collapsible toggle. */
  readonly treeOpen = signal(false);
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  // --- lines state (KontenLinesState) ----------------------------------------
  readonly accounts = this.linesState.accounts;
  readonly accountId = this.linesState.accountId;
  readonly selectedAccount = this.linesState.selectedAccount;
  readonly accountOptions = this.linesState.accountOptions;
  readonly lines = this.linesState.lines;
  readonly loadingLines = this.linesState.loadingLines;
  readonly loadingMore = this.linesState.loadingMore;
  readonly total = this.linesState.total;
  readonly hasMore = this.linesState.hasMore;
  readonly filterState = this.linesState.filterState;
  readonly kind = this.linesState.kind;
  readonly searchQ = this.linesState.searchQ;
  readonly dateFrom = this.linesState.dateFrom;
  readonly dateTo = this.linesState.dateTo;
  readonly sortField = this.linesState.sortField;
  readonly sortOrder = this.linesState.sortOrder;
  readonly activeFilterCount = this.linesState.activeFilterCount;
  readonly refreshing = this.linesState.refreshing;

  // --- batch / bulk actions (#expenses-ux) ---
  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkBusy = signal(false);
  readonly selectedCount = computed(() => this.selected().size);
  readonly allSelected = computed(() => {
    const list = this.lines();
    return list.length > 0 && list.every((l) => this.selected().has(l.id));
  });
  /** Selection subsets by match state → drive which bulk button is active. */
  readonly selectedMatched = computed(
    () =>
      this.lines().filter((l) => this.selected().has(l.id) && l.matchState === 'matched').length,
  );
  readonly selectedIgnorable = computed(
    () =>
      this.lines().filter(
        (l) =>
          this.selected().has(l.id) &&
          (l.matchState === 'unmatched' || l.matchState === 'suggested'),
      ).length,
  );
  readonly bulkConfirm = signal<null | 'unlink' | 'ignore'>(null);

  // --- FinTS state (FintsSyncState) --------------------------------------------
  readonly credStatus = this.sync.credStatus;
  readonly connectOpen = this.sync.connectOpen;
  readonly credLogin = this.sync.credLogin;
  readonly credPin = this.sync.credPin;
  readonly savingCred = this.sync.savingCred;
  readonly configured = this.sync.configured;
  readonly connected = this.sync.connected;
  readonly locked = this.sync.locked;
  readonly lockedUntilLabel = this.sync.lockedUntilLabel;
  readonly syncing = this.sync.syncing;
  readonly sessionToken = this.sync.sessionToken;
  readonly challenge = this.sync.challenge;
  readonly challengeImage = this.sync.challengeImage;
  readonly decoupled = this.sync.decoupled;
  readonly tanCode = this.sync.tanCode;
  readonly tanBusy = this.sync.tanBusy;
  readonly hasPendingTan = this.sync.hasPendingTan;
  readonly otpLength = this.sync.otpLength;
  readonly otpSlots = this.sync.otpSlots;
  readonly otpDigits = this.sync.otpDigits;
  readonly otpMode = this.sync.otpMode;
  readonly tanReady = this.sync.tanReady;

  // --- reconcile state (KontenReconcileState) ------------------------------------
  readonly costCentreOptions = this.reconcile.costCentreOptions;
  readonly fiscalYearOptions = this.reconcile.fiscalYearOptions;
  readonly importLine = this.reconcile.importLine;
  readonly impBudgetId = this.reconcile.impBudgetId;
  readonly impFiscalYearId = this.reconcile.impFiscalYearId;
  readonly impDescription = this.reconcile.impDescription;
  readonly booking = this.reconcile.booking;
  readonly linkLine = this.reconcile.linkLine;
  readonly linkQuery = this.reconcile.linkQuery;
  readonly linkCandidates = this.reconcile.linkCandidates;
  readonly linkSelected = this.reconcile.linkSelected;
  readonly linkLoading = this.reconcile.linkLoading;
  readonly ignoreLine = this.reconcile.ignoreLine;
  readonly ignoreReason = this.reconcile.ignoreReason;

  constructor() {
    // Account picked → load lines + connection status. fetch() reads the filter
    // signals inside this effect, so filter changes re-trigger it by design.
    effect(() => {
      const acc = this.accountId();
      if (acc) {
        this.linesState.reloadLines();
        this.sync.loadCredStatus(acc);
      }
    });
    // Keep the bulk selection pruned to rows that still exist (after refresh/reload/account switch).
    effect(() => {
      const ids = new Set(this.lines().map((l) => l.id));
      this.selected.update((cur) =>
        [...cur].every((x) => ids.has(x)) ? cur : new Set([...cur].filter((x) => ids.has(x))),
      );
    });
    // Infinite scroll: sentinel at the table end → next page.
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
    this.linesState.dispose();
    this.reconcile.dispose();
  }

  // --- display helpers ------------------------------------------------------------
  /** Unsigned amount (the sign is rendered separately). */
  money(amount: string): string {
    return formatEur(Math.abs(Number(amount)), this.i18n.locale());
  }

  /** Balance keeps its sign (negative = overdrawn). */
  balanceMoney(amount: string): string {
    return formatEur(Number(amount), this.i18n.locale());
  }

  signedMoney(l: StatementLine): string {
    return (l.kind === 'income' ? '+' : '−') + this.money(l.amount);
  }

  counterparty(l: StatementLine): { name: string; iban: string } {
    return splitCounterparty(l);
  }

  /** Colour dot per account, palette rotated by index (like the budget picker). */
  dotColor(index: number): string {
    return PALETTE[((index % PALETTE.length) + PALETTE.length) % PALETTE.length];
  }

  accountBalance(a: AccountOption): string {
    return a.fintsLastBalance !== null ? this.balanceMoney(a.fintsLastBalance) : '';
  }

  sortInd(field: StatementSortField): string {
    return sortIndicator(this.sortField() === field, this.sortOrder());
  }

  ariaSort(field: StatementSortField): 'ascending' | 'descending' | 'none' {
    return ariaSortDir(this.sortField() === field, this.sortOrder());
  }

  // --- account / list delegates ----------------------------------------------------
  selectAccount(id: string): void {
    if (id === this.accountId()) return;
    this.accountId.set(id);
    this.sync.resetTan();
  }

  reloadLines(): void {
    this.linesState.reloadLines();
  }

  loadMore(): void {
    this.linesState.loadMore();
  }

  setState(s: '' | 'open' | 'linked' | 'ignored'): void {
    this.linesState.setState(s);
  }

  setKind(k: '' | ExpenseKind): void {
    this.linesState.setKind(k);
  }

  onDateFilter(which: 'from' | 'to', value: string): void {
    this.linesState.onDateFilter(which, value);
  }

  resetFilters(): void {
    this.linesState.resetFilters();
  }

  onSearch(v: string): void {
    this.linesState.onSearch(v);
  }

  onSort(field: StatementSortField): void {
    this.linesState.onSort(field);
  }

  // --- FinTS delegates ---------------------------------------------------------------
  openConnect(): void {
    this.sync.openConnect();
  }

  closeConnect(): void {
    this.sync.closeConnect();
  }

  saveCred(): void {
    this.sync.saveCred();
  }

  removeCred(): void {
    this.sync.removeCred();
  }

  startSync(): void {
    this.sync.startSync();
  }

  submitTan(): void {
    this.sync.submitTan();
  }

  closeTan(): void {
    this.sync.closeTan();
  }

  onOtpInput(i: number, ev: Event): void {
    this.sync.onOtpInput(i, ev);
  }

  onOtpKeydown(i: number, ev: KeyboardEvent): void {
    this.sync.onOtpKeydown(i, ev);
  }

  onOtpPaste(ev: ClipboardEvent): void {
    this.sync.onOtpPaste(ev);
  }

  useSingleTanField(): void {
    this.sync.useSingleTanField();
  }

  private syncError(e: unknown): string {
    return this.sync.syncError(e);
  }

  private refreshOnLock(e: unknown): void {
    this.sync.refreshOnLock(e);
  }

  // --- reconcile delegates --------------------------------------------------------------
  candidateLabel(e: Expense): string {
    return this.reconcile.candidateLabel(e);
  }

  openImport(line: StatementLine): void {
    this.reconcile.openImport(line);
  }

  onPickImportBudget(id: string): void {
    this.reconcile.onPickImportBudget(id);
  }

  closeImport(): void {
    this.reconcile.closeImport();
  }

  confirmImport(): void {
    this.reconcile.confirmImport();
  }

  openLink(line: StatementLine): void {
    this.reconcile.openLink(line);
  }

  onLinkSearch(q: string): void {
    this.reconcile.onLinkSearch(q);
  }

  pickLinkCandidate(e: Expense): void {
    this.reconcile.pickLinkCandidate(e);
  }

  closeLink(): void {
    this.reconcile.closeLink();
  }

  confirmLink(): void {
    this.reconcile.confirmLink();
  }

  unlink(line: StatementLine): void {
    this.reconcile.unlink(line);
  }

  openIgnore(line: StatementLine): void {
    this.reconcile.openIgnore(line);
  }

  closeIgnore(): void {
    this.reconcile.closeIgnore();
  }

  confirmIgnore(): void {
    this.reconcile.confirmIgnore();
  }

  reactivate(line: StatementLine): void {
    this.reconcile.reactivate(line);
  }

  // --- cross-links (#expenses-ux) ---------------------------------------------------
  /** Deep-link to a matched line's booking. Exact via the allocation's booking id
   *  (hidden, resettable ``id`` filter in the Bookings tab); older lines without a
   *  ``matchedExpenseId`` fall back to account + reference/purpose text search. */
  bookingLink(
    line: StatementLine,
  ): { id: string } | { account: string; q: string | null } {
    if (line.matchedExpenseId) return { id: line.matchedExpenseId };
    return {
      account: line.accountId,
      q: line.reference || line.endToEndId || line.purpose || null,
    };
  }

  // --- batch (#expenses-ux) ---------------------------------------------------------
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
    this.selected.set(checked ? new Set(this.lines().map((l) => l.id)) : new Set());
  }


  askBulk(kind: 'unlink' | 'ignore'): void {
    const n = kind === 'unlink' ? this.selectedMatched() : this.selectedIgnorable();
    if (!n) return;
    this.bulkConfirm.set(kind);
  }
  runBulk(): void {
    const kind = this.bulkConfirm();
    if (!kind || this.bulkBusy()) return;
    const eligible = this.lines()
      .filter(
        (l) =>
          this.selected().has(l.id) &&
          (kind === 'unlink'
            ? l.matchState === 'matched'
            : l.matchState === 'unmatched' || l.matchState === 'suggested'),
      )
      .map((l) => l.id);
    if (!eligible.length) {
      this.bulkConfirm.set(null);
      return;
    }
    this.bulkBusy.set(true);
    let done = 0;
    from(eligible)
      .pipe(
        concatMap((id) =>
          kind === 'unlink' ? this.api.unlinkStatementLine(id) : this.api.ignoreStatementLine(id),
        ),
      )
      .subscribe({
        next: () => {
          done++;
        },
        error: () => this.afterBulk(kind, done, true),
        complete: () => this.afterBulk(kind, done, false),
      });
  }
  private afterBulk(kind: 'unlink' | 'ignore', count: number, failed: boolean): void {
    this.bulkBusy.set(false);
    this.bulkConfirm.set(null);
    this.linesState.refresh();
    if (failed) {
      this.toast.error(this.i18n.translate('konten.bulk.error'));
    } else {
      const key = kind === 'unlink' ? 'konten.bulk.unlinkDone' : 'konten.bulk.ignoreDone';
      this.toast.success(this.i18n.translate(key, { count: String(count) }));
    }
  }
}
