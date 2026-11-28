import { render, screen } from '@testing-library/angular';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { MOCK_MOLLIE } from '@core/api/mock-sales';
import { type MollieConnection, type MollieConnectionIn, SalesApiService } from '@core/api/sales.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastWith } from '../../../../testing/load-error';
import { BudgetTreeApi } from '../../budget/budget-tree.api';
import { node } from '../../budget/plan/budget-plan.fixtures';
import { MollieComponent } from './mollie.component';

function makeApi(stored: MollieConnection = MOCK_MOLLIE) {
  return {
    getMollie: jest.fn(() => of({ ...stored })),
    putMollie: jest.fn((b: MollieConnectionIn) => of({ ...stored, ...b, tokenSet: stored.tokenSet || !!b.token })),
    testMollie: jest.fn(() => of({ ok: true, error: null as string | null, name: 'Studierendenschaft' as string | null })),
    mollieFailed: jest.fn(() => of({ items: [{ source: 'settlement', key: 'stl_1', error: 'no_actor', at: '2026-11-27T10:00:00Z' }] })),
  };
}

interface Page {
  act(key: string): void;
  save(): void;
  discard(): void;
  patch(change: Record<string, unknown>): void;
  groups(): { key: string; rows: { key: string; disabled?: boolean; value?: unknown }[] }[];
  screenState(): { state: string };
  notice(): unknown;
}

async function setup(opts: { api?: ReturnType<typeof makeApi>; perms?: string[]; treeFails?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.mollie']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const tree = jest.fn(() =>
    opts.treeFails ? throwError(() => new Error('x')) : of([node({ id: 'fees', name: 'Gebühren' })]),
  );
  const view = await render(MollieComponent, {
    providers: [
      provideRouter([]),
      { provide: SalesApiService, useValue: api },
      { provide: BudgetTreeApi, useValue: { tree } },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast, tree, page: view.fixture.componentInstance as unknown as Page };
}

const status = (page: Page) => page.groups().find((g) => g.key === 'status')?.rows ?? [];

describe('MollieComponent', () => {
  it('shows the token field, both cost centres, the status and the failed bookings', async () => {
    const { page } = await setup();
    expect(screen.getByLabelText(/Neuer Zugriffstoken/)).toBeTruthy();
    expect(screen.getByText('Kostenstelle der Gebühren')).toBeTruthy();
    expect(screen.getByText('Kostenstelle ohne Veranstaltung')).toBeTruthy();
    expect(screen.getByText('stl_1')).toBeTruthy();
    expect(screen.getByText(/Niemand ist als Verknüpfer/)).toBeTruthy();
    expect(status(page).map((r) => r.key)).toEqual(['organization', 'readOk']);
    expect(status(page)[0].value).toBe('Studierendenschaft Hochschule Reutlingen');
  });

  it('saves a new token and the cost centres, and clears an empty pick', async () => {
    const { page, api } = await setup();
    page.patch({ token: 'live_x', feeBudgetId: 'fees', unassignedBudgetId: '' });
    page.save();
    expect(api.putMollie).toHaveBeenCalledWith({ token: 'live_x', feeBudgetId: 'fees', unassignedBudgetId: null });
    page.patch({ feeBudgetId: '' });
    page.discard();
    page.save();
    expect(api.putMollie).toHaveBeenCalledTimes(1);
  });

  it('shows the cause of the last read that failed and no time without a read', async () => {
    const { page } = await setup({
      api: makeApi({ ...MOCK_MOLLIE, organization: null, readOkAt: null, readError: 'unauthorized', tokenSet: false }),
    });
    expect(status(page).map((r) => r.value)).toEqual(['–', '–', 'Der Dienst lehnt den Token ab.']);
    expect(page.groups().find((g) => g.key === 'actions')?.rows[0].disabled).toBe(true);
    expect(screen.getByLabelText(/^Zugriffstoken/)).toBeTruthy();
  });

  it('tests the connection and names the organization', async () => {
    const { page, toast, api } = await setup();
    page.act('test');
    expect(toast.success).toHaveBeenCalledWith('Die Verbindung zu Mollie steht: Studierendenschaft');
    page.act('other');
    expect(api.testMollie).toHaveBeenCalledTimes(1);
  });

  it('says when the failed bookings cannot be read', async () => {
    const api = makeApi();
    api.mollieFailed.mockReturnValueOnce(throwError(() => new Error('x')));
    const { page } = await setup({ api, treeFails: true });
    expect(page.notice()).toEqual({ kind: 'error', text: 'Die fehlgeschlagenen Buchungen konnten nicht geladen werden.' });
  });

  it('reads nothing without the right', async () => {
    const { page, api, tree } = await setup({ perms: [] });
    expect(page.screenState()).toEqual({ state: 'forbidden', message: 'Dir fehlt das Recht „Mollie verwalten“.' });
    expect(api.mollieFailed).not.toHaveBeenCalled();
    expect(tree).not.toHaveBeenCalled();
  });

  it('starts without cost centres', async () => {
    const api = makeApi({ ...MOCK_MOLLIE, feeBudgetId: 'fees', unassignedBudgetId: null });
    const { page } = await setup({ api });
    page.patch({ unassignedBudgetId: 'fees' });
    page.save();
    expect(api.putMollie).toHaveBeenCalledWith({ feeBudgetId: 'fees', unassignedBudgetId: 'fees' });
  });
});
