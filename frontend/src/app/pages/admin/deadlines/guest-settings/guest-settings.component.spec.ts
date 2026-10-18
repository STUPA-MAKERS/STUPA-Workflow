import { of, throwError } from 'rxjs';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type { GuestSettings } from '../../admin.models';
import { GuestSettingsComponent } from './guest-settings.component';
import { pickOption } from '../../../../../testing/select';

function makeApi(initial: GuestSettings = { confirmTtlHours: 12, linkTtlDays: null }) {
  return {
    getGuestSettings: jest.fn(() => of(initial)),
    putGuestSettings: jest.fn((b: Pick<GuestSettings, 'confirmTtlHours' | 'linkTtlDays'>) => of({ ...b, updatedAt: null })),
  };
}

async function setup(opts: { api?: ReturnType<typeof makeApi> | Record<string, jest.Mock>; perms?: string[] } = {}) {
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.deadlines']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(GuestSettingsComponent, {
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

const hoursField = (): HTMLInputElement => screen.getByLabelText('Unbestätigte Anträge verwerfen nach');

describe('GuestSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the stored values: the hours and "Unbegrenzt" for a link without expiry', async () => {
    const { api, c } = await setup();
    expect(api.getGuestSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Anträge ohne Konto' })).toBeInTheDocument();
    expect(hoursField().value).toBe('12');
    const select = screen.getByLabelText('Gültigkeit des persönlichen Links');
    expect(select).toHaveTextContent('Unbegrenzt');
    expect(screen.queryByLabelText('Gültig für')).not.toBeInTheDocument();
    // Nothing changed yet. The section has no button of its own: the deadlines page
    // shows "Speichern" while a section has changes.
    expect(c.dirty()).toBe(false);
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  it('saves new hours and keeps "Unbegrenzt" as null', async () => {
    const { api, toast, c } = await setup();
    await userEvent.clear(hoursField());
    await userEvent.type(hoursField(), '48');
    expect(c.dirty()).toBe(true);
    c.save();
    expect(api.putGuestSettings).toHaveBeenCalledWith({ confirmTtlHours: 48, linkTtlDays: null });
    expect(toast.success).toHaveBeenCalled();
    // The saved values are the new baseline.
    expect(c.dirty()).toBe(false);
  });

  it('refuses hours outside 1 to 720 and names the range', async () => {
    const { api, c } = await setup();
    for (const bad of ['0', '721', '1.5', '']) {
      await userEvent.clear(hoursField());
      if (bad) await userEvent.type(hoursField(), bad);
      expect(screen.getByText('Eine ganze Zahl von 1 bis 720 Stunden.')).toBeInTheDocument();
      expect(c.valid()).toBe(false);
    }
    await userEvent.clear(hoursField());
    await userEvent.type(hoursField(), '720');
    expect(c.valid()).toBe(true);
    expect(api.putGuestSettings).not.toHaveBeenCalled();
  });

  it('limits the link to a number of days, and back to "Unbegrenzt"', async () => {
    const { api, c } = await setup();
    const select = screen.getByLabelText('Gültigkeit des persönlichen Links');
    await pickOption(select, 'Begrenzt');
    const days = screen.getByLabelText('Gültig für') as HTMLInputElement;
    // The field starts with 30 days, so a switch alone is a valid change.
    await waitFor(() => expect(days.value).toBe('30'));
    await userEvent.clear(days);
    await userEvent.type(days, '3651');
    expect(screen.getByText('Eine ganze Zahl von 1 bis 3650 Tagen.')).toBeInTheDocument();
    expect(c.valid()).toBe(false);
    await userEvent.clear(days);
    await userEvent.type(days, '90');
    c.save();
    expect(api.putGuestSettings).toHaveBeenLastCalledWith({ confirmTtlHours: 12, linkTtlDays: 90 });

    // "Unbegrenzt" sends null again; a typed day count stays in the draft.
    c.setMode('unlimited');
    c.setMode('days');
    expect(c.draft().days).toBe('90');
    c.setMode('unlimited');
    c.save();
    expect(api.putGuestSettings).toHaveBeenLastCalledWith({ confirmTtlHours: 12, linkTtlDays: null });
  });

  it('starts with the stored day count of a limited link', async () => {
    await setup({ api: makeApi({ confirmTtlHours: 6, linkTtlDays: 14 }) });
    expect((screen.getByLabelText('Gültig für') as HTMLInputElement).value).toBe('14');
  });

  it('toasts a failed save and keeps the draft', async () => {
    const api = { ...makeApi(), putGuestSettings: jest.fn(() => throwError(() => ({ status: 422 }))) };
    const { toast, c } = await setup({ api });
    await userEvent.clear(hoursField());
    await userEvent.type(hoursField(), '24');
    c.save();
    expect(toast.error).toHaveBeenCalled();
    expect(c.draft().hours).toBe('24');
    expect(c.dirty()).toBe(true);
    expect(c.saving()).toBe(false);
  });

  it('does nothing on save without a change or with an invalid field', async () => {
    const { api, c } = await setup();
    c.save();
    c.patch({ hours: 'x' });
    c.save();
    expect(api.putGuestSettings).not.toHaveBeenCalled();
  });

  it('shows nothing and asks nothing without admin.deadlines', async () => {
    const { api } = await setup({ perms: [] });
    expect(api.getGuestSettings).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: 'Anträge ohne Konto' })).not.toBeInTheDocument();
  });

  it('hides the section after a 403 of the server', async () => {
    await setup({ api: { getGuestSettings: jest.fn(() => throwError(() => ({ status: 403 }))), putGuestSettings: jest.fn() } });
    expect(screen.queryByRole('heading', { name: 'Anträge ohne Konto' })).not.toBeInTheDocument();
  });

  it('names any other read failure', async () => {
    await setup({ api: { getGuestSettings: jest.fn(() => throwError(() => ({ status: 500 }))), putGuestSettings: jest.fn() } });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Einstellungen konnten nicht geladen werden.');
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  });
});
