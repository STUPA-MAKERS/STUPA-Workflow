import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { BookingRowComponent } from './booking-row.component';
import { SumRowComponent } from './sum-row.component';

describe('BookingRowComponent', () => {
  it('is a list item with the title, the meta line, the amount and the end slot', async () => {
    const { container } = await render(
      `<div class="rowgroup" role="list">
         <app-booking-row mark title="Druck" amount="−20,00 €"><span meta>12.10.2026</span><button type="button">Menü</button></app-booking-row>
       </div>`,
      { imports: [BookingRowComponent] },
    );
    expect(screen.getByRole('listitem')).toHaveTextContent('Druck');
    expect(screen.getByText('Druck')).toHaveAttribute('title', 'Druck');
    expect(screen.getByText('12.10.2026').closest('.bkr__meta')).toBeTruthy();
    expect(container.querySelector('.bkr__amount')).toHaveTextContent('−20,00 €');
    expect(container.querySelector('.bkr__mark')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByRole('button', { name: 'Menü' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('puts the mark into the title of a form row', async () => {
    const { container } = await render(`<app-booking-row mark plain title="Druck" amount="1" />`, {
      imports: [BookingRowComponent],
    });
    expect(container.querySelector('.bkr__mark')).toBeNull();
    expect(container.querySelector('.bkr__title')).toHaveTextContent('↳ Druck');
    expect(container.querySelector('app-booking-row')).toHaveClass('bkr--plain');
  });

  it('has no mark without mark', async () => {
    const { container } = await render(`<app-booking-row title="Druck" amount="1" />`, {
      imports: [BookingRowComponent],
    });
    expect(container.querySelector('.bkr__mark')).toBeNull();
    expect(container.querySelector('.bkr__title')).toHaveTextContent(/^Druck$/);
  });
});

describe('SumRowComponent', () => {
  it('shows the label and the amount, with the strong and quiet looks', async () => {
    const { container } = await render(
      `<app-sum-row label="Summe" amount="10,00 €" /><app-sum-row strong quiet label="S" amount="1" />`,
      { imports: [SumRowComponent] },
    );
    const [plain, other] = Array.from(container.querySelectorAll('app-sum-row'));
    expect(plain).toHaveTextContent('Summe');
    expect(plain.querySelector('.sum__amount')).toHaveTextContent('10,00 €');
    expect(plain).not.toHaveClass('sum--strong');
    expect(other).toHaveClass('sum--strong');
    expect(other).toHaveClass('sum--quiet');
  });
});
