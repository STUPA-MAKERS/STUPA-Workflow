import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { PositionsViewComponent } from './positions-view.component';

const POSITIONS = [
  {
    label: 'Raummiete',
    offers: [
      { label: 'Studierendenwerk', value: 450, preferred: true },
      { label: 'Stadthalle', value: 520, preferred: false },
      { label: 'Gemeindezentrum', value: 610, preferred: false },
    ],
  },
  {
    label: 'Technik',
    noOffers: true,
    noOffersReason: 'Rahmenvertrag mit der Hochschule.',
    offers: [{ label: 'Technik-Team', value: 420, preferred: true }],
  },
];

async function view(value: unknown = POSITIONS, inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  return render(PositionsViewComponent, {
    componentInputs: { label: 'Kostenaufstellung', value, ...inputs },
  });
}

const norm = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();

/** The visible parts of an element, each part one element of text, joined by " | ". */
const parts = (el: Element, selector: string) =>
  [...el.querySelectorAll(selector)].map((p) => norm(p.textContent)).join(' | ');
const ROW = '.pv__name, .pv__sub > *, .pv__amount';

describe('PositionsViewComponent', () => {
  it('shows each position collapsed: name, offers, preferred supplier and amount', async () => {
    const { container } = await view();
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'false');
    expect(parts(buttons[0], ROW)).toBe('Raummiete | 3 Angebote | · | bevorzugt: Studierendenwerk | 450,00 €');
    // Without comparison offers: the count and the warning instead of the supplier.
    expect(parts(buttons[1], ROW)).toBe('Technik | 1 Angebot | · | ohne Vergleichsangebote | 420,00 €');
    expect(container.querySelector('.pv__offers')).toBeNull();
    expect(parts(container.querySelector('.pv__total')!, 'span')).toBe('Gesamtbetrag | 870,00 €');
  });

  it('opens a position on a click anywhere on its row and closes it again', async () => {
    await view();
    const row = screen.getAllByRole('button')[0];
    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'true');
    const list = screen.getByRole('list', { name: 'Angebote' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    // The preferred offer is marked and stands out; the others are muted.
    expect(items[0]).toHaveClass('pv__offer--pref');
    expect(within(items[0]).getByText('bevorzugt')).toBeInTheDocument();
    expect(items[1]).not.toHaveClass('pv__offer--pref');
    expect(parts(items[2], 'span')).toBe('Gemeindezentrum | 610,00 €');
    expect(document.getElementById(row.getAttribute('aria-controls') ?? '')).not.toBeNull();
    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('shows the reason of a position without comparison offers', async () => {
    await view();
    await userEvent.click(screen.getAllByRole('button')[1]);
    expect(screen.getByText('Ohne Vergleichsangebote')).toBeInTheDocument();
    expect(screen.getByText('Rahmenvertrag mit der Hochschule.')).toBeInTheDocument();
  });

  it('starts open for the review step', async () => {
    await view(POSITIONS, { expanded: true });
    const buttons = screen.getAllByRole('button');
    expect(buttons.every((b) => b.getAttribute('aria-expanded') === 'true')).toBe(true);
    await userEvent.click(buttons[0]);
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'false');
  });

  it('copes with broken data: no name, no preferred offer, no reason, no offers', async () => {
    const { container } = await view([
      { offers: [{ label: 'A', value: 'x' }, 'kaputt'] },
      { label: 'Leer', noOffers: true },
      'kaputt',
    ]);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(parts(buttons[0], ROW)).toBe('Position ohne Namen | 1 Angebot | 0,00 €');
    await userEvent.click(buttons[0]);
    expect(parts(screen.getByRole('listitem'), 'span')).toBe('A | 0,00 €');
    await userEvent.click(buttons[1]);
    expect(parts(container.querySelector('.pv__reason')!, ':scope > *')).toBe('Ohne Vergleichsangebote | —');
    expect(parts(container.querySelector('.pv__total')!, 'span')).toBe('Gesamtbetrag | 0,00 €');
  });

  it('shows only the total for an answer that is no list', async () => {
    const { container } = await view('kaputt', { surface: 1 });
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(container.querySelector('.pv')).toHaveClass('pv--bg1');
  });

  it('names the group by its label and has no a11y violations', async () => {
    const { container } = await view(POSITIONS, { surface: 3 });
    expect(screen.getByRole('group', { name: 'Kostenaufstellung' })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button')[0]);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
