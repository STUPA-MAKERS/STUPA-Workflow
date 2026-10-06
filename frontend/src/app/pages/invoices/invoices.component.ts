import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
  type WritableSignal,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, type ParamMap, Router } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  SegmentedComponent,
  type SegmentedOption,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  EmptyStateComponent,
  FileDropZoneComponent,
  ListDetailLayoutComponent,
  PageHeaderComponent,
  ListItemComponent,
  RangeChipComponent,
  type RangeValue,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SearchPillComponent,
  SideSheetComponent,
  SkeletonComponent,
  StatusTextComponent,
  StickyBarComponent,
  invoiceStatus,
} from '@shared/ui';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { downloadBlob } from '@shared/download.util';
import { mediaQuerySignal } from '../../layout/media-query';
import { PageFrameService } from '../../layout/page-frame.service';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type Invoice,
  type InvoiceParseResult,
  type InvoiceQuery,
  type InvoiceSegmentCounts,
  type InvoiceStatus,
} from '../budget/budget-tree.api';
import { costCentreIndex, formatEur, monthGroups, shortDate } from '../budget/expense-display.util';
import { InvoiceDetailComponent } from './invoice-detail/invoice-detail.component';
import {
  type InvoiceFormHost,
  InvoiceFormComponent,
  invoiceFieldsValid,
} from './invoice-form/invoice-form.component';

/** What the import found, for the note at the top of the review form. */
export type ImportNotice = 'parsed' | 'manual' | null;

/**
 * The segments of the list: every invoice, "Eingang" (open, no booking), "Verbucht"
 * (open, with a booking), "Bezahlt".
 */
export type InvoiceSegment = 'all' | 'inbox' | 'booked' | 'paid';

const SEGMENTS: readonly InvoiceSegment[] = ['all', 'inbox', 'booked', 'paid'];

/** The query of a segment. */
const SEGMENT_QUERY: Record<InvoiceSegment, Pick<InvoiceQuery, 'status' | 'booked'>> = {
  all: {},
  inbox: { status: 'open', booked: false },
  booked: { status: 'open', booked: true },
  paid: { status: 'paid' },
};

/**
 * Invoices (boards Fin-Rechnungen and the other Fin-Rechnung* boards): a list of invoices
 * beside a detail sheet, like the applications page. An invoice is a document of its own;
 * a booking can reference one invoice, so one invoice can serve many bookings.
 *
 * The list: title with the import; the search and the chips (invoice date, due date,
 * amount); the segments Alle / Eingang / Verbucht / Bezahlt with their counts; the drop
 * zone; the rows by month. The detail: the open invoice (`?id=`, also the target of the
 * global search), or the form of a new, an imported or an edited invoice.
 *
 * Import: a ZUGFeRD or Factur-X PDF dropped on the page or picked with the file dialog.
 * The parsed fields fill the review form. A PDF without ZUGFeRD data (422
 * `invoice_not_zugferd`) opens the empty form for manual entry, with the PDF as receipt.
 */
