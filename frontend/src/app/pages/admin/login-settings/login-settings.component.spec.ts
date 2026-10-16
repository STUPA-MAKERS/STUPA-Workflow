import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { LoginSettings } from '../admin.models';
import { LoginSettingsComponent } from './login-settings.component';

type Body = Pick<LoginSettings, 'webSessionDays' | 'pwaSessionDays'>;

const STORED: LoginSettings = { webSessionDays: 90, pwaSessionDays: 180, updatedAt: null, updatedBy: null };

function makeApi(initial: LoginSettings = STORED) {
  return {
    getLoginSettings: jest.fn(() => of(initial)),
    putLoginSettings: jest.fn((b: Body) =>
      of({ ...b, updatedAt: '2026-10-12T08:30:00Z', updatedBy: 'admin-sub' } as LoginSettings),
    ),
  };
}

async function setup(opts: { api?: ReturnType<typeof makeApi> | Record<string, jest.Mock>; perms?: string[] } = {}) {
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.users']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(LoginSettingsComponent, {
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

const webField = (): HTMLInputElement => screen.getByLabelText('Anmeldung im Browser gültig für');
const pwaField = (): HTMLInputElement => screen.getByLabelText('Anmeldung in der installierten App gültig für');
const saveButton = (): HTMLButtonElement => screen.getByRole('button', { name: 'Speichern' });

describe('LoginSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the stored lifetimes', async () => {
    const { api } = await setup();
    expect(api.getLoginSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Anmeldung' })).toBeInTheDocument();
    expect(webField().value).toBe('90');
    expect(pwaField().value).toBe('180');
    // A setting that nobody changed has no change date.
    expect(screen.queryByText(/Zuletzt geändert/)).not.toBeInTheDocument();
    // Nothing changed yet: the save is off.
    expect(saveButton()).toBeDisabled();
  });

  it('saves both lifetimes and shows the change date', async () => {
    const { api, toast } = await setup();
    await userEvent.clear(webField());
    await userEvent.type(webField(), '30');
    await userEvent.clear(pwaField());
    await userEvent.type(pwaField(), '400');
    await userEvent.click(saveButton());
    expect(api.putLoginSettings).toHaveBeenCalledWith({ webSessionDays: 30, pwaSessionDays: 400 });
    expect(toast.success).toHaveBeenCalled();
    expect(screen.getByText(/Zuletzt geändert am/)).toBeInTheDocument();
    // The saved values are the new baseline.
    expect(saveButton()).toBeDisabled();
  });

  it('refuses a lifetime outside 1 to 400 and names the range', async () => {
    const { api } = await setup();
    for (const field of [webField, pwaField]) {
      for (const bad of ['0', '401', '1.5', '']) {
        await userEvent.clear(field());
        if (bad) await userEvent.type(field(), bad);
        expect(screen.getByText('Eine ganze Zahl von 1 bis 400 Tagen.')).toBeInTheDocument();
        expect(saveButton()).toBeDisabled();
      }
      await userEvent.clear(field());
      await userEvent.type(field(), '1');
      expect(saveButton()).toBeEnabled();
    }
    expect(api.putLoginSettings).not.toHaveBeenCalled();
  });

  it('turns the save off again when the draft returns to the stored values', async () => {
    const { c } = await setup();
    c.patch({ pwa: '200' });
    expect(c.canSave()).toBe(true);
    c.patch({ pwa: ' 180 ' });
    expect(c.canSave()).toBe(false);
  });

  it('toasts a failed save and keeps the draft', async () => {
    const api = { ...makeApi(), putLoginSettings: jest.fn(() => throwError(() => ({ status: 422 }))) };
    const { toast, c } = await setup({ api });
    await userEvent.clear(webField());
    await userEvent.type(webField(), '60');
    await userEvent.click(saveButton());
    expect(toast.error).toHaveBeenCalled();
    expect(c.draft().web).toBe('60');
    expect(saveButton()).toBeEnabled();
  });

  it('does nothing on save without a change or with an invalid field', async () => {
    const { api, c } = await setup();
    c.save();
    c.patch({ web: 'x' });
    c.save();
    expect(api.putLoginSettings).not.toHaveBeenCalled();
  });

  it('shows the date of the last change of a stored setting', async () => {
    await setup({ api: makeApi({ ...STORED, updatedAt: '2026-09-01T10:00:00Z', updatedBy: 'admin-sub' }) });
    expect(screen.getByText(/Zuletzt geändert am/)).toBeInTheDocument();
  });

  it('asks nothing and shows no form without admin.users', async () => {
    const { api, c } = await setup({ perms: [] });
    expect(api.getLoginSettings).not.toHaveBeenCalled();
    // Without stored values there is nothing to save.
    expect(c.canSave()).toBe(false);
    expect(screen.getByRole('alert')).toHaveTextContent('Für diese Einstellungen fehlt das Recht');
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  });

  it('hides the form after a 403 of the server', async () => {
    await setup({ api: { getLoginSettings: jest.fn(() => throwError(() => ({ status: 403 }))), putLoginSettings: jest.fn() } });
    expect(screen.getByRole('alert')).toHaveTextContent('Für diese Einstellungen fehlt das Recht');
    expect(screen.queryByLabelText('Anmeldung im Browser gültig für')).not.toBeInTheDocument();
  });

  it('names any other read failure', async () => {
    await setup({ api: { getLoginSettings: jest.fn(() => throwError(() => ({ status: 500 }))), putLoginSettings: jest.fn() } });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Einstellungen konnten nicht geladen werden.');
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  });

  it('reads an error without a status as a failure, not as a refusal', async () => {
    await setup({ api: { getLoginSettings: jest.fn(() => throwError(() => null)), putLoginSettings: jest.fn() } });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Einstellungen konnten nicht geladen werden.');
  });
});
