import { computed, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Invoice, InvoiceStatus } from '../../budget/budget-tree.api';
import {
  type InvoiceFormHost,
  type InvoiceImportNotice,
  InvoiceFormComponent,
  invoiceFieldsValid,
} from './invoice-form.component';

const INVOICE: Invoice = {
  id: 'inv',
  number: 'RE-2026-118',
  issueDate: '2026-09-24',
  dueDate: '2026-10-08',
  supplier: 'Radhaus',
  netAmount: '1',
  taxAmount: '0',
  grossAmount: '1',
  currency: 'EUR',
  note: null,
  status: 'open',
  fileName: 'RE.pdf',
  hasFile: true,
  actor: null,
  createdAt: '2026-09-24T00:00:00Z',
};

/** A host with plain signals, as the invoices page has them. */
function host(): InvoiceFormHost & { calls: string[] } {
  const calls: string[] = [];
  const h = {
    calls,
    saving: signal(false),
    attaching: signal(false),
    statusOptions: signal([
      { value: 'open', label: 'Offen' },
      { value: 'paid', label: 'Bezahlt' },
    ]),
    createOpen: signal(true),
    newNumber: signal(''),
    newSupplier: signal(''),
    newIssueDate: signal(''),
    newDueDate: signal(''),
    newNet: signal(''),
    newTax: signal(''),
    newGross: signal(''),
    newStatus: signal<InvoiceStatus>('open'),
    newNote: signal(''),
    importToken: signal(''),
    importFileName: signal(''),
    importFileSize: signal(0),
    importNotice: signal<InvoiceImportNotice>(null),
    importDuplicate: signal<string | null>(null),
    canSubmitCreate: signal(false),
    create: () => calls.push('create'),
    clearAttachment: () => calls.push('clear'),
    onCreateFilePicked: () => calls.push('picked'),
    editing: signal<Invoice | null>(null),
    editNumber: signal(''),
    editSupplier: signal(''),
    editIssueDate: signal(''),
    editDueDate: signal(''),
    editNet: signal(''),
    editTax: signal(''),
    editGross: signal(''),
    editStatus: signal<InvoiceStatus>('open'),
    editNote: signal(''),
    editNumberRequired: computed(() => true),
    editSupplierRequired: computed(() => true),
    canSubmitEdit: signal(true),
    saveEdit: () => calls.push('save'),
    openFile: () => calls.push('file'),
  };
  return h;
}

async function setup(mode: 'create' | 'edit', h = host(), layout: 'pane' | 'sheet' = 'pane') {
  localStorage.setItem('ap.locale', 'de');
  const remove = jest.fn();
  const openDuplicate = jest.fn();
  const view = await render(InvoiceFormComponent, {
    inputs: { host: h, mode, layout },
    on: { remove, openDuplicate },
  });
  return { view, h, remove, openDuplicate, user: userEvent.setup() };
}

describe('InvoiceFormComponent', () => {
  it('requires number, supplier and a positive gross amount for a new invoice', () => {
    expect(invoiceFieldsValid('R-1', 'X', '10')).toBe(true);
    expect(invoiceFieldsValid(' ', 'X', '10')).toBe(false);
    expect(invoiceFieldsValid('R-1', '', '10')).toBe(false);
    expect(invoiceFieldsValid('R-1', 'X', '0')).toBe(false);
  });

  it('shows the review of an import: the file, the note and the duplicate warning', async () => {
    const h = host();
    h.importNotice.set('parsed');
    h.importToken.set('tok');
    h.importFileName.set('2026-0931.pdf');
    h.importFileSize.set(217_000);
    h.importDuplicate.set('2026-0931');
    const { openDuplicate, user, view } = await setup('create', h);
    expect(screen.getByRole('heading', { name: 'Importierte Rechnung prüfen' })).toBeInTheDocument();
    expect(screen.getByText('Werte aus der ZUGFeRD-Datei')).toBeInTheDocument();
    expect(screen.getByText('212 KB')).toBeInTheDocument();
    expect(screen.getByText('Rechnung gelesen — bitte prüfen.')).toBeInTheDocument();
    expect(screen.getByRole('alert').textContent).toContain('„2026-0931“');
    await user.click(screen.getByRole('button', { name: 'Vorhandene öffnen' }));
    expect(openDuplicate).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Beleg entfernen' }));
    expect(h.calls).toContain('clear');
    h.importFileSize.set(3_000_000);
    view.fixture.detectChanges();
    expect(screen.getByText(/2,9 MB/)).toBeInTheDocument();
  });

  it('offers a receipt for a manual entry and says that no ZUGFeRD was found', async () => {
    const h = host();
    h.importNotice.set('manual');
    const { view, user } = await setup('create', h);
    expect(screen.getByRole('heading', { name: 'Rechnung hinzufügen' })).toBeInTheDocument();
    expect(screen.getByText('Pflichtfelder sind mit * markiert.')).toBeInTheDocument();
    expect(screen.getByText(/Kein ZUGFeRD erkannt/)).toBeInTheDocument();
    const input = view.container.querySelector('input[type=file]') as HTMLInputElement;
    const click = jest.spyOn(input, 'click').mockImplementation(() => undefined);
    await user.click(screen.getByRole('button', { name: 'Beleg hinzufügen' }));
    expect(click).toHaveBeenCalled();
    input.dispatchEvent(new Event('change'));
    expect(h.calls).toContain('picked');
  });

  it('sets the status with the segments and submits or cancels', async () => {
    const h = host();
    const { view, user } = await setup('create', h);
    await user.click(screen.getByRole('radio', { name: 'Bezahlt' }));
    expect(h.newStatus()).toBe('paid');
    await user.click(screen.getByRole('radio', { name: 'Offen' }));
    expect(h.newStatus()).toBe('open');
    view.fixture.componentInstance.submit(new Event('submit'));
    expect(h.calls).toContain('create');
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(h.createOpen()).toBe(false);
  });

  it('edits a stored invoice with its receipt, and deletes, saves or cancels', async () => {
    const h = host();
    h.editing.set(INVOICE);
    const { view, remove, user } = await setup('edit', h);
    expect(screen.getByRole('heading', { name: 'Rechnung bearbeiten' })).toBeInTheDocument();
    expect(screen.getByText('RE-2026-118')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /RE\.pdf/ }));
    expect(h.calls).toContain('file');
    await user.click(screen.getByRole('radio', { name: 'Bezahlt' }));
    expect(h.editStatus()).toBe('paid');
    await user.click(screen.getByRole('button', { name: 'Löschen' }));
    expect(remove).toHaveBeenCalled();
    view.fixture.componentInstance.submit(new Event('submit'));
    expect(h.calls).toContain('save');
    view.fixture.componentInstance.close();
    expect(h.editing()).toBeNull();
  });

  it('says that a stored invoice has no receipt', async () => {
    const h = host();
    h.editing.set({ ...INVOICE, hasFile: false, number: null });
    await setup('edit', h);
    expect(screen.getByText('Kein Beleg-PDF hinterlegt.')).toBeInTheDocument();
  });

  it('leaves out its head in the bottom sheet', async () => {
    await setup('create', host(), 'sheet');
    expect(screen.queryByRole('heading', { name: 'Rechnung hinzufügen' })).toBeNull();
    expect(screen.getByRole('button', { name: /Hinzufügen/ })).toBeInTheDocument();
  });
});
