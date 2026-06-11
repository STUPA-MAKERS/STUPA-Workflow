import { of } from 'rxjs';
import { render, screen, fireEvent } from '@testing-library/angular';
import type { NotificationSettings } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { NotificationSettingsComponent } from './notification-settings.component';

const SETTINGS: NotificationSettings = {
  taskReminderEnabled: true,
  taskReminderAfterDays: 5,
  taskReminderRepeatDays: 7,
};

async function setup(settings: NotificationSettings = SETTINGS) {
  const putNotificationSettings = jest.fn((s: NotificationSettings) => of(s));
  const api = {
    getNotificationSettings: jest.fn(() => of(settings)),
    putNotificationSettings,
  };
  const view = await render(NotificationSettingsComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, putNotificationSettings };
}

describe('NotificationSettingsComponent (#task-reminder)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the loaded settings', async () => {
    await setup();
    expect(screen.getByText('Aufgaben-Erinnerungen')).toBeInTheDocument();
    expect(screen.getByLabelText(/Erinnern nach/)).toHaveValue(5);
    expect(screen.getByLabelText(/Wiederholen alle/)).toHaveValue(7);
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('saves changed values via PUT', async () => {
    const { fixture, putNotificationSettings } = await setup();
    fireEvent.input(screen.getByLabelText(/Erinnern nach/), { target: { value: '3' } });
    fixture.detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(putNotificationSettings).toHaveBeenCalledWith({
      taskReminderEnabled: true,
      taskReminderAfterDays: 3,
      taskReminderRepeatDays: 7,
    });
  });

  it('keeps save disabled until something changed', async () => {
    await setup();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
  });
});
