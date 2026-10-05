import { of, throwError } from 'rxjs';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AuditEntry, AuditPage, ConfigRevisionDiff } from '../admin.models';
import { AuditLogComponent } from './audit-log.component';

const DIFF: ConfigRevisionDiff = {
  id: 'rev-2',
  entityType: 'flow',
  entityId: 'global',
  version: 2,
  prevVersion: 1,
  diff: { added: [], removed: [], changed: [{ key: 'state:review', old: 'A', new: 'B' }] },
};

function cfgEntry(over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 7,
    at: '2026-06-07T09:00:00+00:00',
    actor: 'kc|root',
    actorName: 'Root',
    action: 'config_activation',
    targetType: 'flow',
    targetId: 'global',
    data: { revisionId: 'rev-2', version: 2 },
    revertable: true,
    hash: 'h',
    prevHash: null,
    ...over,
  };
}

type Cmp = AuditLogComponent & {
  entries(): AuditEntry[];
  toggle(id: number): void;
  isRevertable(e: AuditEntry): boolean;
  diffOf(e: AuditEntry): ConfigRevisionDiff | null | undefined;
  askRevert(e: AuditEntry): void;
  doRevert(): void;
  confirmRevert(): AuditEntry | null;
  reverting(): boolean;
};

async function setup(
  opts: { canRevert?: boolean; revert?: jest.Mock; entryOver?: Partial<AuditEntry> } = {},
) {
  const page: AuditPage = {
    items: [cfgEntry(opts.entryOver)],
    nextCursor: null,
    hasMore: false,
  };
  const revertAuditEntry =
    opts.revert ??
    jest.fn(() => of({ revertedAuditId: 7, entityType: 'flow', entityId: 'global' }));
  const api = {
    listAuditLog: jest.fn(() => of(page)),
    listAuditActors: jest.fn(() => of([])),
    getConfigRevisionDiff: jest.fn(() => of(DIFF)),
    latestAuditVerification: jest.fn(() => of(null)),
    runAuditVerification: jest.fn(),
    revertAuditEntry,
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const auth = { can: jest.fn((p: string) => (opts.canRevert ?? true) && p === 'audit.revert') };
  const view = await render(AuditLogComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: auth },
    ],
  });
  return { ...view, c: view.fixture.componentInstance as unknown as Cmp, api, toast, revertAuditEntry };
}

describe('AuditLogComponent — config diff + revert', () => {
  it('loads the config diff when an entry with a revisionId is expanded', async () => {
    const { c, api } = await setup();
    c.toggle(7);
    expect(api.getConfigRevisionDiff).toHaveBeenCalledWith('rev-2');
    expect(c.diffOf(c.entries()[0])).toEqual(DIFF);
  });

  it('offers revert with the audit.revert permission', async () => {
    const { c } = await setup({ canRevert: true });
    expect(c.isRevertable(c.entries()[0])).toBe(true);
  });

  it('hides revert without the audit.revert permission', async () => {
    const { c } = await setup({ canRevert: false });
    expect(c.isRevertable(c.entries()[0])).toBe(false);
  });

  it('is not revertable when the backend flags it non-revertable (e.g. first version)', async () => {
    const { c } = await setup({ entryOver: { revertable: false } });
    expect(c.isRevertable(c.entries()[0])).toBe(false);
  });

  it('offers revert for a flagged non-config entry (status change / booking)', async () => {
    const { c } = await setup({
      entryOver: {
        action: 'status_change',
        targetType: 'application',
        data: { fromStateId: 'a', toStateId: 'b' },
        revertable: true,
      },
    });
    expect(c.isRevertable(c.entries()[0])).toBe(true);
  });

  it('reverts on confirm, then toasts success and reloads', async () => {
    const { c, revertAuditEntry, toast, api } = await setup();
    c.askRevert(c.entries()[0]);
    c.doRevert();
    expect(revertAuditEntry).toHaveBeenCalledWith(7);
    expect(toast.success).toHaveBeenCalled();
    // The revert triggers a reload, so the component reads the audit log a second time.
    expect(api.listAuditLog).toHaveBeenCalledTimes(2);
  });

  it('surfaces a stale-conflict message on HTTP 409', async () => {
    const revert = jest.fn(() =>
      throwError(() => ({ status: 409, error: { code: 'stale_revert' } })),
    );
    const { c, toast } = await setup({ revert });
    c.askRevert(c.entries()[0]);
    c.doRevert();
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/neuere|newer/i));
  });

  it('shows the diff, "Ziel öffnen" and "Zurücknehmen" in the opened entry, and confirms', async () => {
    const { c, fixture, revertAuditEntry } = await setup({ entryOver: { targetType: 'role', targetId: 'r-1' } });
    (fixture.nativeElement.querySelector('.al__row') as HTMLElement).click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-config-diff')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'Ziel öffnen' })).toHaveAttribute('href', '/admin/roles');
    await userEvent.click(screen.getByRole('button', { name: 'Zurücknehmen' }));
    expect(c.confirmRevert()).not.toBeNull();
    const dialog = screen.getByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Zurücknehmen' }));
    expect(revertAuditEntry).toHaveBeenCalledWith(7);
  });

  it('drops a failed diff load, so a second opening tries again', async () => {
    const { c, api } = await setup();
    (api.getConfigRevisionDiff as jest.Mock).mockReturnValueOnce(throwError(() => new Error('x')));
    c.toggle(7);
    expect(c.diffOf(c.entries()[0])).toBeUndefined();
    c.toggle(7);
    c.toggle(7);
    expect(api.getConfigRevisionDiff).toHaveBeenCalledTimes(2);
    expect(c.diffOf(c.entries()[0])).toEqual(DIFF);
  });

  it('loads a diff only once and has none for an entry without a revision', async () => {
    const { c, api } = await setup({ entryOver: { data: {} } });
    c.toggle(7);
    expect(api.getConfigRevisionDiff).not.toHaveBeenCalled();
    expect(c.diffOf(c.entries()[0])).toBeUndefined();
  });

  it('doRevert does nothing without a confirmation', async () => {
    const { c, revertAuditEntry } = await setup();
    c.doRevert();
    expect(revertAuditEntry).not.toHaveBeenCalled();
  });

  it.each([
    ['already_reverted', /bereits|already/i],
    ['not_revertable', /nicht zurückgenommen|cannot/i],
  ])('names the 409 code %s', async (code, text) => {
    const revert = jest.fn(() => throwError(() => ({ status: 409, error: { code } })));
    const { c, toast } = await setup({ revert });
    c.askRevert(c.entries()[0]);
    c.doRevert();
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(text));
  });

  it('gives the generic message for any other error', async () => {
    const revert = jest.fn(() => throwError(() => ({ status: 500 })));
    const { c, toast } = await setup({ revert });
    c.askRevert(c.entries()[0]);
    c.doRevert();
    expect(toast.error).toHaveBeenCalledWith('Rücknahme fehlgeschlagen.');
    expect(c.reverting()).toBe(false);
  });

  it('surfaces a "first state" message for the nothing_to_revert code', async () => {
    const revert = jest.fn(() =>
      throwError(() => ({ status: 409, error: { code: 'nothing_to_revert' } })),
    );
    const { c, toast } = await setup({ revert });
    c.askRevert(c.entries()[0]);
    c.doRevert();
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/erste|first/i));
  });
});
