import { of, throwError } from 'rxjs';
import { render } from '@testing-library/angular';
import { ToastService } from '@shared/ui/toast/toast.service';
import {
  type AccountOption,
  BudgetTreeApi,
  type BankSyncResult,
  type StatementLine,
} from '../budget/budget-tree.api';
import { BankImportDialogComponent } from './bank-import-dialog.component';

const ACCOUNTS: AccountOption[] = [
  { id: 'acc-1', name: 'Giro', fintsConfigured: true },
  { id: 'acc-2', name: 'Bar', fintsConfigured: false },
];

const TREE = [
  { id: 'b-1', pathKey: 'VS-800', name: 'Referat', children: [] },
] as unknown as ReturnType<BudgetTreeApi['tree']> extends never ? never : unknown[];

function line(over: Partial<StatementLine> = {}): StatementLine {
  return {
    id: 'l-1',
    accountId: 'acc-1',
    amount: '-50.00',
    kind: 'expense',
    currency: 'EUR',
    bookingDate: '2024-01-02',
    valueDate: '2024-01-02',
    purpose: 'Miete',
    counterpartyName: 'Vermieter',
    counterpartyIban: 'DE99',
    endToEndId: null,
    reference: null,
    matchState: 'unmatched',
    suggestedBudgetId: null,
    suggestedPathKey: null,
    suggestedExpenseId: null,
    createdAt: '2024-01-02T00:00:00Z',
    ...over,
  };
}

const SYNC_DONE: BankSyncResult = {
  status: 'done',
  accountId: 'acc-1',
  imported: 2,
  duplicates: 1,
  sessionToken: null,
  challenge: null,
  challengeHtml: null,
  challengeImage: null,
  decoupled: false,
};

const SYNC_TAN: BankSyncResult = {
  status: 'needs_tan',
  accountId: 'acc-1',
  imported: 0,
  duplicates: 0,
  sessionToken: 'sess-1',
  challenge: 'Bitte TAN',
  challengeHtml: null,
  challengeImage: null,
  decoupled: false,
};

interface Overrides {
  listStatementLines?: jest.Mock;
  fintsSync?: jest.Mock;
  fintsSubmitTan?: jest.Mock;
  importStatementFile?: jest.Mock;
  confirmStatementLine?: jest.Mock;
  ignoreStatementLine?: jest.Mock;
  listAccountOptions?: jest.Mock;
  tree?: jest.Mock;
}

