import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError } from 'rxjs';
import { type InvoiceOrders, OrdersApiService } from '@core/api/orders.service';
import { InvoiceOrdersComponent } from './invoice-orders.component';

const LIST: InvoiceOrders = {
  items: [
    {
      accessible: true,
      id: 'o-1',
      number: 'B-7K3QX9MD',
      title: 'Beamer',
      applicationId: 'a-1',
      applicationTitle: 'Technik für den Sitzungssaal',
      actualAmount: '72.50',
    },
    {
      accessible: true,
      id: 'o-2',
      number: 'B-2M4N6P8Q',
      title: 'Kabel',
      applicationId: 'a-2',
      applicationTitle: null,
      actualAmount: null,
    },
    {
      accessible: false,
      id: null,
      number: null,
      title: null,
      applicationId: null,
      applicationTitle: null,
      actualAmount: null,
    },
  ],
  total: '72.50',
};

async function setup(answer: InvoiceOrders | null = LIST, gross: string | null = '150.00') {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    ofInvoice: jest.fn(() => (answer ? of(answer) : throwError(() => ({ status: 500 })))),
  };
  const view = await render(InvoiceOrdersComponent, {
    inputs: { invoiceId: 'i-1', gross },
    providers: [provideRouter([]), { provide: OrdersApiService, useValue: api }],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  return { ...view, cmp, api };
}

const rowTexts = () =>
  [...document.querySelectorAll('[data-testid="io-row"]')].map((row) =>
    (row.textContent ?? '').replace(/\s+/g, ' ').trim(),
  );

describe('InvoiceOrdersComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/finance/orders/002877 */
  it('lists the Bestellungen of the invoice with the sum beside the gross amount', async () => {
    const { api, cmp, fixture } = await setup();
    expect(api.ofInvoice).toHaveBeenCalledWith('i-1');
    expect(fixture.nativeElement).not.toHaveAttribute('hidden');
    expect(screen.getByRole('heading', { name: 'Bestellungen' })).toBeInTheDocument();
    const rows = rowTexts();
    expect(rows[0]).toContain('B-7K3QX9MD · Beamer');
    expect(rows[0]).toContain('Technik für den Sitzungssaal');
    expect(rows[0]).toMatch(/72,50\s€/);
    expect(rows[1]).toContain('Preis offen');
    expect(rows[2]).toBe('Bestellung (kein Zugriff)');
    expect(cmp.rows().map((row: { link: unknown }) => row.link)).toEqual([
      ['/orders', 'o-1'],
      ['/orders', 'o-2'],
      null,
    ]);
    expect(screen.getByTestId('io-sum')).toHaveTextContent(/Summe der Bestellungen\s*72,50\s€ von 150,00\s€/);
  });

  /** §F/finance/orders/003011: while `Bestellungen` is off the invoice asks for none. */
  it('reads nothing while the feature is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['orders']));
    const { api, fixture } = await setup();
    localStorage.removeItem('ap.features.off');
    expect(api.ofInvoice).not.toHaveBeenCalled();
    expect(fixture.nativeElement).toHaveAttribute('hidden');
  });

  it('gives the sum alone without a gross amount', async () => {
    await setup(LIST, null);
    expect(screen.getByTestId('io-sum')).toHaveTextContent(/Summe der Bestellungen\s*72,50\s€\s*$/);
  });

  it.each([[{ items: [], total: '0' }], [null]])(
    'takes no space without a Bestellung or without an answer (%j)',
    async (answer) => {
      const { fixture, cmp } = await setup(answer, null);
      expect(cmp.sumLine()).toBe(answer ? '0,00\u00a0€' : '');
      expect(fixture.nativeElement).toHaveAttribute('hidden');
      expect(screen.queryByRole('heading', { name: 'Bestellungen' })).not.toBeInTheDocument();
    },
  );

  it('drops the answer of an invoice that is no longer shown', async () => {
    const first = new Subject<InvoiceOrders>();
    const { cmp, api, fixture } = await setup({ items: [], total: '0' });
    api.ofInvoice.mockReturnValueOnce(first);
    fixture.componentRef.setInput('invoiceId', 'i-2');
    fixture.detectChanges();
    fixture.componentRef.setInput('invoiceId', 'i-3');
    fixture.detectChanges();
    first.next(LIST);
    expect(cmp.rows()).toHaveLength(0);
  });
});