@Component({
  selector: 'app-invoices',
  // A pane page (styles.scss): side by side the panes fill the free height and scroll by
  // themselves.
  host: { '[class.pane-page]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    ButtonComponent,
    DialogComponent,
    EmptyStateComponent,
    FileDropZoneComponent,
    IconComponent,
    InvoiceDetailComponent,
    InvoiceFormComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    NgTemplateOutlet,
    RangeChipComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SegmentedComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    StickyBarComponent,
    TranslatePipe,
  ],
  templateUrl: './invoices.component.html',
  styleUrl: './invoices.component.scss',
})
export class InvoicesComponent implements OnDestroy, InvoiceFormHost {
  private readonly api = inject(BudgetTreeApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly frame = inject(PageFrameService);

  readonly canManage = computed(() => this.auth.can('budget.book'));

  /** < 768px: one primary action in the title row, the rest in a menu; forms as a sheet. */
  readonly phone = mediaQuerySignal(MEDIA.phone);
  /** The list-detail layout, for its split state. */
  private readonly layout = viewChild(ListDetailLayoutComponent);
  readonly split = computed(() => this.layout()?.collapsed() === false);

  /** The status as coloured text. */
  readonly invoiceStatus = invoiceStatus;

  /** The page actions that do not fit the title row of a phone. */
  readonly phoneMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'import', label: this.i18n.translate('invoices.import'), icon: 'upload' }] },
  ]);

  /** The cost-centre tree, for the swatches of the bookings in the detail. It loads once
   *  the first open invoice with a booking shows up. */
  readonly tree = signal<BudgetTreeNode[]>([]);
  private treeRequested = false;
  readonly costCentres = computed(() => costCentreIndex(this.tree()));

  private readonly PAGE = 20;
  readonly items = signal<Invoice[]>([]);
  readonly total = signal(0);
  /** The size of each segment under the other filters; null from a backend before FE10c. */
  readonly counts = signal<InvoiceSegmentCounts | null>(null);
  private nextOffset = 0;
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());
  readonly q = signal('');
  readonly saving = signal(false);
  readonly importing = signal(false);
  /** True while a manual receipt upload runs in the create form. */
  readonly attaching = signal(false);
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  /** Monotone request generation: a late answer of an older filter state is dropped. */
  private fetchEpoch = 0;

  readonly segment = signal<InvoiceSegment>('all');
  readonly grossMin = signal('');
  readonly grossMax = signal('');
  readonly issueFrom = signal('');
  readonly issueTo = signal('');
  readonly dueFrom = signal('');
  readonly dueTo = signal('');

  /**
   * Every filter of the chips and the search, declared once.
   *
   * The count, the reset and the request each read this list. A filter added to one and
   * forgotten in another is invisible: the control moves and the list does not change.
   * `filterSignals` is what the spec walks. The segment is not a filter of this list: it
   * keeps its value when the filters reset.
   */
  readonly filterSignals: readonly {
    readonly signal: WritableSignal<string>;
    readonly key: keyof InvoiceQuery;
    readonly numeric?: boolean;
  }[] = [
    { signal: this.grossMin, key: 'grossMin', numeric: true },
    { signal: this.grossMax, key: 'grossMax', numeric: true },
    { signal: this.issueFrom, key: 'issueFrom' },
    { signal: this.issueTo, key: 'issueTo' },
    { signal: this.dueFrom, key: 'dueFrom' },
    { signal: this.dueTo, key: 'dueTo' },
    { signal: this.q, key: 'q' },
  ];

  /** Active filters as the query part of a list request, with the segment. */
  filterParams(): InvoiceQuery {
    const params: InvoiceQuery = { ...SEGMENT_QUERY[this.segment()] };
    for (const f of this.filterSignals) {
      const value = f.signal().trim();
      if (value === '') continue;
      Object.assign(params, { [f.key]: f.numeric ? Number(value) : value });
    }
    return params;
  }

  /** The number of set filters (chips and search). */
  readonly activeFilterCount = computed(
    () => this.filterSignals.filter((f) => f.signal().trim() !== '').length,
  );

  /** The segments with their counts. */
  readonly segmentOptions = computed<SegmentedOption[]>(() => {
    const c = this.counts();
    return SEGMENTS.map((value) => ({
      value,
      label: this.i18n.translate(`invoices.segment.${value}`),
      count: c ? c[value] : null,
    }));
  });

  // --- the open row ------------------------------------------------------------------
  /** The invoice open in the detail (`?id=`). */
  readonly selectedId = signal('');
  private readonly fetchedInvoice = signal<Invoice | null>(null);
  readonly selectedMissing = signal(false);

  readonly selectedInvoice = computed<Invoice | null>(() => {
    const id = this.selectedId();
    if (!id) return null;
    const row = this.items().find((i) => i.id === id);
    if (row) return row;
    const fetched = this.fetchedInvoice();
    return fetched?.id === id ? fetched : null;
  });

  /** The rows by the month of their invoice date. */
  readonly groups = computed(() =>
    monthGroups(this.items(), (i) => i.issueDate ?? i.createdAt, this.i18n.locale()),
  );

  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');
  readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');

  /** Debounced search, about 400 ms. It drives the `q` param of the server query. */
  onSearch(value: string): void {
    this.q.set(value);
    this.debouncedReload();
  }

  setSegment(value: string): void {
    const next = (SEGMENTS as readonly string[]).includes(value) ? (value as InvoiceSegment) : 'all';
    if (next === this.segment()) return;
    this.segment.set(next);
    this.reload();
  }

  onGrossRange(v: RangeValue): void {
    this.grossMin.set(v.from);
    this.grossMax.set(v.to);
    this.reload();
  }

  onIssueRange(v: RangeValue): void {
    this.issueFrom.set(v.from);
    this.issueTo.set(v.to);
    this.reload();
  }

  onDueRange(v: RangeValue): void {
    this.dueFrom.set(v.from);
    this.dueTo.set(v.to);
    this.reload();
  }

  resetFilters(): void {
    for (const f of this.filterSignals) f.signal.set('');
    this.reload();
  }

  private debouncedReload(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reload(), 400);
  }

  ngOnDestroy(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.frame.fill.set(false);
  }

  readonly fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');

  /** What the import found: the note at the top of the review form. */
  readonly importNotice = signal<ImportNotice>(null);
  /** The number of an invoice that exists already (N31), or null. */
  readonly importDuplicate = signal<string | null>(null);

  private dragDepth = 0;
  readonly dragActive = signal(false);

  readonly statusOptions = computed<SelectOption[]>(() =>
    (['open', 'paid'] as const).map((v) => ({
      value: v,
      label: this.i18n.translate(`invoices.status.${v}`),
    })),
  );

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
  /** Receipt handle from the import. An empty value means manual entry. */
  readonly importToken = signal('');
  readonly importFileName = signal('');
  /** The size of the dropped or picked file in bytes, 0 when unknown. */
  readonly importFileSize = signal(0);
  private importFileMime = '';

  /** Number, supplier and a positive gross are required (board Fin-Rechnung-Import). */
  readonly canSubmitCreate = computed(() =>
    invoiceFieldsValid(this.newNumber(), this.newSupplier(), this.newGross()),
  );

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
  /**
   * The edit keeps a stored number or supplier: the field cannot become empty. An
   * invoice without them (from the API, the MCP server or an older import) still saves,
   * for example a change of its status to paid.
   */
  readonly editNumberRequired = computed(() => !!this.editing()?.number);
  readonly editSupplierRequired = computed(() => !!this.editing()?.supplier);
  readonly canSubmitEdit = computed(
    () =>
      (!this.editNumberRequired() || this.editNumber().trim() !== '') &&
      (!this.editSupplierRequired() || this.editSupplier().trim() !== '') &&
      Number(this.editGross()) > 0,
  );
  readonly confirmDelete = signal<Invoice | null>(null);
  /** "Als bezahlt markieren" runs for this invoice. */
  readonly markingPaid = signal<string | null>(null);

  /** The open form, or null. */
  readonly formMode = computed<'create' | 'edit' | null>(() =>
    this.createOpen() ? 'create' : this.editing() ? 'edit' : null,
  );

  /** The heading of the form sheet of a phone. */
  readonly formTitle = computed(() => {
    const mode = this.formMode();
    if (mode === 'edit') return this.i18n.translate('invoices.edit');
    if (mode === 'create' && this.importNotice() === 'parsed') {
      return this.i18n.translate('invoices.importReview');
    }
    return this.i18n.translate('invoices.add');
  });

  /** What the detail pane shows. */
  readonly detailView = computed<'form' | 'invoice' | 'missing' | 'none'>(() => {
    if (this.formMode() && !this.phone()) return 'form';
    if (this.selectedInvoice()) return 'invoice';
    if (this.selectedId() && this.selectedMissing()) return 'missing';
    return 'none';
  });

  /** One pane at a time the detail shows while a row or a form is open. */
  readonly detailOpen = computed(() => (!!this.formMode() && !this.phone()) || !!this.selectedId());

  constructor() {
    this.adoptUrl(this.route.snapshot.queryParamMap);
    this.reload();

    // The palette can send us here while we are already here: a hit on another invoice
    // changes only the query string, and the router keeps this component alive.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      if (this.adoptUrl(qp)) this.reload();
    });

    // Write the filters back, so the URL always states what the list is showing.
    // `replaceUrl`, so filtering does not fill the back button with one entry per
    // keystroke. The open row is a navigation of its own (see `openInvoice`).
    effect(() => {
      const queryParams: Record<string, string | null> = {
        seg: this.segment() === 'all' ? null : this.segment(),
      };
      for (const f of this.filterSignals) {
        queryParams[f.key as string] = f.signal().trim() || null;
      }
      untracked(
        () =>
          void this.router.navigate([], {
            relativeTo: this.route,
            queryParams,
            queryParamsHandling: 'merge',
            replaceUrl: true,
          }),
      );
    });

    // The rows are tracked too: a reload can drop the open invoice from the list (for
    // example after "Als bezahlt markieren" in "Eingang"). It then loads by its id.
    effect(() => {
      const id = this.selectedId();
      const loading = this.loading();
      const rows = this.items();
      untracked(() => this.ensureSelected(id, loading, rows));
    });
    effect(() => {
      const inv = this.selectedInvoice();
      untracked(() => this.loadTreeOnce(inv));
    });

    effect(() => this.frame.fill.set(this.split()));

    // Infinite scroll. Side by side the list scrolls inside its own box.
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const root = this.split() ? (this.scroller()?.nativeElement ?? null) : null;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { root, rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  /**
   * Adopt the filters, the segment and the open row of the URL. Returns whether a filter
   * of the list changed.
   */
  private adoptUrl(qp: ParamMap): boolean {
    let changed = false;
    for (const f of this.filterSignals) {
      // Absence clears: each of these is written back by the effect in the constructor.
      const next = this.sanitizeFilter(f, qp.get(f.key as string) ?? '');
      if (next !== f.signal()) {
        f.signal.set(next);
        changed = true;
      }
    }
    const raw = qp.get('seg') ?? 'all';
    const seg = (SEGMENTS as readonly string[]).includes(raw) ? (raw as InvoiceSegment) : 'all';
    if (seg !== this.segment()) {
      this.segment.set(seg);
      changed = true;
    }
    const id = qp.get('id') ?? '';
    if (id !== this.selectedId()) {
      // A click on another row while a form is open: the row replaces the form, so the
      // highlighted row and the detail always agree.
      if (id) this.closeForms();
      this.selectedId.set(id);
      this.selectedMissing.set(false);
    }
    return changed;
  }

  /**
   * A query string is typed by whoever holds the link, so it can name a value the chips
   * could never produce. A bad number would reach the request as `NaN`.
   */
  private sanitizeFilter(f: { readonly numeric?: boolean }, raw: string): string {
    const value = raw.trim();
    if (value === '') return '';
    if (f.numeric) return Number.isFinite(Number(value)) ? value : '';
    return value;
  }

  money(amount: string): string {
    return formatEur(Number(amount), this.i18n.locale());
  }

  day(iso: string | null): string {
    return shortDate(iso, this.i18n.locale());
  }

  /** The title of a row: the supplier, else the number. */
  titleOf(i: Invoice): string {
    return i.supplier || i.number || this.i18n.translate('invoices.untitled');
  }

  /** Reload page 0 after a filter change, without emptying the list first. */
  private reload(): void {
    this.fetchEpoch++;
    this.nextOffset = 0;
    this.loading.set(this.items().length === 0);
    this.loadingMore.set(false);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  private fetch(initial: boolean): void {
    const epoch = this.fetchEpoch;
    this.api
      .listInvoicesPaged({
        ...this.filterParams(),
        limit: this.PAGE,
        offset: this.nextOffset,
      })
      .subscribe({
        next: (page) => {
          if (epoch !== this.fetchEpoch) return;
          this.total.set(page.total);
          this.counts.set(page.counts ?? null);
          this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loading.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          if (epoch !== this.fetchEpoch) return;
          if (initial) {
            this.items.set([]);
            this.total.set(0);
          }
          this.loading.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  /** Load the open invoice when it is not among the loaded rows (a deep link, or a row
   *  that a reload dropped). */
  private ensureSelected(id: string, loading: boolean, rows: readonly Invoice[]): void {
    if (!id || loading || rows.some((i) => i.id === id)) return;
    if (this.fetchedInvoice()?.id === id) return;
    this.api.getInvoice(id).subscribe({
      next: (inv) => {
        if (this.selectedId() !== id) return;
        this.fetchedInvoice.set(inv);
      },
      error: () => {
        if (this.selectedId() === id) this.selectedMissing.set(true);
      },
    });
  }

  /** Load the tree for the swatches, once, and only when a booking needs a colour. */
  private loadTreeOnce(inv: Invoice | null): void {
    if (this.treeRequested || !(inv?.linkedBookings?.length ?? 0)) return;
    this.treeRequested = true;
    this.api.tree().subscribe({
      next: (nodes) => this.tree.set(nodes),
      error: () => this.tree.set([]),
    });
  }

  // --- the open row ------------------------------------------------------------------
  /** Open an invoice in the detail. The URL keeps it, so the back button closes it. */
  openInvoice(id: string): void {
    this.closeForms();
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { id },
      queryParamsHandling: 'merge',
    });
  }

  /** "Zur Liste": close the form, else the open row. */
  closeDetail(): void {
    if (this.formMode()) {
      this.closeForms();
      return;
    }
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { id: null },
      queryParamsHandling: 'merge',
    });
  }

  closeForms(): void {
    this.createOpen.set(false);
    this.editing.set(null);
  }

  // --- import ----------------------------------------------------------------------
  /** A drag event that the drop zone handles itself. The page overlay leaves it alone, so
   *  one drop never imports twice. */
  private inDropZone(event: DragEvent): boolean {
    const target = event.target as Element | null;
    return !!target && typeof target.closest === 'function' && !!target.closest('app-file-drop-zone');
  }

  onDragEnter(event: DragEvent): void {
    if (!this.canManage() || !this.hasFiles(event) || this.inDropZone(event)) return;
    event.preventDefault();
    this.dragDepth++;
    this.dragActive.set(true);
  }

  onDragOver(event: DragEvent): void {
    if (!this.canManage() || !this.hasFiles(event)) return;
    event.preventDefault();
  }

  onDragLeave(event: DragEvent): void {
    if (!this.dragActive() || this.inDropZone(event)) return;
    event.preventDefault();
    this.dragDepth = Math.max(0, this.dragDepth - 1);
    if (this.dragDepth === 0) this.dragActive.set(false);
  }

  onDrop(event: DragEvent): void {
    if (!this.canManage()) return;
    if (this.inDropZone(event)) {
      this.dragDepth = 0;
      this.dragActive.set(false);
      return;
    }
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

  /** Files from the drop zone. One import at a time, so the first PDF counts. */
  onZoneFiles(files: File[]): void {
    if (this.canManage() && files[0]) this.importFile(files[0]);
  }

  /** The zone takes PDFs only. */
  onZoneRejected(): void {
    this.toast.error(this.i18n.translate('invoices.toast.notPdf'));
  }

  onHeaderMenu(item: RowMenuItem): void {
    if (item.id === 'import') this.fileInput()?.nativeElement.click();
  }

  /** Parse a PDF. On success, prefill the form. Without ZUGFeRD data, open it empty. */
  private importFile(file: File): void {
    if (this.importing()) return;
    this.importing.set(true);
    this.api.parseInvoice(file).subscribe({
      next: (parsed) => {
        this.importing.set(false);
        this.prefillFromParse(parsed, file.size);
      },
      error: (err) => {
        this.importing.set(false);
        const code = (err as { error?: { code?: string } } | null)?.error?.code;
        if (code === 'invoice_not_zugferd') {
          // The PDF embeds no ZUGFeRD data. The user enters the invoice manually.
          // The dropped PDF still becomes the receipt.
          this.openCreate();
          this.importNotice.set('manual');
          this.attachFile(file);
        } else {
          this.toast.error(this.problemDetail(err));
        }
      },
    });
  }

  private prefillFromParse(p: InvoiceParseResult, size: number): void {
    this.closeForms();
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
    this.importFileSize.set(size);
    this.importFileMime = p.fileMime;
    this.importNotice.set('parsed');
    // The server sets the flag when an invoice with the same number exists. The form
    // shows it as a warning above the fields (N31).
    this.importDuplicate.set(p.duplicate ? (p.number ?? '') : null);
    this.createOpen.set(true);
  }

  /** Upload the receipt PDF and keep it as an attachment. It serves manual entry and a
   *  drop without ZUGFeRD data. */
  private attachFile(file: File): void {
    if (this.attaching()) return;
    this.attaching.set(true);
    this.api.uploadInvoiceFile(file).subscribe({
      next: (res) => {
        this.attaching.set(false);
        this.importToken.set(res.fileToken);
        this.importFileName.set(res.fileName);
        this.importFileSize.set(file.size);
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
    this.importFileSize.set(0);
    this.importFileMime = '';
  }

  /**
   * "Vorhandene öffnen" at a duplicate: search for the number in every segment. The
   * review closes; the list shows the invoice that exists.
   */
  openDuplicate(): void {
    const number = this.importDuplicate();
    if (!number) return;
    this.closeForms();
    this.q.set(number);
    this.segment.set('all');
    this.reload();
  }

  // --- forms -----------------------------------------------------------------------
  openCreate(): void {
    this.closeForms();
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
    this.importFileSize.set(0);
    this.importFileMime = '';
    this.importNotice.set(null);
    this.importDuplicate.set(null);
    this.createOpen.set(true);
  }

  create(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitCreate() || this.saving()) return;
    this.saving.set(true);
    this.api
      .createInvoice({
        number: this.newNumber().trim(),
        supplier: this.newSupplier().trim(),
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
        next: (created) => {
          this.saving.set(false);
          this.createOpen.set(false);
          this.toast.success(this.i18n.translate('invoices.toast.created'));
          this.reload();
          if (created?.id) this.openInvoice(created.id);
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  openEdit(i: Invoice): void {
    this.closeForms();
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
    if (!i || !this.canSubmitEdit() || this.saving()) return;
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
          this.replaceRow(updated);
          this.toast.success(this.i18n.translate('invoices.toast.saved'));
          // The status or the amount can move the invoice to another segment.
          if (updated.status !== i.status) this.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  /** "Als bezahlt markieren": the existing update with `status: paid`. */
  markPaid(i: Invoice): void {
    if (this.markingPaid() || i.status === 'paid') return;
    this.markingPaid.set(i.id);
    this.api.updateInvoice(i.id, { status: 'paid' }).subscribe({
      next: (updated) => {
        this.markingPaid.set(null);
        this.replaceRow(updated);
        this.toast.success(this.i18n.translate('invoices.toast.paid'));
        // The invoice leaves "Eingang" and "Verbucht"; the counts change.
        this.reload();
      },
      error: (err) => {
        this.markingPaid.set(null);
        this.toast.error(this.problemDetail(err));
      },
    });
  }

  /** "Buchung anlegen": the booking form of the bookings page with this invoice. */
  createBooking(i: Invoice): void {
    void this.router.navigate(['/expenses'], { queryParams: { new: 'booking', invoice: i.id } });
  }

  /**
   * Put a saved invoice into the list. The open invoice is also kept apart: a reload
   * after a status change can drop its row from the segment, and the detail must still
   * show it.
   */
  private replaceRow(updated: Invoice): void {
    this.items.update((list) => list.map((x) => (x.id === updated.id ? { ...x, ...updated } : x)));
    if (updated.id === this.selectedId() || this.fetchedInvoice()?.id === updated.id) {
      this.fetchedInvoice.set(updated);
    }
  }

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
        this.closeForms();
        this.items.update((list) => list.filter((x) => x.id !== i.id));
        this.total.update((t) => Math.max(0, t - 1));
        this.toast.success(this.i18n.translate('invoices.toast.deleted'));
        if (i.id === this.selectedId()) this.closeDetail();
        this.reload();
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('invoices.toast.failed'));
      },
    });
  }

  openFile(i: Invoice): void {
    // The API streams the PDF because MinIO is internal. `downloadBlob` turns the
    // blob into an object URL and opens it in a new tab. This works for an async
    // call. Popup blockers do not stop it.
    this.api.invoiceFileBlob(i.id).subscribe({
      next: (blob) => downloadBlob(blob, i.fileName || 'beleg.pdf'),
      error: () => this.toast.error(this.i18n.translate('invoices.toast.failed')),
    });
  }

  /** The row menu of an invoice. */
  rowMenu(i: Invoice): RowMenuSection[] {
    const items: RowMenuItem[] = [];
    if (this.canManage()) {
      items.push({ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' });
      if (i.status === 'open') {
        items.push({ id: 'paid', label: this.i18n.translate('invoices.markPaid'), icon: 'check' });
      }
      items.push({ id: 'book', label: this.i18n.translate('invoices.createBooking'), icon: 'add' });
    }
    if (i.hasFile) items.push({ id: 'file', label: this.i18n.translate('invoices.openFile'), icon: 'file' });
    const sections: RowMenuSection[] = items.length ? [{ items }] : [];
    if (this.canManage()) {
      sections.push({
        items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }],
      });
    }
    return sections;
  }

  onRowMenu(item: RowMenuItem, i: Invoice): void {
    if (item.id === 'edit') this.openEdit(i);
    else if (item.id === 'paid') this.markPaid(i);
    else if (item.id === 'book') this.createBooking(i);
    else if (item.id === 'file') this.openFile(i);
    else if (item.id === 'delete') this.askDelete(i);
  }

  rowMenuLabel(i: Invoice): string {
    return this.i18n.translate('invoices.rowMenu', { number: i.number || i.supplier || '' });
  }

  private problemDetail(err: unknown): string {
    const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
    return detail || this.i18n.translate('invoices.toast.failed');
  }
}
