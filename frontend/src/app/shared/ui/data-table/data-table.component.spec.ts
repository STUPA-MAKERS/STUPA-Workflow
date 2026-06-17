import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { CellDirective } from './cell.directive';
import { type ColumnDef, DataTableComponent } from './data-table.component';
import { RowDetailDirective } from './row-detail.directive';

interface Row {
  id: number;
  name: string;
  status: string;
}

const COLS: ColumnDef[] = [
  { key: 'name', label: 'Name' },
  { key: 'status', label: 'Status', align: 'end', width: '8rem' },
];

const ROWS: Row[] = [
  { id: 1, name: 'Alpha', status: 'open' },
  { id: 2, name: 'Beta', status: 'done' },
];

describe('DataTableComponent', () => {
  it('renders a header row from the column defs', async () => {
    await render(`<app-data-table [columns]="cols" [rows]="rows" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS },
    });
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    const statusHead = screen.getByRole('columnheader', { name: 'Status' });
    expect(statusHead).toHaveStyle({ textAlign: 'end' });
    expect(statusHead).toHaveStyle({ width: '8rem' });
  });

  it('defaults column alignment to start and omits width when unset', async () => {
    await render(`<app-data-table [columns]="cols" [rows]="rows" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS },
    });
    const nameHead = screen.getByRole('columnheader', { name: 'Name' });
    expect(nameHead).toHaveStyle({ textAlign: 'start' });
    expect(nameHead.style.width).toBe('');
  });

  it('renders the raw cell text when no cell template is given', async () => {
    await render(`<app-data-table [columns]="cols" [rows]="rows" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS },
    });
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('done')).toBeInTheDocument();
  });

  it('shows the empty state (no table, no box) when there are no rows', async () => {
    const { container } = await render(`<app-data-table [columns]="cols" [rows]="rows" emptyText="Nichts da" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: [] as Row[] },
    });
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText('Nichts da')).toBeInTheDocument();
    expect(container.querySelector('.dt--boxed')).toBeNull();
  });

  it('applies the boxed class only when boxed and rows present', async () => {
    const { container } = await render(`<app-data-table [columns]="cols" [rows]="rows" [boxed]="true" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS },
    });
    expect(container.querySelector('.dt--boxed')).not.toBeNull();
  });

  it('omits the boxed class when boxed is false', async () => {
    const { container } = await render(`<app-data-table [columns]="cols" [rows]="rows" [boxed]="false" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS },
    });
    expect(container.querySelector('.dt--boxed')).toBeNull();
  });

  it('renders a custom cell template via appCell with the row context', async () => {
    @Component({
      standalone: true,
      imports: [DataTableComponent, CellDirective],
      template: `<app-data-table [columns]="cols" [rows]="rows">
        <ng-template appCell="status" let-row let-i="index">
          <span class="chip">{{ row.status }}#{{ i }}</span>
        </ng-template>
      </app-data-table>`,
    })
    class Host {
      cols = COLS;
      rows = ROWS;
    }
    await render(Host);
    expect(screen.getByText('open#0')).toBeInTheDocument();
    expect(screen.getByText('done#1')).toBeInTheDocument();
  });

  it('is not clickable by default: no rowClick, no tabindex', async () => {
    const onRowClick = jest.fn();
    await render(`<app-data-table [columns]="cols" [rows]="rows" (rowClick)="onRowClick($event)" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS, onRowClick },
    });
    const firstRow = screen.getByText('Alpha').closest('tr') as HTMLElement;
    expect(firstRow.getAttribute('tabindex')).toBeNull();
    await userEvent.click(firstRow);
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it('emits rowClick on click and Enter when clickable', async () => {
    const onRowClick = jest.fn();
    await render(`<app-data-table [columns]="cols" [rows]="rows" [clickable]="true" (rowClick)="onRowClick($event)" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS, onRowClick },
    });
    const firstRow = screen.getByText('Alpha').closest('tr') as HTMLElement;
    expect(firstRow).toHaveClass('dt__row--clickable');
    expect(firstRow.getAttribute('tabindex')).toBe('0');
    await userEvent.click(firstRow);
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);

    firstRow.focus();
    await userEvent.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenCalledTimes(2);
  });

  it('uses a custom rowKey for tracking', async () => {
    const rowKey = jest.fn((row: unknown) => (row as Row).id);
    await render(`<app-data-table [columns]="cols" [rows]="rows" [rowKey]="rowKey" />`, {
      imports: [DataTableComponent],
      componentProperties: { cols: COLS, rows: ROWS, rowKey },
    });
    expect(rowKey).toHaveBeenCalled();
    expect(screen.getByText('Beta')).toBeInTheDocument();
  });

  it('renders an expandable detail row only for expanded rows', async () => {
    @Component({
      standalone: true,
      imports: [DataTableComponent, RowDetailDirective],
      template: `<app-data-table [columns]="cols" [rows]="rows" [isExpanded]="isExpanded">
        <ng-template appRowDetail let-row>
          <div class="detail">Details für {{ row.name }}</div>
        </ng-template>
      </app-data-table>`,
    })
    class Host {
      cols = COLS;
      rows = ROWS;
      isExpanded = (row: unknown): boolean => (row as Row).id === 1;
    }
    const { container } = await render(Host);
    expect(screen.getByText('Details für Alpha')).toBeInTheDocument();
    expect(screen.queryByText('Details für Beta')).toBeNull();
    const detailCell = container.querySelector('.dt__detail-row td') as HTMLElement;
    expect(detailCell.getAttribute('colspan')).toBe(String(COLS.length));
  });

  it('does not render detail rows when no isExpanded predicate is provided', async () => {
    @Component({
      standalone: true,
      imports: [DataTableComponent, RowDetailDirective],
      template: `<app-data-table [columns]="cols" [rows]="rows">
        <ng-template appRowDetail let-row>
          <div>Detail {{ row.name }}</div>
        </ng-template>
      </app-data-table>`,
    })
    class Host {
      cols = COLS;
      rows = ROWS;
    }
    const { container } = await render(Host);
    expect(container.querySelector('.dt__detail-row')).toBeNull();
  });

  it('rebuilds the cell map when projected cell templates change', async () => {
    @Component({
      standalone: true,
      imports: [DataTableComponent, CellDirective],
      template: `<app-data-table [columns]="cols" [rows]="rows">
        @if (showCell()) {
          <ng-template appCell="name" let-row>
            <b class="tpl">{{ row.name }}!</b>
          </ng-template>
        }
      </app-data-table>`,
    })
    class Host {
      cols = COLS;
      rows = ROWS;
      readonly showCell = signal(false);
    }
    const view = await render(Host);
    // Initially the raw text is shown (no template registered).
    expect(view.container.querySelector('.tpl')).toBeNull();
    // Add the projected template → ContentChildren.changes fires → cellMap rebuilds.
    view.fixture.componentInstance.showCell.set(true);
    view.fixture.detectChanges();
    expect(screen.getByText('Alpha!')).toBeInTheDocument();
  });
});
