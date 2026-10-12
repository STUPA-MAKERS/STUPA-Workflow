import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type { MeetingSettings } from '../../admin.models';
import { MeetingWindowSettingsComponent } from './meeting-window.component';

type Body = Pick<MeetingSettings, 'openLeadMinutes' | 'confirmLeadMinutes'>;

function makeApi(initial: MeetingSettings = { openLeadMinutes: 60, confirmLeadMinutes: 10 }) {
  return {
    getMeetingSettings: jest.fn(() => of(initial)),
    putMeetingSettings: jest.fn((b: Body) => of({ ...b, updatedAt: null })),
  };
}

async function setup(opts: { api?: Record<string, jest.Mock>; perms?: string[] } = {}) {
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.deadlines']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(MeetingWindowSettingsComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useValue: toast },
    ],
  });
  // ngModel writes the stored values into the fields after a tick.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

const openField = (): HTMLInputElement => screen.getByLabelText('Frühestens eröffnen');
const confirmField = (): HTMLInputElement => screen.getByLabelText('Ohne Rückfrage eröffnen ab');
const saveButton = (): HTMLButtonElement => screen.getByRole('button', { name: 'Speichern' });

describe('MeetingWindowSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the stored minutes and saves new ones', async () => {
    const { api, toast } = await setup();
    expect(screen.getByRole('heading', { name: 'Sitzung eröffnen' })).toBeInTheDocument();
    expect(openField().value).toBe('60');
    expect(confirmField().value).toBe('10');
    expect(saveButton()).toBeDisabled();
    await userEvent.clear(openField());
    await userEvent.type(openField(), '90');
    await userEvent.clear(confirmField());
    await userEvent.type(confirmField(), '0');
    await userEvent.click(saveButton());
    expect(api.putMeetingSettings).toHaveBeenCalledWith({ openLeadMinutes: 90, confirmLeadMinutes: 0 });
    expect(toast.success).toHaveBeenCalled();
    expect(saveButton()).toBeDisabled();
  });

  it('refuses a value outside the range and a confirm point before the open', async () => {
    const { api } = await setup();
    await userEvent.clear(openField());
    await userEvent.type(openField(), '10081');
    expect(screen.getByText('Eine ganze Zahl von 0 bis 10080 Minuten.')).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    await userEvent.clear(openField());
    await userEvent.type(openField(), '5');
    expect(screen.getByText('Höchstens so viele Minuten wie bei „Frühestens eröffnen“.')).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    await userEvent.clear(confirmField());
    expect(screen.getByText('Eine ganze Zahl von 0 bis 10080 Minuten.')).toBeInTheDocument();
    await userEvent.type(confirmField(), '5');
    expect(saveButton()).toBeEnabled();
    expect(api.putMeetingSettings).not.toHaveBeenCalled();
  });

  it('toasts a failed save and keeps the draft', async () => {
    const api = { ...makeApi(), putMeetingSettings: jest.fn(() => throwError(() => ({ status: 422 }))) };
    const { toast, c } = await setup({ api });
    await userEvent.clear(openField());
    await userEvent.type(openField(), '30');
    await userEvent.click(saveButton());
    expect(toast.error).toHaveBeenCalled();
    expect(c.draft().open).toBe('30');
    expect(saveButton()).toBeEnabled();
  });

  it('does nothing on save without a change or with an invalid field', async () => {
    const { api, c } = await setup();
    c.save();
    c.patch({ confirm: 'x' });
    c.save();
    expect(api.putMeetingSettings).not.toHaveBeenCalled();
  });

  it('shows nothing and asks nothing without admin.deadlines', async () => {
    const { api } = await setup({ perms: [] });
    expect(api.getMeetingSettings).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: 'Sitzung eröffnen' })).not.toBeInTheDocument();
  });

  it('hides the section after a 403 of the server', async () => {
    await setup({
      api: { getMeetingSettings: jest.fn(() => throwError(() => ({ status: 403 }))), putMeetingSettings: jest.fn() },
    });
    expect(screen.queryByRole('heading', { name: 'Sitzung eröffnen' })).not.toBeInTheDocument();
  });

  it('names any other read failure', async () => {
    await setup({
      api: { getMeetingSettings: jest.fn(() => throwError(() => ({ status: 500 }))), putMeetingSettings: jest.fn() },
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Einstellungen konnten nicht geladen werden.');
  });
});
