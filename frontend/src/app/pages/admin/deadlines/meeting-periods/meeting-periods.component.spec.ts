import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type { MeetingPeriods } from '../../admin.models';
import { MeetingPeriodsSettingsComponent } from './meeting-periods.component';
import { toastWith } from '../../../../../testing/load-error';

const STORED: MeetingPeriods = {
  inviteDaysOrdinary: 7,
  inviteDaysExtraordinary: 3,
  protocolDraftDays: 14,
  lateExcuseDays: 7,
  absenceLimit: 3,
  circularMinDays: 3,
  termStartMonth: 10,
};

function makeApi() {
  return {
    getMeetingPeriods: jest.fn(() => of(STORED)),
    putMeetingPeriods: jest.fn((b: MeetingPeriods) => of(b)),
  };
}

async function setup(opts: { api?: Record<string, jest.Mock>; perms?: string[] } = {}) {
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.deadlines']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(MeetingPeriodsSettingsComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

const field = (label: string): HTMLInputElement => screen.getByLabelText(label);

/** § 000917 */
describe('MeetingPeriodsSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the seven stored periods and saves a new one with the others', async () => {
    const { api, toast, c } = await setup();
    expect(screen.getByRole('heading', { name: 'Sitzungsfristen' })).toBeInTheDocument();
    expect(field('Ladungsfrist ordentliche Sitzung').value).toBe('7');
    expect(field('Ladungsfrist andere Sitzungen').value).toBe('3');
    expect(field('Protokollentwurf nach').value).toBe('14');
    expect(field('Nachträgliche Entschuldigung bis').value).toBe('7');
    expect(field('Umlaufbeschluss mindestens').value).toBe('3');
    expect(field('Unentschuldigte Fehlzeiten bis zum Mandatsverlust').value).toBe('3');
    expect(field('Beginn der Amtszeit (Monat)').value).toBe('10');
    expect(c.dirty()).toBe(false);
    await userEvent.clear(field('Ladungsfrist ordentliche Sitzung'));
    await userEvent.type(field('Ladungsfrist ordentliche Sitzung'), '10');
    expect(c.dirty()).toBe(true);
    c.save();
    expect(api.putMeetingPeriods).toHaveBeenCalledWith({ ...STORED, inviteDaysOrdinary: 10 });
    expect(toast.success).toHaveBeenCalled();
    expect(c.dirty()).toBe(false);
  });

  it('refuses a value outside the bounds of its field', async () => {
    const { api, c } = await setup();
    await userEvent.clear(field('Beginn der Amtszeit (Monat)'));
    await userEvent.type(field('Beginn der Amtszeit (Monat)'), '13');
    expect(screen.getByText('Eine ganze Zahl von 1 bis 12.')).toBeInTheDocument();
    expect(c.valid()).toBe(false);
    c.save();
    expect(api.putMeetingPeriods).not.toHaveBeenCalled();
    await userEvent.clear(field('Beginn der Amtszeit (Monat)'));
    expect(screen.getByText('Eine ganze Zahl von 1 bis 12.')).toBeInTheDocument();
    await userEvent.type(field('Beginn der Amtszeit (Monat)'), '4');
    expect(c.valid()).toBe(true);
  });

  it('puts the stored values back on discard', async () => {
    const { fixture, c } = await setup();
    await userEvent.clear(field('Protokollentwurf nach'));
    await userEvent.type(field('Protokollentwurf nach'), '21');
    c.discard();
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(field('Protokollentwurf nach').value).toBe('14');
    expect(c.dirty()).toBe(false);
  });

  it('shows nothing without the right and nothing after a 403', async () => {
    const api = makeApi();
    await setup({ api, perms: [] });
    expect(screen.queryByRole('heading', { name: 'Sitzungsfristen' })).toBeNull();
    expect(api.getMeetingPeriods).not.toHaveBeenCalled();
  });

  it('hides the section after a 403 of the read', async () => {
    const api = { ...makeApi(), getMeetingPeriods: jest.fn(() => throwError(() => ({ status: 403 }))) };
    await setup({ api });
    expect(screen.queryByRole('heading', { name: 'Sitzungsfristen' })).toBeNull();
  });
});
