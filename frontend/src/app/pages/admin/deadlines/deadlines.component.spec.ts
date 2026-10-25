import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { AdminDeadlinesComponent } from './deadlines.component';

function makeApi() {
  return {
    getMeetingSettings: jest.fn(() => of({ openLeadMinutes: 60, confirmLeadMinutes: 10 })),
    putMeetingSettings: jest.fn((b: object) => of({ ...b, updatedAt: null })),
    getGuestSettings: jest.fn(() => of({ confirmTtlHours: 12, linkTtlDays: null })),
    putGuestSettings: jest.fn((b: object) => of(b)),
  };
}

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminDeadlinesComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { can: () => true } },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

describe('AdminDeadlinesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the title and no floating button while nothing changed', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: 'Fristen & Fenster' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  it('shows "Speichern" while a settings section has changes and saves only that section', async () => {
    const { api } = await setup();
    const hours = screen.getByLabelText('Unbestätigte Anträge verwerfen nach');
    await userEvent.clear(hours);
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    await userEvent.type(hours, '48');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.putGuestSettings).toHaveBeenCalledWith({ confirmTtlHours: 48, linkTtlDays: null });
    expect(api.putMeetingSettings).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });
});
