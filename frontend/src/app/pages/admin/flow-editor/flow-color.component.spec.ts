import { fireEvent, render, screen } from '@testing-library/angular';
import { FLOW_COLOR_PRESETS, FlowColorComponent } from './flow-color.component';

async function setup(value: string | null) {
  const emitted: string[] = [];
  const view = await render(FlowColorComponent, { inputs: { value } });
  view.fixture.componentInstance.changed.subscribe((c) => emitted.push(c));
  return { ...view, emitted };
}

describe('FlowColorComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('offers "no colour", every preset and a custom colour as one radio group', async () => {
    await setup(null);
    expect(screen.getByRole('radiogroup', { name: 'Farbe' })).toBeInTheDocument();
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(FLOW_COLOR_PRESETS.length + 1);
    // Without a colour, "Keine Farbe" is the chosen one.
    expect(screen.getByRole('radio', { name: 'Keine Farbe' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByLabelText('Eigene Farbe')).toBeInTheDocument();
  });

  it('marks a preset in any letter case and emits a click', async () => {
    const { emitted } = await setup('#CE1625');
    expect(screen.getByRole('radio', { name: 'Farbe #ce1625' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Keine Farbe' })).toHaveAttribute('aria-checked', 'false');
    screen.getByRole('radio', { name: 'Farbe #0075bf' }).click();
    screen.getByRole('radio', { name: 'Keine Farbe' }).click();
    expect(emitted).toEqual(['#0075bf', '']);
  });

  it('shows a custom colour on the picker swatch and emits a picked colour', async () => {
    const { emitted, container } = await setup('#123456');
    expect(screen.getAllByRole('radio').every((r) => r.getAttribute('aria-checked') === 'false')).toBe(true);
    const swatch = container.querySelector('.fc__dot--custom') as HTMLElement;
    expect(swatch.classList).toContain('fc__dot--on');
    const picker = screen.getByLabelText('Eigene Farbe') as HTMLInputElement;
    expect(picker.value).toBe('#123456');
    fireEvent.input(picker, { target: { value: '#abcdef' } });
    expect(emitted).toEqual(['#abcdef']);
  });
});
