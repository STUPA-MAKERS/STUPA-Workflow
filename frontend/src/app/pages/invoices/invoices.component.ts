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
import { FormsModule } from '@angular/forms';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
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
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';
import {
  BudgetTreeApi,
  type Invoice,
  type InvoiceParseResult,
  type InvoiceStatus,
} from '../budget/budget-tree.api';

/**
 * Invoices tab: view/create/manage receipts — a standalone entity; bookings
 * optionally reference **one** invoice (1 : N).
 *
 * Import: a ZUGFeRD/Factur-X PDF is parsed via drag & drop (overlay) or the file
 * picker; the fields prefill the entry dialog (review + confirm). If no valid
 * ZUGFeRD is embedded (422 ``invoice_not_zugferd``), the empty dialog opens for
 * manual entry.
 */
@Component({
  selector: 'app-invoices',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    LocalizedDatePipe,
    TranslatePipe,
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
  ],
  templateUrl: './invoices.component.html',
  styleUrl: './invoices.component.scss',
})
export class InvoicesComponent implements OnDestroy {
  private readonly api = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly canManage = computed(() => this.auth.can('budget.book'));

  private readonly PAGE = 20;
  readonly items = signal<Invoice[]>([]);
  readonly total = signal(0);
  private nextOffset = 0;
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());
  readonly q = signal('');
  readonly saving = signal(false);
  readonly importing = signal(false);
  /** A manual receipt upload in the create dialog is in progress. */
  readonly attaching = signal(false);
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  /** Filters (bookings style): status, gross range, issue/due date. These drive
   *  the server query. */
  readonly statusFilter = signal<'' | InvoiceStatus>('');
  readonly grossMin = signal('');
  readonly grossMax = signal('');
  readonly issueFrom = signal('');
  readonly issueTo = signal('');
  readonly dueFrom = signal('');
  readonly dueTo = signal('');

  /** Number of active filters (for the filter-button indicator) — excluding search. */
  readonly activeFilterCount = computed(
    () =>
      [
        this.statusFilter(),
        this.grossMin().trim(),
        this.grossMax().trim(),
        this.issueFrom(),
        this.issueTo(),
        this.dueFrom(),
        this.dueTo(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  /** Search (debounced ~400ms) drives the ``q`` param of the server query. */
  onSearch(value: string): void {
    this.q.set(value);
    this.debouncedReload();
  }

  /** Set the status filter + reload (server filters). */
  setStatus(value: '' | InvoiceStatus): void {
    this.statusFilter.set(value);
    this.reload();
  }

  /** Gross-range filter (debounced, since typed). */
  onGrossFilter(which: 'min' | 'max', value: string): void {
    (which === 'min' ? this.grossMin : this.grossMax).set(value);
    this.debouncedReload();
  }

  /** Date-range filter (issue/due date). */
  onDateFilter(which: 'issueFrom' | 'issueTo' | 'dueFrom' | 'dueTo', value: string): void {
    ({
      issueFrom: this.issueFrom,
      issueTo: this.issueTo,
      dueFrom: this.dueFrom,
      dueTo: this.dueTo,
    })[which].set(value);
    this.debouncedReload();
  }

  resetFilters(): void {
    this.statusFilter.set('');
    this.grossMin.set('');
    this.grossMax.set('');
    this.issueFrom.set('');
    this.issueTo.set('');
    this.dueFrom.set('');
    this.dueTo.set('');
    this.reload();
  }

  private debouncedReload(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reload(), 400);
  }

  ngOnDestroy(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }

  readonly fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');

  // --- Drag&Drop ---
  private dragDepth = 0;
  readonly dragActive = signal(false);

  readonly statusOptions = computed<SelectOption[]>(() =>
    (['open', 'paid'] as const).map((v) => ({
      value: v,
      label: this.i18n.translate(`invoices.status.${v}`),
    })),
  );

  // --- Create / import ---
  readonly createOpen = signal(false);
  readonly newNumber = signal('');
  readonly newSupplier = signal('');
  readonly newIssueDate = signal('');
  readonly newDueDate = signal('');
  readonly newNet = signal('');
  readonly newTax = signal('');
  readonly newGross = signal('');
  readonly newStatus = signal<InvoiceStatus>('open');
  readonly newNote = signal('');
  /** Receipt handle from the import (empty = manual). */
  readonly importToken = signal('');
  readonly importFileName = signal('');
  private importFileMime = '';

  readonly canSubmitCreate = computed(() => Number(this.newGross()) > 0);

  // --- Edit / delete ---
  readonly editing = signal<Invoice | null>(null);
  readonly editNumber = signal('');
  readonly editSupplier = signal('');
  readonly editIssueDate = signal('');
  readonly editDueDate = signal('');
  readonly editNet = signal('');
  readonly editTax = signal('');
  readonly editGross = signal('');
  readonly editStatus = signal<InvoiceStatus>('open');
  readonly editNote = signal('');
  readonly editGrossValid = computed(() => Number(this.editGross()) > 0);
  readonly confirmDelete = signal<Invoice | null>(null);

  constructor() {
    this.reload();

    // Infinite scroll: sentinel at the list end → load the next page.
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

  statusLabel(status: InvoiceStatus): string {
    return this.i18n.translate(status === 'paid' ? 'invoices.status.paid' : 'invoices.status.open');
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

  private fetch(initial: boolean): void {
    this.api
      .listInvoicesPaged({
        q: this.q().trim() || undefined,
        status: this.statusFilter() || undefined,
        grossMin: this.grossMin().trim() ? Number(this.grossMin()) : undefined,
        grossMax: this.grossMax().trim() ? Number(this.grossMax()) : undefined,
        issueFrom: this.issueFrom() || undefined,
        issueTo: this.issueTo() || undefined,
        dueFrom: this.dueFrom() || undefined,
        dueTo: this.dueTo() || undefined,
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
          if (initial) {
            this.items.set([]);
            this.total.set(0);
          }
          this.loading.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  // ----------------------------------------------------------- drag & drop
  onDragEnter(event: DragEvent): void {
    if (!this.canManage() || !this.hasFiles(event)) return;
    event.preventDefault();
    this.dragDepth++;
    this.dragActive.set(true);
  }

  onDragOver(event: DragEvent): void {
    if (!this.canManage() || !this.hasFiles(event)) return;
    event.preventDefault();
  }

  onDragLeave(event: DragEvent): void {
    if (!this.dragActive()) return;
    event.preventDefault();
    this.dragDepth = Math.max(0, this.dragDepth - 1);
    if (this.dragDepth === 0) this.dragActive.set(false);
  }

  onDrop(event: DragEvent): void {
    if (!this.canManage()) return;
    event.preventDefault();
    this.dragDepth = 0;
    this.dragActive.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.importFile(file);
  }

  private hasFiles(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes('Files');
  }

  onFilePicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.importFile(file);
    input.value = '';
  }

  /** Parse a PDF: success → prefilled dialog; no ZUGFeRD → empty dialog. */
  private importFile(file: File): void {
    if (this.importing()) return;
    this.importing.set(true);
    this.api.parseInvoice(file).subscribe({
      next: (parsed) => {
        this.importing.set(false);
        this.prefillFromParse(parsed);
        this.toast.success(this.i18n.translate('invoices.toast.imported'));
      },
      error: (err) => {
        this.importing.set(false);
        const code = (err as { error?: { code?: string } } | null)?.error?.code;
        if (code === 'invoice_not_zugferd') {
          // No embedded ZUGFeRD → enter manually, but still attach the dropped
          // PDF as the receipt.
          this.openCreate();
          this.attachFile(file);
          this.toast.show(this.i18n.translate('invoices.toast.notZugferd'), 'info');
        } else {
          this.toast.error(this.problemDetail(err));
        }
      },
    });
  }

  private prefillFromParse(p: InvoiceParseResult): void {
    this.newNumber.set(p.number ?? '');
    this.newSupplier.set(p.supplier ?? '');
    this.newIssueDate.set(p.issueDate ?? '');
    this.newDueDate.set(p.dueDate ?? '');
    this.newNet.set(p.netAmount ?? '');
    this.newTax.set(p.taxAmount ?? '');
    this.newGross.set(p.grossAmount ?? '');
    this.newStatus.set('open');
    this.newNote.set('');
    this.importToken.set(p.fileToken);
    this.importFileName.set(p.fileName);
    this.importFileMime = p.fileMime;
    this.createOpen.set(true);
    // Duplicate warning: an invoice with the same number already exists.
    if (p.duplicate) {
      this.toast.show(
        this.i18n.translate('invoices.toast.duplicate', { number: p.number ?? '' }),
        'warning',
      );
    }
  }

  /** Upload the receipt PDF + remember it as an attachment (manual or non-ZUGFeRD drop). */
  private attachFile(file: File): void {
    if (this.attaching()) return;
    this.attaching.set(true);
    this.api.uploadInvoiceFile(file).subscribe({
      next: (res) => {
        this.attaching.set(false);
        this.importToken.set(res.fileToken);
        this.importFileName.set(res.fileName);
        this.importFileMime = res.fileMime;
      },
      error: (err) => {
        this.attaching.set(false);
        this.toast.error(this.problemDetail(err));
      },
    });
  }

  onCreateFilePicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) this.attachFile(file);
  }

  clearAttachment(): void {
    this.importToken.set('');
    this.importFileName.set('');
    this.importFileMime = '';
  }

  // ----------------------------------------------------------------- create
  openCreate(): void {
    this.newNumber.set('');
    this.newSupplier.set('');
    this.newIssueDate.set('');
    this.newDueDate.set('');
    this.newNet.set('');
    this.newTax.set('');
    this.newGross.set('');
    this.newStatus.set('open');
    this.newNote.set('');
    this.importToken.set('');
    this.importFileName.set('');
    this.importFileMime = '';
    this.createOpen.set(true);
  }

  create(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitCreate() || this.saving()) return;
    this.saving.set(true);
    this.api
      .createInvoice({
        number: this.newNumber().trim() || null,
        supplier: this.newSupplier().trim() || null,
        issueDate: this.newIssueDate() || null,
        dueDate: this.newDueDate() || null,
        netAmount: this.newNet().trim() || null,
        taxAmount: this.newTax().trim() || null,
        grossAmount: this.newGross(),
        status: this.newStatus(),
        note: this.newNote().trim() || null,
        fileToken: this.importToken() || null,
        fileName: this.importToken() ? this.importFileName() : null,
        fileMime: this.importToken() ? this.importFileMime || null : null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.createOpen.set(false);
          this.toast.success(this.i18n.translate('invoices.toast.created'));
          this.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  // ------------------------------------------------------------------- edit
  openEdit(i: Invoice): void {
    this.editing.set(i);
    this.editNumber.set(i.number ?? '');
    this.editSupplier.set(i.supplier ?? '');
    this.editIssueDate.set(i.issueDate ?? '');
    this.editDueDate.set(i.dueDate ?? '');
    this.editNet.set(i.netAmount ?? '');
    this.editTax.set(i.taxAmount ?? '');
    this.editGross.set(i.grossAmount);
    this.editStatus.set(i.status);
    this.editNote.set(i.note ?? '');
  }

  saveEdit(event: Event): void {
    event.preventDefault();
    const i = this.editing();
    if (!i || !this.editGrossValid() || this.saving()) return;
    this.saving.set(true);
    this.api
      .updateInvoice(i.id, {
        number: this.editNumber().trim() || null,
        supplier: this.editSupplier().trim() || null,
        issueDate: this.editIssueDate() || null,
        dueDate: this.editDueDate() || null,
        netAmount: this.editNet().trim() || null,
        taxAmount: this.editTax().trim() || null,
        grossAmount: this.editGross(),
        status: this.editStatus(),
        note: this.editNote().trim() || null,
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.editing.set(null);
          this.items.update((list) => list.map((x) => (x.id === updated.id ? updated : x)));
          this.toast.success(this.i18n.translate('invoices.toast.saved'));
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  // ----------------------------------------------------------------- delete
  askDelete(i: Invoice): void {
    this.confirmDelete.set(i);
  }

  doDelete(): void {
    const i = this.confirmDelete();
    if (!i || this.saving()) return;
    this.saving.set(true);
    this.api.deleteInvoice(i.id).subscribe({
      next: () => {
        this.saving.set(false);
        this.confirmDelete.set(null);
        this.items.update((list) => list.filter((x) => x.id !== i.id));
        this.total.update((t) => Math.max(0, t - 1));
        this.toast.success(this.i18n.translate('invoices.toast.deleted'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('invoices.toast.failed'));
      },
    });
  }

  // ------------------------------------------------------------------- file
  openFile(i: Invoice): void {
    // The API streams the PDF (MinIO is internal). Blob → object URL in a new tab;
    // ``downloadBlob`` triggers reliably (even async, without popup blockers).
    this.api.invoiceFileBlob(i.id).subscribe({
      next: (blob) => downloadBlob(blob, i.fileName || 'beleg.pdf'),
      error: () => this.toast.error(this.i18n.translate('invoices.toast.failed')),
    });
  }

  private problemDetail(err: unknown): string {
    const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
    return detail || this.i18n.translate('invoices.toast.failed');
  }
}
