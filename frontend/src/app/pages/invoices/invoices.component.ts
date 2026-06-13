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
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
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
    IconComponent,
    SelectComponent,
  ],
  template: `
    <div
      class="inv"
      (dragenter)="onDragEnter($event)"
      (dragover)="onDragOver($event)"
      (dragleave)="onDragLeave($event)"
      (drop)="onDrop($event)"
    >
      <header class="inv__head">
        <div>
          <h1 class="inv__title">{{ 'invoices.title' | t }}</h1>
          <p class="inv__subtitle">{{ 'invoices.subtitle' | t }}</p>
        </div>
        <div class="inv__headActions">
          <input
            class="inv__search"
            type="search"
            [placeholder]="'invoices.search' | t"
            [ngModel]="q()"
            (ngModelChange)="q.set($event)"
            [attr.aria-label]="'invoices.search' | t"
          />
          @if (canManage()) {
            <input
              #fileInput
              type="file"
              accept="application/pdf,.pdf"
              class="inv__fileInput"
              (change)="onFilePicked($event)"
              [attr.aria-label]="'invoices.import' | t"
            />
            <app-button variant="secondary" size="sm" [loading]="importing()" (click)="fileInput.click()">
              <span class="inv__btnIcon"><app-icon name="upload" [size]="16" /> {{ 'invoices.import' | t }}</span>
            </app-button>
            <app-button size="sm" (click)="openCreate()">{{ 'invoices.add' | t }}</app-button>
          }
        </div>
      </header>

      @if (loading()) {
        <p class="inv__status" aria-live="polite">{{ 'invoices.loading' | t }}</p>
      } @else {
        <div class="inv__tableWrap">
          <table class="inv__table">
            <thead>
              <tr>
                <th scope="col">{{ 'invoices.col.issueDate' | t }}</th>
                <th scope="col">{{ 'invoices.col.dueDate' | t }}</th>
                <th scope="col">{{ 'invoices.col.number' | t }}</th>
                <th scope="col">{{ 'invoices.col.supplier' | t }}</th>
                <th scope="col" class="inv__num">{{ 'invoices.col.net' | t }}</th>
                <th scope="col" class="inv__num">{{ 'invoices.col.tax' | t }}</th>
                <th scope="col" class="inv__num">{{ 'invoices.col.gross' | t }}</th>
                <th scope="col">{{ 'invoices.col.status' | t }}</th>
                <th scope="col">{{ 'invoices.col.file' | t }}</th>
                @if (canManage()) { <th scope="col" class="inv__num"></th> }
              </tr>
            </thead>
            <tbody>
              @for (i of visible(); track i.id) {
                <tr [attr.title]="i.actor ? ('invoices.bookedBy' | t: { actor: i.actor }) : null">
                  <td class="inv__cellDate">{{ i.issueDate ? (i.issueDate | ldate: 'mediumDate') : '—' }}</td>
                  <td class="inv__cellDate">{{ i.dueDate ? (i.dueDate | ldate: 'mediumDate') : '—' }}</td>
                  <td class="inv__cellNumber">{{ i.number || '—' }}</td>
                  <td class="inv__cellSupplier">{{ i.supplier || '—' }}</td>
                  <td class="inv__num inv__mono">{{ i.netAmount ? money(i.netAmount) : '—' }}</td>
                  <td class="inv__num inv__mono">{{ i.taxAmount ? money(i.taxAmount) : '—' }}</td>
                  <td class="inv__num inv__amount">{{ money(i.grossAmount) }}</td>
                  <td class="inv__cellStatus">
                    <app-badge [variant]="i.status === 'paid' ? 'success' : 'warning'">{{ statusLabel(i.status) }}</app-badge>
                  </td>
                  <td class="inv__cellFile">
                    @if (i.hasFile) {
                      <button type="button" class="inv__fileLink" (click)="openFile(i)">
                        <app-icon name="export" [size]="14" /> {{ i.fileName || ('invoices.openFile' | t) }}
                      </button>
                    } @else { — }
                  </td>
                  @if (canManage()) {
                    <td class="inv__num">
                      <span class="inv__actions">
                        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.edit' | t" [title]="'action.edit' | t" (click)="openEdit(i)"><app-icon name="edit" /></app-button>
                        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.delete' | t" [title]="'action.delete' | t" (click)="askDelete(i)"><app-icon name="delete" /></app-button>
                      </span>
                    </td>
                  }
                </tr>
              } @empty {
                <tr>
                  <td class="inv__empty" [attr.colspan]="canManage() ? 10 : 9">{{ 'invoices.empty' | t }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      <!-- Drop-Overlay (#15): erscheint, solange eine Datei über dem Tab schwebt. -->
      @if (dragActive()) {
        <div class="inv__dropOverlay" aria-hidden="true">
          <div class="inv__dropInner">
            <app-icon name="upload" [size]="32" />
            <span>{{ 'invoices.drop' | t }}</span>
          </div>
        </div>
      }
    </div>

    <!-- Anlegen / Import-Review -->
    <app-dialog
      [open]="createOpen()"
      [title]="(importToken() ? 'invoices.importReview' : 'invoices.add') | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="createOpen.set(false)"
    >
      <form id="inv-create" class="inv__form" (submit)="create($event)">
        @if (importToken()) {
          <div class="inv__fileChip">
            <app-icon name="document" [size]="16" />
            <span class="inv__fileChipName">{{ importFileName() }}</span>
            <span class="inv__fileChipBadge">{{ 'invoices.importedBeleg' | t }}</span>
          </div>
        }

        <div class="inv__grid2">
          <div class="inv__field">
            <label class="inv__label" for="inv-number">{{ 'invoices.field.number' | t }}</label>
            <input id="inv-number" class="inv__input" name="number" [ngModel]="newNumber()" (ngModelChange)="newNumber.set($event)" />
          </div>
          <div class="inv__field">
            <label class="inv__label" for="inv-supplier">{{ 'invoices.field.supplier' | t }}</label>
            <input id="inv-supplier" class="inv__input" name="supplier" [ngModel]="newSupplier()" (ngModelChange)="newSupplier.set($event)" />
          </div>
        </div>

        <div class="inv__grid2">
          <app-datepicker name="issue" [label]="'invoices.field.issueDate' | t" [ngModel]="newIssueDate()" (ngModelChange)="newIssueDate.set($event)" />
          <app-datepicker name="due" [label]="'invoices.field.dueDate' | t" [ngModel]="newDueDate()" (ngModelChange)="newDueDate.set($event)" />
        </div>

        <div class="inv__grid3">
          <div class="inv__field">
            <label class="inv__label">{{ 'invoices.field.net' | t }}</label>
            <app-currency-input name="net" [ngModel]="newNet()" (ngModelChange)="newNet.set($event)" [ariaLabel]="'invoices.field.net' | t" />
          </div>
          <div class="inv__field">
            <label class="inv__label">{{ 'invoices.field.tax' | t }}</label>
            <app-currency-input name="tax" [ngModel]="newTax()" (ngModelChange)="newTax.set($event)" [ariaLabel]="'invoices.field.tax' | t" />
          </div>
          <div class="inv__field">
            <label class="inv__label">{{ 'invoices.field.gross' | t }} *</label>
            <app-currency-input name="gross" [ngModel]="newGross()" (ngModelChange)="newGross.set($event)" [ariaLabel]="'invoices.field.gross' | t" />
          </div>
        </div>

        <app-select name="status" [label]="'invoices.field.status' | t" [options]="statusOptions()" [ngModel]="newStatus()" (ngModelChange)="newStatus.set($event)" />

        <label class="inv__label" for="inv-note">{{ 'invoices.field.note' | t }}</label>
        <textarea id="inv-note" class="inv__input inv__textarea" name="note" rows="3" [ngModel]="newNote()" (ngModelChange)="newNote.set($event)"></textarea>
      </form>
      <div dialog-footer class="inv__dialogFoot">
        <app-button variant="ghost" (click)="createOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!canSubmitCreate()" [loading]="saving()" (click)="create($event)">{{ 'invoices.add' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Bearbeiten -->
    <app-dialog [open]="!!editing()" [title]="'invoices.edit' | t" [closeLabel]="'action.cancel' | t" (closed)="editing.set(null)">
      <form id="inv-edit" class="inv__form" (submit)="saveEdit($event)">
        <div class="inv__grid2">
          <div class="inv__field">
            <label class="inv__label" for="inv-enumber">{{ 'invoices.field.number' | t }}</label>
            <input id="inv-enumber" class="inv__input" name="enumber" [ngModel]="editNumber()" (ngModelChange)="editNumber.set($event)" />
          </div>
          <div class="inv__field">
            <label class="inv__label" for="inv-esupplier">{{ 'invoices.field.supplier' | t }}</label>
            <input id="inv-esupplier" class="inv__input" name="esupplier" [ngModel]="editSupplier()" (ngModelChange)="editSupplier.set($event)" />
          </div>
        </div>
        <div class="inv__grid2">
          <app-datepicker name="eissue" [label]="'invoices.field.issueDate' | t" [ngModel]="editIssueDate()" (ngModelChange)="editIssueDate.set($event)" />
          <app-datepicker name="edue" [label]="'invoices.field.dueDate' | t" [ngModel]="editDueDate()" (ngModelChange)="editDueDate.set($event)" />
        </div>
        <div class="inv__grid3">
          <div class="inv__field">
            <label class="inv__label">{{ 'invoices.field.net' | t }}</label>
            <app-currency-input name="enet" [ngModel]="editNet()" (ngModelChange)="editNet.set($event)" [ariaLabel]="'invoices.field.net' | t" />
          </div>
          <div class="inv__field">
            <label class="inv__label">{{ 'invoices.field.tax' | t }}</label>
            <app-currency-input name="etax" [ngModel]="editTax()" (ngModelChange)="editTax.set($event)" [ariaLabel]="'invoices.field.tax' | t" />
          </div>
          <div class="inv__field">
            <label class="inv__label">{{ 'invoices.field.gross' | t }} *</label>
            <app-currency-input name="egross" [ngModel]="editGross()" (ngModelChange)="editGross.set($event)" [ariaLabel]="'invoices.field.gross' | t" />
          </div>
        </div>
        <app-select name="estatus" [label]="'invoices.field.status' | t" [options]="statusOptions()" [ngModel]="editStatus()" (ngModelChange)="editStatus.set($event)" />
        <label class="inv__label" for="inv-enote">{{ 'invoices.field.note' | t }}</label>
        <textarea id="inv-enote" class="inv__input inv__textarea" name="enote" rows="3" [ngModel]="editNote()" (ngModelChange)="editNote.set($event)"></textarea>
      </form>
      <div dialog-footer class="inv__dialogFoot">
        <app-button variant="ghost" (click)="editing.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!(editGrossValid())" [loading]="saving()" (click)="saveEdit($event)">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Löschen -->
    <app-dialog [open]="!!confirmDelete()" [title]="'invoices.delete.title' | t" [closeLabel]="'action.cancel' | t" (closed)="confirmDelete.set(null)">
      <p>{{ 'invoices.delete.body' | t: { number: confirmDelete()?.number ?? '' } }}</p>
      <div dialog-footer class="inv__dialogFoot">
        <app-button variant="ghost" (click)="confirmDelete.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" [loading]="saving()" (click)="doDelete()">{{ 'invoices.delete.confirm' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host { display: block; }
      .inv { position: relative; min-height: 60vh; }
      .inv__head {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
        margin-bottom: var(--space-5);
      }
      .inv__title { margin: 0; }
      .inv__subtitle { color: var(--color-text-muted); margin: var(--space-1) 0 0; }
      .inv__headActions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
      .inv__btnIcon { display: inline-flex; align-items: center; gap: var(--space-2); }
      .inv__fileInput { display: none; }
      .inv__search, .inv__input {
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        color: var(--color-text);
        font: inherit;
      }
      input.inv__input { height: var(--control-height); box-sizing: border-box; }
      .inv__search { min-width: 14rem; height: 2.25rem; }
      .inv__status { color: var(--color-text-muted); padding: var(--space-4) 0; }
      .inv__empty { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }
      .inv__tableWrap {
        overflow-x: auto;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
      }
      .inv__table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
      .inv__table th, .inv__table td {
        padding: var(--space-2) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
        vertical-align: middle;
      }
      .inv__table tbody tr:last-child td { border-bottom: none; }
      .inv__table tbody tr:hover { background: var(--color-surface-sunken); }
      .inv__table th {
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        white-space: nowrap;
        padding: var(--space-3) var(--space-4);
        background: var(--color-surface-sunken);
      }
      .inv__num { text-align: end; font-variant-numeric: tabular-nums; white-space: nowrap; }
      .inv__cellDate { color: var(--color-text-muted); white-space: nowrap; }
      .inv__cellNumber { font-weight: var(--fw-medium); white-space: nowrap; }
      .inv__cellSupplier { min-width: 10rem; }
      .inv__mono { font-variant-numeric: tabular-nums; color: var(--color-text-muted); }
      .inv__amount { font-variant-numeric: tabular-nums; font-weight: var(--fw-semibold); white-space: nowrap; }
      .inv__fileLink {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        background: transparent;
        border: 0;
        padding: 0;
        cursor: pointer;
        color: var(--color-primary);
        font: inherit;
      }
      .inv__fileLink:hover { text-decoration: underline; }
      .inv__actions { display: inline-flex; gap: var(--space-1); justify-content: flex-end; }
      /* --- Drop-Overlay --- */
      .inv__dropOverlay {
        position: absolute;
        inset: 0;
        z-index: 20;
        display: flex;
        align-items: center;
        justify-content: center;
        background: color-mix(in srgb, var(--color-primary) 12%, var(--color-bg));
        border: 2px dashed var(--color-primary);
        border-radius: var(--radius-lg);
        pointer-events: none;
      }
      .inv__dropInner {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--space-2);
        color: var(--color-primary);
        font-weight: var(--fw-semibold);
      }
      /* --- Dialog --- */
      .inv__form { display: flex; flex-direction: column; gap: var(--space-2); }
      .inv__label { font-size: var(--fs-sm); font-weight: var(--fw-medium); margin-top: var(--space-2); }
      .inv__field { display: flex; flex-direction: column; gap: var(--space-1); }
      .inv__grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); align-items: end; }
      .inv__grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--space-3); align-items: end; }
      @media (max-width: 30rem) { .inv__grid2, .inv__grid3 { grid-template-columns: 1fr; } }
      .inv__textarea { resize: vertical; min-height: 4.5rem; }
      .inv__dialogFoot { display: flex; justify-content: flex-end; gap: var(--space-3); }
      .inv__fileChip {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface-sunken);
      }
      .inv__fileChipName { font-weight: var(--fw-medium); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .inv__fileChipBadge {
        margin-left: auto;
        font-size: var(--fs-xs);
        color: var(--color-primary);
        white-space: nowrap;
      }
      /* Mobil (≤768px): Tabellenzeilen als Karten (rein CSS) — wie Buchungen. */
      @media (max-width: 768px) {
        .inv__search { flex: 1 1 100%; min-width: 0; }
        .inv__tableWrap { overflow-x: visible; border: none; border-radius: 0; background: transparent; }
        .inv__table, .inv__table tbody { display: block; }
        .inv__table thead { display: none; }
        .inv__table tbody tr {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: var(--space-2) var(--space-3);
          padding: var(--space-4);
          margin-bottom: var(--space-3);
          background: var(--color-surface);
          border: var(--border-width) solid var(--color-border);
          border-radius: var(--radius-lg);
        }
        .inv__table tbody tr:last-child { margin-bottom: 0; }
        .inv__table th, .inv__table td { padding: 0; border-bottom: none; }
        .inv__cellNumber { flex: 1 1 100%; order: -3; }
        .inv__cellStatus { order: -2; }
        .inv__amount { order: -1; margin-left: auto; font-size: var(--fs-md); }
        .inv__cellDate, .inv__cellSupplier, .inv__cellFile, .inv__mono {
          flex: 0 1 auto;
          order: 1;
          font-size: var(--fs-xs);
          color: var(--color-text-muted);
        }
        .inv__actions { margin-left: auto; }
        .inv__num:has(.inv__actions) { order: 2; flex: 1 1 100%; }
        .inv__empty { flex: 1 1 100%; padding: var(--space-6) !important; }
      }
    `,
  ],
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

  /** Client-seitige Suche über Nummer/Lieferant/Notiz. */
  readonly visible = computed(() => {
    const needle = this.q().trim().toLowerCase();
    if (!needle) return this.items();
    return this.items().filter((i) =>
      [i.number, i.supplier, i.note].some((v) => (v ?? '').toLowerCase().includes(needle)),
    );
  });

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
          // Kein eingebettetes ZUGFeRD → manuell erfassen (leerer Dialog).
          this.openCreate();
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
    this.api.invoiceFileUrl(i.id).subscribe({
      next: ({ url }) => window.open(url, '_blank', 'noopener'),
      error: () => this.toast.error(this.i18n.translate('invoices.toast.failed')),
    });
  }

  private problemDetail(err: unknown): string {
    const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
    return detail || this.i18n.translate('invoices.toast.failed');
  }
}
