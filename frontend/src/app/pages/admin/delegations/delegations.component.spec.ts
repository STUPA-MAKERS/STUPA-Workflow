import { of, throwError } from 'rxjs';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { ToastService } from '@shared/ui/toast/toast.service';
import { DelegationsComponent } from './delegations.component';

const DELEGATIONS: Delegation[] = [
  {
    id: 'd-1',
    meetingId: 'm-1',
    meetingTitle: 'Sitzung A',
    meetingDate: '2026-07-01',
    gremiumId: 'g-1',
    gremiumName: 'StuPa',
    delegatorId: 'p-1',
    delegatorName: 'Alice',
    delegateId: 'p-2',
    delegateName: 'Bob',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-01T10:00:00Z',
    revocable: true,
    direction: null,
  },
  {
    id: 'd-2',
    meetingId: 'm-2',
    meetingTitle: null,
    meetingDate: null,
    gremiumId: 'g-1',
    gremiumName: 'StuPa',
    delegatorId: 'p-3',
    delegatorName: null,
    delegateId: 'p-4',
    delegateName: null,
    delegateVoting: false,
    viaPool: true,
    createdAt: '2026-06-02T10:00:00Z',
    revocable: false,
    direction: null,
  },
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

interface ApiOverrides {
  list?: jest.Mock;
  revoke?: jest.Mock;
}

function makeApi(o: ApiOverrides = {}) {
  return {
    list: o.list ?? jest.fn(() => of(clone(DELEGATIONS))),
    revoke: o.revoke ?? jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(DelegationsComponent, {
    providers: [
      provideRouter([]),
      { provide: DelegationsApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance as unknown as {
    delegations: () => Delegation[];
    loading: () => boolean;
    loadError: () => boolean;
    busy: () => boolean;
    confirmRevoke: { set: (d: Delegation | null) => void; (): Delegation | null };
    askRevoke: (d: Delegation) => void;
    revoke: () => void;
    columns: () => { key: string }[];
    rowId: (d: unknown) => string;
  };
  return { ...view, api, toast, cmp };
}

describe('DelegationsComponent (#delegation-rework)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads delegations on init and clears the loading flag', async () => {
    const { api, cmp } = await setup();
    expect(api.list).toHaveBeenCalled();
    expect(cmp.loading()).toBe(false);
    expect(cmp.loadError()).toBe(false);
    expect(cmp.delegations()).toHaveLength(2);
    // names rendered (delegator → delegate).
    expect(screen.getByText('Sitzung A')).toBeInTheDocument();
  });

  it('falls back to ids when title/names are missing', async () => {
    await setup();
    // second row has null meetingTitle → meetingId shown instead.
    expect(screen.getByText('m-2')).toBeInTheDocument();
  });

  it('sets the load-error flag when listing fails', async () => {
    const api = makeApi({ list: jest.fn(() => throwError(() => new Error('boom'))) });
    const { cmp } = await setup(api);
    expect(cmp.loadError()).toBe(true);
    expect(cmp.loading()).toBe(false);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('exposes localized columns and a row id accessor', async () => {
    const { cmp } = await setup();
    expect(cmp.columns().map((c) => c.key)).toEqual(['meeting', 'who', 'flags', 'actions']);
    expect(cmp.rowId(DELEGATIONS[0])).toBe('d-1');
  });

  // ------------------------------------------------------------------ revoke
  it('askRevoke arms the confirm dialog', async () => {
    const { cmp } = await setup();
    cmp.askRevoke(DELEGATIONS[0]);
    expect(cmp.confirmRevoke()).toEqual(DELEGATIONS[0]);
  });

  it('does nothing on revoke when nothing is armed', async () => {
    const { cmp, api } = await setup();
    cmp.revoke();
    expect(api.revoke).not.toHaveBeenCalled();
  });

  it('does nothing on revoke while busy', async () => {
    const { cmp, api } = await setup();
    cmp.confirmRevoke.set(DELEGATIONS[0]);
    // simulate an in-flight revoke by leaving busy=true via a never-completing call;
    // here we just directly assert the guard by setting busy first.
    (cmp as unknown as { busy: { set: (v: boolean) => void } }).busy.set(true);
    cmp.revoke();
    expect(api.revoke).not.toHaveBeenCalled();
  });

  it('revokes the armed delegation, removes the row and toasts success', async () => {
    const api = makeApi();
    const { cmp, toast } = await setup(api);
    cmp.askRevoke(DELEGATIONS[0]);
    cmp.revoke();
    expect(api.revoke).toHaveBeenCalledWith('d-1');
    expect(cmp.busy()).toBe(false);
    expect(cmp.confirmRevoke()).toBeNull();
    // d-1 filtered out, d-2 remains.
    expect(cmp.delegations().map((d) => d.id)).toEqual(['d-2']);
    expect(toast.success).toHaveBeenCalled();
  });

  it('toasts an error and clears busy when revoke fails', async () => {
    const api = makeApi({ revoke: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, toast } = await setup(api);
    cmp.askRevoke(DELEGATIONS[0]);
    cmp.revoke();
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.busy()).toBe(false);
    // list unchanged on failure.
    expect(cmp.delegations()).toHaveLength(2);
  });
});
