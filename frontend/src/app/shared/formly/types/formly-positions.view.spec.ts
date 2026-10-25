import { FormControl } from '@angular/forms';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { FormlyPositionsType } from './formly-positions.type';

/** The look and the open state of the positions editor (board Anträge-Bearbeiten). */

const COMPLETE = {
  label: 'Raummiete',
  offers: [
    { label: 'Studierendenwerk', value: 450, preferred: true },
    { label: 'Stadthalle', value: 520, preferred: false },
    { label: 'Gemeindezentrum', value: 610, preferred: false },
  ],
};
const NO_OFFERS = {
  label: 'Technik',
  noOffers: true,
  noOffersReason: 'Rahmenvertrag',
  offers: [{ label: 'Technik-Team', value: 420, preferred: true }],
};
const INCOMPLETE = { label: '', offers: [{ label: '', value: null, preferred: true }] };

async function setup(value: unknown, props: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const control = new FormControl(value);
  const fieldProps: Record<string, unknown> = { label: 'Kostenaufstellung', ...props };
  const field = { formControl: control, props: fieldProps, options: {} };
  const view = await render(FormlyPositionsType, { componentInputs: { field: field as never } });
  await new Promise((r) => queueMicrotask(() => r(null)));
  view.detectChanges();
  return { ...view, control, field, cmp: view.fixture.componentInstance };
}

const cards = (container: Element) => [...container.querySelectorAll('.pos__card')] as HTMLElement[];

