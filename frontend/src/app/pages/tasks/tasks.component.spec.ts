import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationListItem } from '@core/api/models';
import { TasksComponent } from './tasks.component';

function task(id: string, kind: string, title = 'Mein Antrag'): ApplicationListItem {
  return {
    id,
    typeId: 't1',
    title,
    state: { id: 's1', key: 's', label: 'Abstimmung', color: '#9b59b6', editAllowed: false, kind },
    gremiumId: null,
    budgetPotId: null,
    amount: '120.00',
    currency: 'EUR',
    createdAt: '2026-06-01T10:00:00Z',
    updatedAt: '2026-06-01T10:00:00Z',
  };
}

async function setup(items: ApplicationListItem[]) {
  const listTasks = jest.fn(() => of(items));
  const applicationTypes = jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }]));
  const api = { listTasks, applicationTypes };
  const view = await render(TasksComponent, {
    providers: [provideRouter([]), { provide: ApiClient, useValue: api }],
  });
  return { ...view, listTasks };
}

describe('TasksComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists vote tasks awaiting the user with type and waiting age', async () => {
    await setup([task('v1', 'vote')]);
    expect(screen.getByText('Mein Antrag')).toBeInTheDocument();
    expect(screen.getByText('Abstimmung')).toBeInTheDocument();
    // Typ-Spalte (über die geladenen Typen aufgelöst).
    expect(await screen.findByText('Finanzantrag')).toBeInTheDocument();
    // „Wartet seit"-Spalte zeigt eine relative Angabe (vor … Tagen).
    expect(screen.getByText(/Tag(en)?/)).toBeInTheDocument();
  });

  it('shows no inline decision buttons (acting happens in the detail view)', async () => {
    await setup([task('v1', 'vote')]);
    expect(screen.queryByRole('button', { name: 'Annehmen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ablehnen' })).not.toBeInTheDocument();
  });
});
