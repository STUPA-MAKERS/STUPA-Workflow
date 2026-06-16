import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import {
  ApplicationsTableComponent,
  type ApplicationRow,
  type SortState,
} from './applications-table.component';

const ROW: ApplicationRow = {
  id: 'app-1',
  title: 'Mein Antrag',
  typeLabel: 'Finanzantrag',
  stateLabel: 'Eingereicht',
  stateColor: '#4a90d9',
  amount: '250.00',
  currency: 'EUR',
  createdAt: '2026-05-30T09:00:00Z',
};

async function setup(
  inputs: Partial<{ rows: ApplicationRow[]; emptyText: string; sort: SortState | null }> = {},
) {
  return render(ApplicationsTableComponent, {
    providers: [provideRouter([])],
    inputs: {
      rows: inputs.rows ?? [ROW],
      emptyText: inputs.emptyText ?? 'Keine Anträge',
      sort: inputs.sort ?? null,
    },
  });
}

describe('ApplicationsTableComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders a row per application with title, type, state badge and a detail link', async () => {
    await setup();
    const link = screen.getByRole('link', { name: /Mein Antrag/ });
    expect(link).toHaveAttribute('href', '/applications/app-1');
    expect(screen.getByText('Finanzantrag')).toBeInTheDocument();
    expect(screen.getByText('Eingereicht')).toBeInTheDocument();
    // German currency formatting of the amount
    expect(screen.getByText(/250/)).toBeInTheDocument();
    // the created-at cell renders a <time> with the raw ISO datetime attribute
    const time = document.querySelector('time');
    expect(time).toHaveAttribute('datetime', '2026-05-30T09:00:00Z');
  });

  it('shows the empty state (and no table) when there are no rows', async () => {
    await setup({ rows: [], emptyText: 'Nix da' });
    expect(screen.getByText('Nix da')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('falls back to a dash for missing type, state and created date', async () => {
    await setup({
      rows: [
        {
          id: 'a',
          title: 'Ohne Felder',
          typeLabel: null,
          stateLabel: null,
          stateColor: null,
          amount: null,
          createdAt: null,
        },
      ],
    });
    // type, state, amount and created all collapse to the em-dash
    expect(screen.getAllByText('—').length).toBe(4);
    // no badge is rendered when stateLabel is null
    expect(screen.queryByText('Eingereicht')).not.toBeInTheDocument();
    // no <time> element without a createdAt
    expect(document.querySelector('time')).toBeNull();
  });

  describe('money formatting', () => {
    const cases: { label: string; row: Partial<ApplicationRow>; expect: RegExp | string }[] = [
      { label: 'null amount → dash', row: { amount: null }, expect: '—' },
      { label: 'undefined amount → dash', row: { amount: undefined }, expect: '—' },
      { label: 'empty-string amount → dash', row: { amount: '' }, expect: '—' },
      { label: 'non-numeric string → printed verbatim', row: { amount: 'n/a' }, expect: 'n/a' },
      { label: 'numeric amount → currency', row: { amount: 99.5, currency: 'EUR' }, expect: /99[,.]5/ },
    ];
    for (const c of cases) {
      it(c.label, async () => {
        await setup({ rows: [{ ...ROW, ...c.row }] });
        if (typeof c.expect === 'string') {
          expect(screen.getByText(c.expect)).toBeInTheDocument();
        } else {
          expect(screen.getByText(c.expect)).toBeInTheDocument();
        }
      });
    }

    it('defaults the currency to EUR when none is given', async () => {
      await setup({ rows: [{ ...ROW, amount: 10, currency: null }] });
      // EUR symbol/format present even though currency was null
      expect(screen.getByText(/10[,.]00/)).toBeInTheDocument();
    });
  });

  describe('sorting', () => {
    it('renders plain header text (no buttons) when sort is null', async () => {
      await setup({ sort: null });
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      // headers carry aria-sort="none" when unsorted
      const amountHeader = screen.getByRole('columnheader', { name: /Betrag/ });
      expect(amountHeader).toHaveAttribute('aria-sort', 'none');
    });

    it('renders clickable headers with indicators when sort is set (descending)', async () => {
      await setup({ sort: { field: 'amount', order: 'desc' } });
      const amountBtn = screen.getByRole('button', { name: /Betrag/ });
      // descending indicator arrow on the active column
      expect(amountBtn.textContent).toContain('↓');
      const amountHeader = screen.getByRole('columnheader', { name: /Betrag/ });
      expect(amountHeader).toHaveAttribute('aria-sort', 'descending');
      // the inactive (createdAt) header stays neutral
      const createdHeader = screen.getByRole('columnheader', { name: /Eingegangen/ });
      expect(createdHeader).toHaveAttribute('aria-sort', 'none');
    });

    it('shows the ascending indicator and aria-sort for an ascending column', async () => {
      await setup({ sort: { field: 'createdAt', order: 'asc' } });
      const createdBtn = screen.getByRole('button', { name: /Eingegangen/ });
      expect(createdBtn.textContent).toContain('↑');
      const createdHeader = screen.getByRole('columnheader', { name: /Eingegangen/ });
      expect(createdHeader).toHaveAttribute('aria-sort', 'ascending');
    });

    it('toggles a desc column to asc when its header is clicked again', async () => {
      const emitted: SortState[] = [];
      const { fixture } = await setup({ sort: { field: 'amount', order: 'desc' } });
      fixture.componentInstance.sortChange.subscribe((s) => emitted.push(s));
      await userEvent.click(screen.getByRole('button', { name: /Betrag/ }));
      // same field that is currently desc → flips to asc
      expect(emitted).toEqual([{ field: 'amount', order: 'asc' }]);
    });

    it('starts a different column at desc (default order)', async () => {
      const emitted: SortState[] = [];
      const { fixture } = await setup({ sort: { field: 'amount', order: 'desc' } });
      fixture.componentInstance.sortChange.subscribe((s) => emitted.push(s));
      // clicking the OTHER column → defaults to desc
      await userEvent.click(screen.getByRole('button', { name: /Eingegangen/ }));
      expect(emitted).toEqual([{ field: 'createdAt', order: 'desc' }]);
    });

    it('flips an asc column back to desc when clicked', async () => {
      const emitted: SortState[] = [];
      const { fixture } = await setup({ sort: { field: 'amount', order: 'asc' } });
      fixture.componentInstance.sortChange.subscribe((s) => emitted.push(s));
      // same field but currently asc → cur.order !== 'desc' branch → desc
      await userEvent.click(screen.getByRole('button', { name: /Betrag/ }));
      expect(emitted).toEqual([{ field: 'amount', order: 'desc' }]);
    });
  });
});
