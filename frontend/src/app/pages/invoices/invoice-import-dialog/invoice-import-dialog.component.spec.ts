import { computed, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import type { Invoice, InvoiceStatus } from '../../budget/budget-tree.api';
import {
  type InvoiceDialogHost,
  InvoiceImportDialogComponent,
  type InvoiceImportNotice,
  invoiceFieldsValid,
} from './invoice-import-dialog.component';

const INVOICE = { id: 'i-1', number: 'R-1', grossAmount: '119.00' } as Invoice;

/** A host with the signals of the invoices page and spies for its methods. */
function fakeHost(): InvoiceDialogHost & {
  importToken: ReturnType<typeof signal<string>>;
  importFileName: ReturnType<typeof signal<string>>;
  importNotice: ReturnType<typeof signal<InvoiceImportNotice>>;
  importDuplicate: ReturnType<typeof signal<string | null>>;
  create: jest.Mock;
  saveEdit: jest.Mock;
  clearAttachment: jest.Mock;
  onCreateFilePicked: jest.Mock;
} {
  const newNumber = signal('');
  const newSupplier = signal('');
  const newGross = signal('');
  const editNumber = signal('');
  const editSupplier = signal('');
  const editGross = signal('');
  return {
    saving: signal(false),
    attaching: signal(false),
    statusOptions: signal([
      { value: 'open', label: 'Offen' },
      { value: 'paid', label: 'Bezahlt' },
    ]),
    createOpen: signal(false),
    newNumber,
    newSupplier,
    newIssueDate: signal(''),
    newDueDate: signal(''),
    newNet: signal(''),
    newTax: signal(''),
    newGross,
    newStatus: signal<InvoiceStatus>('open'),
    newNote: signal(''),
    importToken: signal(''),
    importFileName: signal(''),
    importNotice: signal<InvoiceImportNotice>(null),
    importDuplicate: signal<string | null>(null),
    canSubmitCreate: computed(() => invoiceFieldsValid(newNumber(), newSupplier(), newGross())),
    create: jest.fn(),
    clearAttachment: jest.fn(),
    onCreateFilePicked: jest.fn(),
    editing: signal<Invoice | null>(null),
    editNumber,
    editSupplier,
    editIssueDate: signal(''),
    editDueDate: signal(''),
    editNet: signal(''),
    editTax: signal(''),
    editGross,
    editStatus: signal<InvoiceStatus>('open'),
    editNote: signal(''),
    canSubmitEdit: computed(() => invoiceFieldsValid(editNumber(), editSupplier(), editGross())),
    saveEdit: jest.fn(),
  };
}

async function setup(mode: 'create' | 'edit') {
  localStorage.setItem('ap.locale', 'de');
  const host = fakeHost();
  const view = await render(InvoiceImportDialogComponent, { inputs: { host, mode } });
  return { ...view, host };
}

describe('InvoiceImportDialogComponent', () => {
  it('reviews an import: file, "read" note, duplicate warning and every field', async () => {
    const { host, fixture } = await setup('create');
    host.importToken.set('tok');
    host.importFileName.set('2026-0931.pdf');
    host.importNotice.set('parsed');
    host.importDuplicate.set('2026-0931');
    host.newNumber.set('2026-0931');
    host.newSupplier.set('Getränke Kraus GmbH');
    host.newGross.set('380.00');
    host.createOpen.set(true);
    fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Importierte Rechnung prüfen' })).toBeInTheDocument();
    expect(screen.getByText('2026-0931.pdf')).toBeInTheDocument();
    expect(screen.getByText('Rechnung gelesen — bitte prüfen.')).toBeInTheDocument();
    expect(screen.getByText('Mögliche Dublette: Rechnung „2026-0931" existiert bereits.')).toBeInTheDocument();
    for (const label of [
      /^Rechnungsnummer/,
      /^Lieferant/,
      'Rechnungsdatum',
      'Fälligkeitsdatum',
      'Netto',
      'USt.',
      /^Brutto/,
      'Status',
      'Notiz',
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    screen.getByRole('button', { name: 'Beleg entfernen' }).click();
    expect(host.clearAttachment).toHaveBeenCalled();
    screen.getByRole('button', { name: 'Rechnung hinzufügen' }).click();
    expect(host.create).toHaveBeenCalled();
  });

  it('asks for the receipt on a manual add and names a PDF without ZUGFeRD', async () => {
    const { host, fixture, container } = await setup('create');
    host.importNotice.set('manual');
    host.createOpen.set(true);
    fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Rechnung hinzufügen' })).toBeInTheDocument();
    expect(screen.getByText('Kein ZUGFeRD erkannt — bitte manuell erfassen.')).toBeInTheDocument();
    expect(screen.queryByText(/Dublette/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Beleg hinzufügen' })).toBeInTheDocument();
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    input.dispatchEvent(new Event('change'));
    expect(host.onCreateFilePicked).toHaveBeenCalled();
    // Number, supplier and gross are required: with any one blank, the add button is off.
    const add = (): HTMLElement | undefined =>
      screen.getAllByRole('button', { name: 'Rechnung hinzufügen' }).at(-1);
    const disabled = (): boolean => {
      const b = add();
      return !!b && (b.hasAttribute('disabled') || b.closest('[disabled]') !== null);
    };
    expect(disabled()).toBe(true);
    for (const label of [/^Rechnungsnummer/, /^Lieferant/]) {
      expect(screen.getByLabelText(label)).toBeRequired();
    }
    host.newGross.set('12.00');
    host.newSupplier.set('Druckerei');
    fixture.detectChanges();
    expect(disabled()).toBe(true);
    host.newNumber.set('R-7');
    fixture.detectChanges();
    expect(disabled()).toBe(false);
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(host.createOpen()).toBe(false);
  });

  it('edits an invoice and closes on cancel', async () => {
    const { host, fixture } = await setup('edit');
    host.editing.set(INVOICE);
    host.editNumber.set('R-1');
    host.editSupplier.set('ACME GmbH');
    host.editGross.set('119.00');
    fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Rechnung bearbeiten' })).toBeInTheDocument();
    expect(screen.queryByText('Rechnung gelesen — bitte prüfen.')).toBeNull();
    screen.getByRole('button', { name: 'Speichern' }).click();
    expect(host.saveEdit).toHaveBeenCalled();
    screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)?.click();
    expect(host.editing()).toBeNull();
  });
});
