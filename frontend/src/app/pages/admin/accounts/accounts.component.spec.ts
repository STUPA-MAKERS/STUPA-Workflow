import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BudgetTreeApi, type Account } from '../../budget/budget-tree.api';
import { AccountsComponent } from './accounts.component';

const FINTS_EMPTY = {
  fintsEndpoint: null,
  fintsBlz: null,
  fintsConfigured: false,
} as const;

const ACCOUNTS: Account[] = [
  { id: 'a-1', name: 'Hauptkonto', iban: 'DE111', active: true, ...FINTS_EMPTY },
  { id: 'a-2', name: 'Bar', iban: '', active: false, ...FINTS_EMPTY },
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

interface ApiOverrides {
  listAccounts?: jest.Mock;
  createAccount?: jest.Mock;
  updateAccount?: jest.Mock;
  deleteAccount?: jest.Mock;
}

function makeApi(o: ApiOverrides = {}) {
  return {
    listAccounts: o.listAccounts ?? jest.fn(() => of(clone(ACCOUNTS))),
    createAccount:
      o.createAccount ??
      jest.fn((b: { name: string }) => of<Account>({ id: 'a-new', iban: '', active: true, ...b })),
    updateAccount:
      o.updateAccount ??
      jest.fn((id: string, b: { name: string }) =>
        of<Account>({ id, iban: '', active: true, ...b }),
      ),
    deleteAccount: o.deleteAccount ?? jest.fn(() => of(void 0)),
  };
}

const evt = () => ({ preventDefault: jest.fn() }) as unknown as Event;

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AccountsComponent, {
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance;
  return { ...view, api, toast, cmp };
}

describe('AccountsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads accounts on init and renders names + iban placeholder', async () => {
    const { api } = await setup();
    expect(api.listAccounts).toHaveBeenCalled();
    expect(screen.getByText('Hauptkonto')).toBeInTheDocument();
    expect(screen.getByText('DE111')).toBeInTheDocument();
    // empty IBAN → em dash.
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('falls back to an empty list when loading fails', async () => {
    const api = makeApi({ listAccounts: jest.fn(() => throwError(() => new Error('boom'))) });
    const { cmp } = await setup(api);
    expect(cmp.accounts()).toEqual([]);
  });

  it('exposes localized columns including the trailing actions column', async () => {
    const { cmp } = await setup();
    expect(cmp.columns().map((c) => c.key)).toEqual(['name', 'iban', 'active', 'actions']);
    expect(cmp.rowId(ACCOUNTS[0])).toBe('a-1');
  });

  it('openCreate resets the form to a blank, active account', async () => {
    const { cmp } = await setup();
    cmp.fName.set('stale');
    cmp.fIban.set('stale');
    cmp.fActive.set(false);
    cmp.openCreate();
    expect(cmp.editing()).toBeNull();
    expect(cmp.fName()).toBe('');
    expect(cmp.fIban()).toBe('');
    expect(cmp.fActive()).toBe(true);
    expect(cmp.dialogOpen()).toBe(true);
  });

  it('openEdit prefills the form from the selected account', async () => {
    const { cmp } = await setup();
    cmp.openEdit(ACCOUNTS[1]);
    expect(cmp.editing()).toEqual(ACCOUNTS[1]);
    expect(cmp.fName()).toBe('Bar');
    expect(cmp.fIban()).toBe('');
    expect(cmp.fActive()).toBe(false);
    expect(cmp.dialogOpen()).toBe(true);
  });

  // -------------------------------------------------------------------- save
  it('does not save when the name is blank', async () => {
    const { cmp, api } = await setup();
    cmp.openCreate();
    cmp.fName.set('   ');
    const e = evt();
    cmp.save(e);
    expect(e.preventDefault).toHaveBeenCalled();
    expect(api.createAccount).not.toHaveBeenCalled();
    expect(cmp.saving()).toBe(false);
  });

  it('does not save when already saving (re-entrancy guard)', async () => {
    const { cmp, api } = await setup();
    cmp.openCreate();
    cmp.fName.set('X');
    cmp.saving.set(true);
    cmp.save(evt());
    expect(api.createAccount).not.toHaveBeenCalled();
  });

  it('creates a new account with trimmed values and reloads', async () => {
    const api = makeApi();
    const { cmp, toast } = await setup(api);
    cmp.openCreate();
    cmp.fName.set('  Neu  ');
    cmp.fIban.set('  DE99  ');
    cmp.fActive.set(true);
    cmp.save(evt());
    expect(api.createAccount).toHaveBeenCalledWith({
      name: 'Neu',
      iban: 'DE99',
      active: true,
      fintsEndpoint: null,
      fintsBlz: null,
    });
    expect(cmp.saving()).toBe(false);
    expect(cmp.dialogOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    expect(api.listAccounts).toHaveBeenCalledTimes(2);
  });

  it('updates an existing account via updateAccount', async () => {
    const api = makeApi();
    const { cmp } = await setup(api);
    cmp.openEdit(ACCOUNTS[0]);
    cmp.fName.set('Renamed');
    cmp.save(evt());
    expect(api.updateAccount).toHaveBeenCalledWith('a-1', {
      name: 'Renamed',
      iban: 'DE111',
      active: true,
      fintsEndpoint: null,
      fintsBlz: null,
    });
    expect(api.createAccount).not.toHaveBeenCalled();
  });

  it('toasts an error and clears saving when save fails', async () => {
    const api = makeApi({ createAccount: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, toast } = await setup(api);
    cmp.openCreate();
    cmp.fName.set('Neu');
    cmp.save(evt());
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.saving()).toBe(false);
    expect(cmp.dialogOpen()).toBe(true);
  });

  // ------------------------------------------------------------------ delete
  it('does nothing when deleting with no account selected', async () => {
    const { cmp, api } = await setup();
    cmp.doDelete();
    expect(api.deleteAccount).not.toHaveBeenCalled();
  });

  it('does not delete when already saving', async () => {
    const { cmp, api } = await setup();
    cmp.confirmDelete.set(ACCOUNTS[0]);
    cmp.saving.set(true);
    cmp.doDelete();
    expect(api.deleteAccount).not.toHaveBeenCalled();
  });

  it('deletes the selected account, closes the dialog and reloads', async () => {
    const api = makeApi();
    const { cmp, toast } = await setup(api);
    cmp.confirmDelete.set(ACCOUNTS[1]);
    cmp.doDelete();
    expect(api.deleteAccount).toHaveBeenCalledWith('a-2');
    expect(cmp.saving()).toBe(false);
    expect(cmp.confirmDelete()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
    expect(api.listAccounts).toHaveBeenCalledTimes(2);
  });

  it('toasts an error and clears saving when delete fails', async () => {
    const api = makeApi({ deleteAccount: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, toast } = await setup(api);
    cmp.confirmDelete.set(ACCOUNTS[0]);
    cmp.doDelete();
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.saving()).toBe(false);
    // dialog stays open so the user can retry.
    expect(cmp.confirmDelete()).not.toBeNull();
  });

  it('uses the injected I18nService for column labels', async () => {
    const { fixture } = await setup();
    const i18n = fixture.debugElement.injector.get(I18nService);
    expect(i18n).toBeTruthy();
  });
});
