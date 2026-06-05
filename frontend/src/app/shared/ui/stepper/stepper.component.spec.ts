import { render, screen } from '@testing-library/angular';
import { StepperComponent } from './stepper.component';

const STEPS = [{ label: 'Antragsteller' }, { label: 'Angaben' }, { label: 'Prüfen' }];

describe('StepperComponent', () => {
  it('renders all steps within a labelled list', async () => {
    await render(StepperComponent, { inputs: { steps: STEPS, activeIndex: 1 } });
    expect(screen.getByRole('list', { name: 'Fortschritt' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('marks the active step with aria-current', async () => {
    await render(StepperComponent, { inputs: { steps: STEPS, activeIndex: 1 } });
    const current = screen.getByText('Angaben').closest('li');
    expect(current).toHaveAttribute('aria-current', 'step');
  });
});
