import { provideRouter } from '@angular/router';
import { render } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { BudgetItemListComponent } from './budget-item-list.component';
import type { BudgetItem } from './budget-items';
import { itemApp, itemBooking } from './budget-items.fixtures';

async function setup(items: BudgetItem[], names = new Map([['b-800', { name: 'Werkstatt' }]])) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(BudgetItemListComponent, {
    inputs: { items, names },
    providers: [provideRouter([])],
  });
  const rows = Array.from(view.container.querySelectorAll('app-list-item')) as HTMLElement[];
  return { ...view, rows };
}

const appItem = (a: ReturnType<typeof itemApp>): BudgetItem => ({ type: 'application', at: a.createdAt, app: a });
const bookingItem = (b: ReturnType<typeof itemBooking>): BudgetItem => ({ type: 'booking', at: b.createdAt, booking: b });

describe('BudgetItemListComponent', () => {
  it('shows an application with its status, path, cost centre and amount, and links to it', async () => {
    const { rows, container } = await setup([
      appItem(
        itemApp({
          applicationId: 'a-1',
          title: 'Neu',
          amount: '2890.00',
          stateLabel: { de: 'Bewilligt', en: 'Approved' },
          stateColor: '#3f9a5c',
        }),
      ),
    ]);
    const row = rows[0];
    expect(row.querySelector('app-status-text')?.textContent).toContain('Bewilligt');
    expect(row.querySelector('app-status-text')?.classList).toContain('st--accent');
    expect(row.textContent).toContain('VS-800');
    expect(row.textContent).toContain('Werkstatt');
    expect(row.textContent).toContain('Antrag:');
    expect(row.textContent).toMatch(/2\.890,00\s€/);
    expect(row.querySelector('a.li__title')?.getAttribute('href')).toBe('/applications/a-1');
    expect(row.querySelector('app-icon[lead]')).toBeTruthy();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('falls back to "Ohne Titel" and shows an application without state, cost centre or amount', async () => {
    const { rows } = await setup([
      appItem(itemApp({ applicationId: 'a-1', title: '  ', stateLabel: null, budgetId: null, pathKey: null, amount: null })),
      appItem(itemApp({ applicationId: 'a-2', stateLabel: {}, budgetId: 'b-unknown', currency: null })),
      appItem(itemApp({ applicationId: 'a-3', stateLabel: { it: 'Stato' } })),
    ]);
    expect(rows[0].querySelector('.li__title')?.textContent?.trim()).toBe('Ohne Titel');
    expect(rows[0].querySelector('app-status-text')).toBeNull();
    expect(rows[0].querySelector('.bil__dot')).toBeNull();
    expect(rows[0].textContent).toContain('—');
    expect(rows[1].querySelector('app-status-text')).toBeNull();
    expect(rows[1].textContent).not.toContain('Werkstatt');
    expect(rows[1].textContent).toMatch(/120,00\s€/);
    expect(rows[2].querySelector('app-status-text')?.textContent).toContain('Stato');
  });

  it('shows a booking with its kind, cost centre, date and signed amount, and links to it', async () => {
    const { rows } = await setup([
      bookingItem(itemBooking({ id: 'e-1', description: 'Druck', paymentDate: '2026-05-04', amount: '20.00' })),
      bookingItem(itemBooking({ id: 'e-2', kind: 'income', budgetId: 'b-x', createdAt: '2025-03-02T10:00:00Z' })),
    ]);
    const [out, inc] = rows;
    expect(out.querySelector('app-status-text')?.textContent).toContain('Ausgabe');
    expect(out.textContent).toContain('Buchung:');
    expect(out.textContent).toContain('Werkstatt');
    expect(out.textContent).toMatch(/04\.05\./);
    expect(out.querySelector('.bil__amount')?.textContent).toMatch(/−20,00\s€/);
    expect(out.querySelector('.bil__amount--in')).toBeNull();
    expect(out.querySelector('a.li__title')?.getAttribute('href')).toBe('/expenses?id=e-1');
    expect(inc.querySelector('app-status-text')?.textContent).toContain('Einnahme');
    expect(inc.querySelector('.bil__amount--in')).toBeTruthy();
    expect(inc.textContent).toContain('02.03.2025');
    expect(inc.textContent).not.toContain('Werkstatt');
  });
});