function makeApi(o: Overrides = {}) {
  return {
    listAccountOptions: o.listAccountOptions ?? jest.fn(() => of(ACCOUNTS)),
    tree: o.tree ?? jest.fn(() => of(TREE)),
    listStatementLines: o.listStatementLines ?? jest.fn(() => of([line()])),
    fintsSync: o.fintsSync ?? jest.fn(() => of(SYNC_DONE)),
    fintsSubmitTan: o.fintsSubmitTan ?? jest.fn(() => of(SYNC_DONE)),
    importStatementFile: o.importStatementFile ?? jest.fn(() => of({ accountId: 'acc-1', imported: 1, duplicates: 0 })),
    confirmStatementLine: o.confirmStatementLine ?? jest.fn(() => of({ id: 'e-1' })),
    ignoreStatementLine: o.ignoreStatementLine ?? jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi(), open = true) {
  const toast = { success: jest.fn(), error: jest.fn(), show: jest.fn() };
  const view = await render(BankImportDialogComponent, {
    inputs: { open },
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

describe('BankImportDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads accounts, tree and open lines on open', async () => {
    const { cmp, api } = await setup();
    expect(api.listAccountOptions).toHaveBeenCalled();
    expect(api.listStatementLines).toHaveBeenCalled();
    expect(cmp.accountId()).toBe('acc-1');
    expect(cmp.lines().length).toBe(1);
    expect(cmp.fintsAccountOptions().length).toBe(1); // nur fintsConfigured
    expect(cmp.fileAccountOptions().length).toBe(2);
    expect(cmp.costCentreOptions().length).toBe(1);
  });

  it('filters out matched/ignored lines and seeds suggested cost centre', async () => {
    const api = makeApi({
      listStatementLines: jest.fn(() =>
        of([
          line({ id: 'a', matchState: 'unmatched' }),
          line({ id: 'b', matchState: 'suggested', suggestedBudgetId: 'b-1' }),
          line({ id: 'c', matchState: 'matched' }),
          line({ id: 'd', matchState: 'ignored' }),
        ]),
      ),
    });
    const { cmp } = await setup(api);
    expect(cmp.lines().map((l) => l.id)).toEqual(['a', 'b']);
    expect(cmp.chosenBudget()['b']).toBe('b-1');
  });

  it('startSync done imports and reloads', async () => {
    const { cmp, api, toast } = await setup();
    api.listStatementLines.mockClear();
    cmp.startSync();
    expect(api.fintsSync).toHaveBeenCalledWith('acc-1');
    expect(toast.success).toHaveBeenCalled();
    expect(api.listStatementLines).toHaveBeenCalled();
  });

  it('startSync needs_tan exposes the TAN step', async () => {
    const { cmp } = await setup(makeApi({ fintsSync: jest.fn(() => of(SYNC_TAN)) }));
    cmp.startSync();
    expect(cmp.hasPendingTan()).toBe(true);
    expect(cmp.challenge()).toBe('Bitte TAN');
    expect(cmp.challengeImage()).toBe(''); // kein optischer Challenge
  });

  it('startSync needs_tan renders the photoTAN/QR image when provided', async () => {
    const dataUrl = 'data:image/png;base64,QQ==';
    const tanImg: BankSyncResult = { ...SYNC_TAN, challengeImage: dataUrl };
    const { cmp, fixture } = await setup(makeApi({ fintsSync: jest.fn(() => of(tanImg)) }));
    cmp.startSync();
    fixture.detectChanges();
    expect(cmp.challengeImage()).toBe(dataUrl);
    const img = fixture.nativeElement.querySelector('.bank__tanImg') as HTMLImageElement | null;
    expect(img?.getAttribute('src')).toBe(dataUrl);
  });

  it('submitTan done clears the TAN step and reloads', async () => {
    const { cmp } = await setup(makeApi({ fintsSync: jest.fn(() => of(SYNC_TAN)) }));
    cmp.startSync();
    cmp.tanCode.set('123456');
    cmp.submitTan();
    expect(cmp.hasPendingTan()).toBe(false);
  });

  it('submitTan still-needs-tan keeps step and toasts pending', async () => {
    const api = makeApi({
      fintsSync: jest.fn(() => of(SYNC_TAN)),
      fintsSubmitTan: jest.fn(() => of(SYNC_TAN)),
    });
    const { cmp, toast } = await setup(api);
    cmp.startSync();
    cmp.submitTan();
    expect(cmp.hasPendingTan()).toBe(true);
    expect(toast.show).toHaveBeenCalled();
  });

  it('submitTan error shows a message and clears busy', async () => {
    const api = makeApi({
      fintsSync: jest.fn(() => of(SYNC_TAN)),
      fintsSubmitTan: jest.fn(() => throwError(() => ({ error: { code: 'fints_tan_expired' } }))),
    });
    const { cmp, toast } = await setup(api);
    cmp.startSync();
    cmp.submitTan();
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.tanBusy()).toBe(false);
  });

  it('maps sync errors to messages', async () => {
    const api = makeApi({
      fintsSync: jest.fn(() => throwError(() => ({ error: { code: 'fints_not_configured' } }))),
    });
    const { cmp, toast } = await setup(api);
    cmp.startSync();
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.syncing()).toBe(false);
  });

  it.each(['fints_pin_undecryptable', 'fints_tan_expired', 'other'])(
    'maps sync error code %s to a message',
    async (code) => {
      const api = makeApi({
        fintsSync: jest.fn(() => throwError(() => ({ error: { code } }))),
      });
      const { cmp, toast } = await setup(api);
      cmp.startSync();
      expect(toast.error).toHaveBeenCalled();
    },
  );

  it('onFile without a selected file does nothing', async () => {
    const { cmp, api } = await setup();
    const inputEl = { files: [], value: '' } as unknown as HTMLInputElement;
    cmp.onFile({ target: inputEl } as unknown as Event);
    expect(api.importStatementFile).not.toHaveBeenCalled();
  });

  it('imports a file and reloads', async () => {
    const { cmp, api, toast } = await setup();
    const inputEl = { files: [new File(['x'], 's.sta')], value: 'x' } as unknown as HTMLInputElement;
    cmp.onFile({ target: inputEl } as unknown as Event);
    expect(api.importStatementFile).toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalled();
  });

  it('handles file import error', async () => {
    const api = makeApi({ importStatementFile: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, toast } = await setup(api);
    const inputEl = { files: [new File(['x'], 's.sta')], value: 'x' } as unknown as HTMLInputElement;
    cmp.onFile({ target: inputEl } as unknown as Event);
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.importing()).toBe(false);
  });

  it('confirm books a line, removes it and emits changed', async () => {
    const { cmp, api } = await setup();
    const changed = jest.fn();
    cmp.changed.subscribe(changed);
    cmp.setChosen('l-1', 'b-1');
    cmp.confirm(line());
    expect(api.confirmStatementLine).toHaveBeenCalledWith('l-1', { budgetId: 'b-1' });
    expect(cmp.lines().length).toBe(0);
    expect(changed).toHaveBeenCalled();
  });

  it('confirm without a cost centre does nothing', async () => {
    const { cmp, api } = await setup();
    cmp.confirm(line({ id: 'l-1' })); // chosenBudget leer
    expect(api.confirmStatementLine).not.toHaveBeenCalled();
  });

  it('confirm error keeps the line', async () => {
    const api = makeApi({ confirmStatementLine: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, toast } = await setup(api);
    cmp.setChosen('l-1', 'b-1');
    cmp.confirm(line());
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.lines().length).toBe(1);
  });

  it('ignore removes the line and emits changed', async () => {
    const { cmp, api } = await setup();
    const changed = jest.fn();
    cmp.changed.subscribe(changed);
    cmp.ignore(line());
    expect(api.ignoreStatementLine).toHaveBeenCalledWith('l-1');
    expect(cmp.lines().length).toBe(0);
    expect(changed).toHaveBeenCalled();
  });

  it('ignore error keeps the line', async () => {
    const api = makeApi({ ignoreStatementLine: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, toast } = await setup(api);
    cmp.ignore(line());
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.lines().length).toBe(1);
  });

  it('formats money as absolute EUR and close emits', async () => {
    const { cmp } = await setup();
    expect(cmp.money('-50.00')).toContain('50');
    const closed = jest.fn();
    cmp.closed.subscribe(closed);
    cmp.close();
    expect(closed).toHaveBeenCalled();
  });

  it('handles empty accounts on open', async () => {
    const { cmp } = await setup(makeApi({ listAccountOptions: jest.fn(() => of([])) }));
    expect(cmp.fintsAccountOptions().length).toBe(0);
  });

  it('handles list/tree load errors gracefully', async () => {
    const api = makeApi({
      listAccountOptions: jest.fn(() => throwError(() => new Error('x'))),
      tree: jest.fn(() => throwError(() => new Error('x'))),
      listStatementLines: jest.fn(() => throwError(() => new Error('x'))),
    });
    const { cmp } = await setup(api);
    expect(cmp.accounts().length).toBe(0);
    expect(cmp.costCentreOptions().length).toBe(0);
    expect(cmp.lines().length).toBe(0);
  });

  it('switches tabs', async () => {
    const { cmp } = await setup();
    cmp.tab.set('file');
    expect(cmp.tab()).toBe('file');
  });

  it('startSync is a no-op without an account', async () => {
    const { cmp, api } = await setup(makeApi({ listAccountOptions: jest.fn(() => of([])) }));
    cmp.startSync();
    expect(api.fintsSync).not.toHaveBeenCalled();
  });

  it('submitTan is a no-op without a pending session', async () => {
    const { cmp, api } = await setup();
    cmp.submitTan();
    expect(api.fintsSubmitTan).not.toHaveBeenCalled();
  });

  it('formats money in en locale', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { cmp } = await setup();
    expect(cmp.money('-5.00')).toMatch(/5/);
  });
});
