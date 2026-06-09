import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { DeadlinePolicy } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@shared/ui';
import { AdminDeadlinesComponent } from './deadlines.component';

const POLICIES: DeadlinePolicy[] = [
  { id: 'dp-1', key: 'semester', label: { de: 'Semesterfrist', en: 'Semester' }, kind: 'absolute', absoluteAt: '2026-07-01T00:00:00Z' },
  { id: 'dp-2', key: 'edit_window', label: { de: 'Bearbeitung', en: 'Edit' }, kind: 'relative_changed', offsetDays: 7 },
];

function makeApi() {
  return {
    listDeadlinePolicies: jest.fn(() => of(POLICIES)),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createDeadlinePolicy: jest.fn((b: any) => of({ id: 'dp-new', ...b })),
    updateDeadlinePolicy: jest.fn((id: string, b: any) => of({ ...POLICIES[0], id, ...b })), // eslint-disable-line @typescript-eslint/no-explicit-any
    deleteDeadlinePolicy: jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminDeadlinesComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, api };
}

describe('AdminDeadlinesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists policies with key, kind and resolved value', async () => {
    await setup();
    expect(screen.getByText('Semesterfrist')).toBeInTheDocument();
    expect(screen.getByText('edit_window')).toBeInTheDocument();
    expect(screen.getByText('+ 7 Tage')).toBeInTheDocument();
  });

  it('creates a relative policy via the dialog', async () => {
    const { api, container } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Frist hinzufügen' }));
    const q = (sel: string) => container.querySelector<HTMLElement>(sel)!;
    // key + relative kind + offset → save enabled.
    await userEvent.type(q('input[name="key"]'), 'mahnung');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Art' }), 'relative_submitted');
    await userEvent.type(q('input[name="offsetDays"]'), '14');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.createDeadlinePolicy).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'mahnung', kind: 'relative_submitted', offsetDays: 14, absoluteAt: null }),
    );
  });
});