describe('FormlyPositionsType — view', () => {
  /**
   * The body of a collapsed position is not there, so the row controls nothing. Name and supplier
   * wrap; they are never cut. The sum of the field sits beside its legend.
   */
  it('starts a complete position collapsed and an incomplete one open', async () => {
    const { container } = await setup([COMPLETE, INCOMPLETE]);
    const [first, second] = cards(container);
    expect(first).not.toHaveClass('pos__card--open');
    const summary = within(first).getByRole('button', { expanded: false });
    expect(summary).not.toHaveAttribute('aria-controls');
    expect(summary.querySelector('.ell')).toBeNull();

    expect(summary.querySelector('.pos__sumSub')?.textContent).toBe('3 Angebote · bevorzugt: Studierendenwerk');
    expect(summary.querySelector('.pos__sumValue')?.textContent?.replace(/\s/g, ' ')).toBe('450,00 €');
    expect(second).toHaveClass('pos__card--open');
    expect(within(second).getByLabelText('Position')).toHaveValue('');
    expect(container.querySelector('.pos__sum')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('Gesamt 450,00 €');
  });

  /**
   * Each radio names its offer. The chevron points to the body that is there; the collapsed row
   * points nowhere.
   */
  it('opens a position on a click on its row and closes it with the chevron', async () => {
    const { container, detectChanges } = await setup([COMPLETE]);
    await userEvent.click(within(cards(container)[0]).getByRole('button', { expanded: false }));
    detectChanges();
    const card = cards(container)[0];
    expect(card).toHaveClass('pos__card--open');
    expect(within(card).getAllByLabelText('Anbieter').map((i) => (i as HTMLInputElement).value)).toEqual([
      'Studierendenwerk',
      'Stadthalle',
      'Gemeindezentrum',
    ]);
    const radios = within(card).getAllByRole('radio') as HTMLInputElement[];
    expect(radios.map((r) => r.getAttribute('aria-label'))).toEqual([
      'Bevorzugt: Studierendenwerk',
      'Bevorzugt: Stadthalle',
      'Bevorzugt: Gemeindezentrum',
    ]);
    expect(radios[0].checked).toBe(true);
    const chevron = within(card).getByRole('button', { name: 'Position zuklappen' });
    expect(document.getElementById(chevron.getAttribute('aria-controls') ?? '')).not.toBeNull();
    await userEvent.click(within(card).getByRole('button', { name: 'Position zuklappen' }));
    detectChanges();
    expect(cards(container)[0]).not.toHaveClass('pos__card--open');
  });

  it('shows one offer without a radio and the reason for a position without comparison offers', async () => {
    const { container, detectChanges } = await setup([NO_OFFERS]);
    const summary = within(cards(container)[0]).getByRole('button', { expanded: false });
    expect(summary.querySelector('.pos__sumSub')?.textContent).toBe('1 Angebot · ohne Vergleichsangebote');
    await userEvent.click(summary);
    detectChanges();
    const card = cards(container)[0];
    expect(within(card).getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    expect(within(card).queryByRole('radio')).toBeNull();
    expect(within(card).queryByRole('button', { name: 'Angebot entfernen' })).toBeNull();
    expect(within(card).queryByText('Angebot hinzufügen')).toBeNull();
    expect(within(card).getByLabelText('Begründung, warum keine Vergleichsangebote möglich sind')).toHaveValue(
      'Rahmenvertrag',
    );
  });

  it('turns the switch on and keeps one offer', async () => {
    const { container, control, detectChanges } = await setup([COMPLETE]);
    await userEvent.click(within(cards(container)[0]).getByRole('button', { expanded: false }));
    detectChanges();
    await userEvent.click(within(cards(container)[0]).getByRole('switch'));
    detectChanges();
    const v = control.value as { noOffers: boolean; offers: unknown[] }[];
    expect(v[0].noOffers).toBe(true);
    expect(v[0].offers.length).toBeGreaterThanOrEqual(1);
  });

  it('hides the switch when the form does not allow the opt-out', async () => {
    const { container } = await setup([INCOMPLETE], { allowNoOffers: false });
    expect(within(cards(container)[0]).queryByRole('switch')).toBeNull();
  });

  /** When the first position goes, the open ones move up with their positions. */
  it('opens a new position and keeps the open state in place when one goes away', async () => {
    const { container, cmp, detectChanges } = await setup([COMPLETE, INCOMPLETE, COMPLETE]);
    expect(cards(container).map((c) => c.classList.contains('pos__card--open'))).toEqual([false, true, false]);
    await userEvent.click(screen.getByRole('button', { name: 'Position hinzufügen' }));
    detectChanges();
    expect(cards(container).map((c) => c.classList.contains('pos__card--open'))).toEqual([false, true, false, true]);
    cmp.removePosition(0);
    detectChanges();
    expect(cards(container).map((c) => c.classList.contains('pos__card--open'))).toEqual([true, false, true]);
    await userEvent.click(within(cards(container)[1]).getAllByRole('button', { name: 'Position entfernen' })[0]);
    detectChanges();
    expect(cards(container)).toHaveLength(2);
  });

  /**
   * The chevron of a position with a server error clears its error first; the message for the field
   * as a whole stays. A change of the value clears what is left.
   */
  it('shows a 422 of the server on its position, opens it, and drops it on the next change', async () => {
    const { container, field, cmp, detectChanges } = await setup([COMPLETE, NO_OFFERS], {
      serverErrors: { 1: 'Mehr Angebote nötig.', [-1]: 'Feld abgelehnt.' },
    });
    const card = cards(container)[1];
    expect(card).toHaveClass('pos__card--open');
    expect(within(card).getByRole('alert')).toHaveTextContent('Mehr Angebote nötig.');
    expect(screen.getByText('Feld abgelehnt.')).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Position zuklappen' }));
    detectChanges();
    expect(field.props['serverErrors']).toEqual({ [-1]: 'Feld abgelehnt.' });
    expect(cards(container)[1]).not.toHaveClass('pos__card--open');
    expect(screen.getByText('Feld abgelehnt.')).toBeInTheDocument();
    field.props['serverErrors'] = { 0: 'x' };
    cmp.setPositionLabel(0, 'Neu');
    expect(field.props['serverErrors']).toBeUndefined();
  });

  it('names the radio of an offer without a supplier by its place', async () => {
    const { container } = await setup([INCOMPLETE]);
    expect(within(cards(container)[0]).getByRole('radio', { name: 'Bevorzugt: Angebot 1' })).toBeChecked();
  });

  /** When the last message goes, the control is valid by its own checks again. */
  it('keeps the errors of the other positions when one closes', async () => {
    const { container, control, field, detectChanges } = await setup([COMPLETE, NO_OFFERS, COMPLETE], {
      serverErrors: { 0: 'Fehler A', 2: 'Fehler C' },
    });
    control.setErrors({ server: true });
    expect(cards(container).map((c) => c.classList.contains('pos__card--open'))).toEqual([true, false, true]);
    await userEvent.click(within(cards(container)[0]).getByRole('button', { name: 'Position zuklappen' }));
    detectChanges();
    expect(field.props['serverErrors']).toEqual({ 2: 'Fehler C' });
    expect(cards(container).map((c) => c.classList.contains('pos__card--open'))).toEqual([false, false, true]);
    expect(within(cards(container)[2]).getByRole('alert')).toHaveTextContent('Fehler C');
    expect(control.hasError('server')).toBe(true);
    await userEvent.click(within(cards(container)[2]).getByRole('button', { name: 'Position zuklappen' }));
    detectChanges();
    expect(field.props['serverErrors']).toBeUndefined();
    expect(control.valid).toBe(true);
  });

  /** The position is incomplete, so it starts open; the test shows the errors and closes it. */
  it('shows the collapsed error of an invalid position under its row', async () => {
    const bad = { label: 'Ohne Bevorzugung', offers: [{ label: 'A', value: 1, preferred: false }, { label: 'B', value: 2, preferred: false }, { label: 'C', value: 3, preferred: false }] };
    const { container, cmp, detectChanges } = await setup([bad]);
    cmp.formControl.markAsTouched();
    await userEvent.click(within(cards(container)[0]).getByRole('button', { name: 'Position zuklappen' }));
    detectChanges();
    const card = cards(container)[0];
    expect(card).not.toHaveClass('pos__card--open');
    expect(within(card).getByRole('alert')).toHaveTextContent('Genau ein Angebot muss als bevorzugt markiert sein.');
    expect(card.querySelector('.pos__sumSub')?.textContent).toBe('3 Angebote');
  });

  it('gives each position its own radio group, also with two editors on a page', async () => {
    const { container } = await setup([INCOMPLETE, INCOMPLETE]);
    const names = [...container.querySelectorAll('input[type=radio]')].map((r) => r.getAttribute('name'));
    expect(new Set(names).size).toBe(2);
    expect(names[0]).toMatch(/^pos-\d+-pref-0$/);
  });

  it('has no a11y violations, open and collapsed', async () => {
    const { container } = await setup([COMPLETE, INCOMPLETE], { required: true, description: 'Hinweis' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
