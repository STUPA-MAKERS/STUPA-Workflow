import { render, screen } from '@testing-library/angular';
import { type Column, TableComponent } from './table.component';

interface Row extends Record<string, unknown> {
  title: string;
  state: string;
}

const columns: Column<Row>[] = [
  { key: 'title', label: 'Titel' },
  { key: 'state', label: 'Status' },
];

describe('TableComponent', () => {
  it('renders headers and a row per item', async () => {
    const rows: Row[] = [
      { title: 'Antrag A', state: 'Entwurf' },
      { title: 'Antrag B', state: 'Eingereicht' },
    ];
    await render(TableComponent, { inputs: { columns, rows } });
    expect(screen.getByRole('columnheader', { name: 'Titel' })).toBeInTheDocument();
    expect(screen.getByText('Antrag A')).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(3); // header + 2
  });

  it('shows the empty placeholder when there are no rows', async () => {
    await render(TableComponent, {
      inputs: { columns, rows: [], emptyText: 'Nichts da' },
    });
    expect(screen.getByText('Nichts da')).toBeInTheDocument();
  });
});
