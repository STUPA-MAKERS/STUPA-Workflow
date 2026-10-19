import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { AmountComponent } from './amount.component';

describe('AmountComponent', () => {
  it('stacks the approved amount over the struck requested one', async () => {
    const { container } = await render(`<app-amount amount="1.250,00 €" approved="900,00 €" layout="stack" />`, {
      imports: [AmountComponent],
    });
    const stack = container.querySelector('.amt__stack') as HTMLElement;
    expect(stack.children[0]).toHaveTextContent('900,00 €');
    expect(stack.children[1].tagName).toBe('S');
    expect(stack.children[1]).toHaveTextContent('1.250,00 €');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('marks the approved amount and puts the struck one after it in one line', async () => {
    const { container } = await render(`<app-amount amount="250,00 €" approved="200,00 €" />`, {
      imports: [AmountComponent],
    });
    expect(container.querySelector('.amt__stack')).toBeNull();
    expect(screen.getByText('200,00 €')).toHaveClass('amt__value--approved');
    expect(container.querySelector('s.amt__struck--inline')).toHaveTextContent('250,00 €');
  });

  it('shows the requested amount alone without an approved one', async () => {
    const { container } = await render(`<app-amount amount="480,00 €" [approved]="null" layout="stack" />`, {
      imports: [AmountComponent],
    });
    expect(screen.getByText('480,00 €')).toHaveClass('amt__value--stack');
    expect(container.querySelector('s')).toBeNull();
  });

  it('shows nothing without an amount', async () => {
    const { container } = await render(`<app-amount [amount]="null" />`, { imports: [AmountComponent] });
    expect(container.querySelector('app-amount')?.textContent?.trim()).toBe('');
  });
});
