import { of } from 'rxjs';
import { render, screen, fireEvent } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { AccountNotificationsComponent } from './notifications.component';

const PREFS: NotificationPreference[] = [
  { kind: 'status_update', enabled: true },
  { kind: 'protocol', enabled: false },
];

async function setup(prefs: NotificationPreference[] = PREFS) {
  const setNotificationPreferences = jest.fn((p: NotificationPreference[]) => of(p));
  const api = {
    listNotificationPreferences: jest.fn(() => of(prefs)),
    setNotificationPreferences,
  };
  const view = await render(AccountNotificationsComponent, {
    providers: [{ provide: ApiClient, useValue: api }],
  });
  // ngModel schreibt asynchron in die Checkbox — auf Stabilität warten.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, setNotificationPreferences };
}

describe('AccountNotificationsComponent (#4-2)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the catalogue with localized labels and stored values', async () => {
    await setup();
    expect(screen.getByText('Status-Updates zu Anträgen')).toBeInTheDocument();
    expect(screen.getByText('Protokolle')).toBeInTheDocument();
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
  });

  it('saves the full preference set when a toggle changes', async () => {
    const { setNotificationPreferences } = await setup();
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[0]);
    expect(setNotificationPreferences).toHaveBeenCalledWith([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: false },
    ]);
  });

  it('falls back to the raw kind for unknown keys', async () => {
    await setup([{ kind: 'brand_new_kind', enabled: true }]);
    expect(screen.getByText('brand_new_kind')).toBeInTheDocument();
  });
});
