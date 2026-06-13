import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
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
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { downloadBlob } from '@shared/download.util';
import {
  BudgetTreeApi,
  type Invoice,
  type InvoiceParseResult,
  type InvoiceStatus,
} from '../budget/budget-tree.api';

/**
 * Rechnungen-Tab (#invoices): Belege sehen/anlegen/verwalten — eigenständige Entität,
 * Buchungen verweisen optional auf **eine** Rechnung (1 : N).
 *
 * Import (#15): ein ZUGFeRD/Factur-X-PDF wird per Drag&Drop (Overlay) oder Datei-Picker
 * geparst; die Felder füllen den Erfassungs-Dialog vor (Review + Bestätigen). Ist kein
 * gültiges ZUGFeRD eingebettet (422 ``invoice_not_zugferd``), öffnet der leere Dialog
 * zur manuellen Erfassung.
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
export class InvoicesComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly canManage = computed(() => this.auth.can('budget.book'));

  readonly items = signal<Invoice[]>([]);
  readonly loading = signal(true);
  readonly q = signal('');
  readonly saving = signal(false);
  readonly importing = signal(false);
  /** Manueller Beleg-Upload im Anlegen-Dialog läuft (#invoices). */
  readonly attaching = signal(false);

  /** Filter (Buchungen-Stil): Status, Brutto-Bereich, Rechnungs-/Fälligkeitsdatum. */
  readonly statusFilter = signal<'' | InvoiceStatus>('');
  readonly grossMin = signal('');
  readonly grossMax = signal('');
  readonly issueFrom = signal('');
  readonly issueTo = signal('');
  readonly dueFrom = signal('');
  readonly dueTo = signal('');

  /** Zahl aktiver Filter (für den Indikator am Filter-Button) — ohne die Suche. */
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

  /** Client-seitige Suche (Nummer/Lieferant/Notiz) + Status-/Betrags-/Datums-Filter. */
  readonly visible = computed(() => {
    const needle = this.q().trim().toLowerCase();
    const status = this.statusFilter();
    const gMin = this.grossMin().trim() ? Number(this.grossMin()) : null;
    const gMax = this.grossMax().trim() ? Number(this.grossMax()) : null;
    const issueFrom = this.issueFrom();
    const issueTo = this.issueTo();
    const dueFrom = this.dueFrom();
    const dueTo = this.dueTo();
    return this.items().filter((i) => {
      if (
        needle &&
        ![i.number, i.supplier, i.note].some((v) => (v ?? '').toLowerCase().includes(needle))
      )
        return false;
      if (status && i.status !== status) return false;
      const gross = Number(i.grossAmount);
      if (gMin !== null && gross < gMin) return false;
      if (gMax !== null && gross > gMax) return false;
      if (!this.inDateRange(i.issueDate, issueFrom, issueTo)) return false;
      if (!this.inDateRange(i.dueDate, dueFrom, dueTo)) return false;
      return true;
    });
  });

  /** ISO-Datums (YYYY-MM-DD) vergleichen sich lexikografisch. Ohne Datum fällt eine
   *  Zeile aus jedem gesetzten Bereich. */
  private inDateRange(date: string | null | undefined, from: string, to: string): boolean {
    if (!from && !to) return true;
    if (!date) return false;
    if (from && date < from) return false;
    if (to && date > to) return false;
    return true;
  }

  resetFilters(): void {
    this.statusFilter.set('');
    this.grossMin.set('');
    this.grossMax.set('');
    this.issueFrom.set('');
    this.issueTo.set('');
    this.dueFrom.set('');
    this.dueTo.set('');
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

  // --- Anlegen / Import ---
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
  /** Beleg-Handle aus dem Import (leer = manuell). */
  readonly importToken = signal('');
  readonly importFileName = signal('');
  private importFileMime = '';

  readonly canSubmitCreate = computed(() => Number(this.newGross()) > 0);

  // --- Bearbeiten / Löschen ---
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
    this.loading.set(true);
    this.api.listInvoices().subscribe({
      next: (rows) => {
        this.items.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.items.set([]);
        this.loading.set(false);
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

  /** PDF parsen (#15): Erfolg → Dialog vorgefüllt; kein ZUGFeRD → leerer Dialog. */
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
          // Kein eingebettetes ZUGFeRD → manuell erfassen, aber das gedroppte PDF
          // trotzdem als Beleg anhängen (#invoices).
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
    // Dubletten-Warnung: gleiche Rechnungsnummer existiert bereits (#invoices).
    if (p.duplicate) {
      this.toast.show(
        this.i18n.translate('invoices.toast.duplicate', { number: p.number ?? '' }),
        'warning',
      );
    }
  }

  /** Beleg-PDF hochladen + als Anhang merken (manuell oder Nicht-ZUGFeRD-Drop). */
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
    // API streamt das PDF (MinIO ist intern). Blob → Objekt-URL im neuen Tab;
    // ``downloadBlob`` löst zuverlässig aus (auch async, ohne Popup-Blocker).
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
