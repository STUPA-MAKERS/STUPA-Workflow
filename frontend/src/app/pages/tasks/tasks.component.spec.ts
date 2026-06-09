import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { ToastService } from '@shared/ui';
import type { ApplicationListItem } from '@core/api/models';
import { TasksComponent } from './tasks.component';

function task(id: string, kind: string, title = 'Mein Antrag'): ApplicationListItem {
  return {
    id,
    typeId: 't1',
    title,
    state: { id: 's1', key: 's', label: 'Freigabe', category: 'running', editAllowed: false, kind },
    gremiumId: null,
    budgetPotId: null,
    amount: '120.00',
    currency: 'EUR',
    createdAt: '2026-06-01T10:00:00Z',
    updatedAt: '2026-06-01T10:00:00Z',
  };
}

async function setup(items: ApplicationListItem[], approval = jest.fn(() => of({}))) {
  const listTasks = jest.fn(() => of(items));
  const toast = { success: jest.fn(), error: jest.fn() };
  const api = { listTasks, submitApproval: approval };
  const view = await render(TasksComponent, {
    providers: [
      provideRouter([]),
      { provide: ApiClient, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, listTasks, approval, toast };
}

describe('TasksComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the title and accept/reject on an approval task', async () => {
    await setup([task('a1', 'approval')]);
    expect(screen.getByText('Mein Antrag')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Annehmen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ablehnen' })).toBeInTheDocument();
  });

  it('decides an approval task inline and reloads', async () => {
    const approval = jest.fn(() => of({}));
    const { listTasks } = await setup([task('a1', 'approval')], approval);
    await userEvent.click(screen.getByRole('button', { name: 'Annehmen' }));
    expect(approval).toHaveBeenCalledWith('a1', 'accept');
    expect(listTasks).toHaveBeenCalledTimes(2); // initial + reload
  });

  it('surfaces a forbidden decision as an error toast', async () => {
    const approval = jest.fn(() => throwError(() => ({ status: 403 })));
    const { toast } = await setup([task('a1', 'approval')], approval);
    await userEvent.click(screen.getByRole('button', { name: 'Ablehnen' }));
    expect(toast.error).toHaveBeenCalledWith('Keine Berechtigung für diese Entscheidung.');
  });

  it('offers Open instead of decide buttons on a vote task', async () => {
    await setup([task('v1', 'vote')]);
    expect(screen.getByRole('button', { name: 'Öffnen' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Annehmen' })).not.toBeInTheDocument();
  });
});
