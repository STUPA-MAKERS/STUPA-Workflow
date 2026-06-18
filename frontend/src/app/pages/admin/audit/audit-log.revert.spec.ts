import { of, throwError } from 'rxjs';
import { provideRouter } from '@angular/router';
import { render } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@shared/ui';
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
    // Reload nach Revert: erneuter Audit-Abruf.
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
