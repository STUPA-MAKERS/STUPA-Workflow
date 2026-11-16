import { HttpErrorResponse } from '@angular/common/http';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { loadErrorToast, toastWith } from '../../../../testing/load-error';
import { AdminApiService } from '../admin-api.service';
import type { FeatureSwitches } from '../admin.models';
import { FeaturesComponent, enabledFeatures, usesOf } from './features.component';

const ALL_ON: FeatureSwitches = {
  todos: true,
  calendar: true,
  meetings: true,
  voting: true,
  budget: true,
  invoices: true,
  tickets: true,
};

function makeApi(initial: FeatureSwitches = ALL_ON) {
  return {
    getFeatures: jest.fn(() => of({ ...initial })),
    putFeatures: jest.fn((body: FeatureSwitches) => of({ ...body })),
  };
}

async function setup(opts: { api?: Record<string, jest.Mock>; perms?: string[] } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.features']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(FeaturesComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const features = view.fixture.debugElement.injector.get(FeatureService);
  return { ...view, api, toast, features };
}

const sw = (name: string) => screen.getByRole('switch', { name: new RegExp(`^${name}`) });
const save = () => screen.getByRole('button', { name: 'Speichern' });
const NAMES = ['Boards', 'Kalender', 'Sitzungen', 'Abstimmungen', 'Haushalt', 'Rechnungen', 'Tickets'];

describe('enabledFeatures', () => {
  it('switches a feature off with the feature it needs', () => {
    const on = enabledFeatures({ ...ALL_ON, budget: false });
    expect(on.budget).toBe(false);
    expect(on.invoices).toBe(false);
    expect(on.tickets).toBe(true);
  });
});

describe('usesOf', () => {
  it('reads the uses of the problem body and drops what it does not know', () => {
    expect(
      usesOf([
        { field: 'voting', msg: 'state:Abstimmung: StuPa' },
        { field: 'budget', msg: 'type:Projektantrag' },
        { field: 'meetings', msg: 'transition:Auf die Tagesordnung' },
        { field: 'nothing', msg: 'state:x' },
        { field: 'voting', msg: 'other:x' },
        { field: 'voting' },
        null,
      ]),
    ).toEqual([
      { feature: 'voting', kind: 'state', name: 'Abstimmung: StuPa' },
      { feature: 'budget', kind: 'type', name: 'Projektantrag' },
      { feature: 'meetings', kind: 'transition', name: 'Auf die Tagesordnung' },
    ]);
    expect(usesOf(undefined)).toEqual([]);
  });
});

/** Spec 000762: the page "Funktionen". */
describe('FeaturesComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows one switch for each feature, with nothing to save', async () => {
    const { api } = await setup();
    expect(api['getFeatures']).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Funktionen' })).toBeInTheDocument();
    for (const name of NAMES) expect(sw(name)).toHaveAttribute('aria-checked', 'true');
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Verwerfen' })).toBeNull();
  });

  it('does not load without admin.features', async () => {
    const { api } = await setup({ perms: ['admin.site'] });
    expect(api['getFeatures']).not.toHaveBeenCalled();
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it('says that the permission is missing when the load gets 403', async () => {
    const api = makeApi();
    api.getFeatures.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 403 })));
    await setup({ api });
    expect(screen.queryByRole('switch')).toBeNull();
    expect(loadErrorToast()).toBeNull();
  });

  it('reports a load fault', async () => {
    const api = makeApi();
    api.getFeatures.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
    await setup({ api });
    expect(screen.queryByRole('switch')).toBeNull();
    expect(loadErrorToast()).toContain('Die Einstellungen konnten nicht geladen werden.');
  });

  /** Spec 000760: a switch that needs a feature that is off is locked and says why. */
  it('locks Rechnungen while Budget is off and keeps its stored switch', async () => {
    const { api, fixture } = await setup();
    await userEvent.click(sw('Haushalt'));
    fixture.detectChanges();
    expect(sw('Rechnungen')).toHaveAttribute('aria-checked', 'false');
    expect(sw('Rechnungen')).toBeDisabled();
    expect(screen.getByText('Benötigt Haushalt')).toBeInTheDocument();
    await userEvent.click(save());
    fixture.detectChanges();
    expect(api['putFeatures']).not.toHaveBeenCalled();
    expect(screen.getByText(/Haushalt, Rechnungen/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ausschalten' }));
    expect(api['putFeatures']).toHaveBeenCalledWith({ ...ALL_ON, budget: false });
  });

  it('asks before a feature goes off and saves nothing on "Abbrechen"', async () => {
    const { api, fixture } = await setup();
    await userEvent.click(sw('Kalender'));
    await userEvent.click(save());
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(api['putFeatures']).not.toHaveBeenCalled();
  });

  it('saves a feature that goes on without a question and tells the navigation', async () => {
    const { api, toast, features, fixture } = await setup({
      api: makeApi({ ...ALL_ON, budget: false }),
    });
    await userEvent.click(sw('Haushalt'));
    fixture.detectChanges();
    await userEvent.click(save());
    expect(api['putFeatures']).toHaveBeenCalledWith(ALL_ON);
    expect(toast.success).toHaveBeenCalled();
    expect(features.isOn('budget', 'invoices')).toBe(true);
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  it('switches the features off in the navigation after the save', async () => {
    const { features, fixture } = await setup();
    await userEvent.click(sw('Haushalt'));
    await userEvent.click(save());
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Ausschalten' }));
    expect(features.isOn('budget')).toBe(false);
    expect(features.isOn('invoices')).toBe(false);
    expect(features.isOn('tickets')).toBe(true);
  });

  it('sets the switches back on "Verwerfen"', async () => {
    const { fixture } = await setup();
    await userEvent.click(sw('Tickets'));
    fixture.detectChanges();
    expect(sw('Tickets')).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    fixture.detectChanges();
    expect(sw('Tickets')).toHaveAttribute('aria-checked', 'true');
  });

  /** Spec 000761: the page names each use that keeps a feature on. */
  it('names the uses when the server refuses the save', async () => {
    const api = makeApi();
    api.putFeatures.mockReturnValueOnce(
      throwError(
        () =>
          new HttpErrorResponse({
            status: 409,
            error: {
              code: 'feature_in_use',
              errors: [{ field: 'voting', msg: 'state:Abstimmung im StuPa' }],
            },
          }),
      ),
    );
    const { toast, fixture } = await setup({ api });
    await userEvent.click(sw('Abstimmungen'));
    await userEvent.click(save());
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Ausschalten' }));
    fixture.detectChanges();
    expect(toast.error).toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Abstimmung im StuPa');
  });

  it('reports another save fault without a use', async () => {
    const api = makeApi({ ...ALL_ON, tickets: false });
    api.putFeatures.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
    const { toast, fixture } = await setup({ api });
    await userEvent.click(sw('Tickets'));
    await userEvent.click(save());
    fixture.detectChanges();
    expect(toast.error).toHaveBeenCalled();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
