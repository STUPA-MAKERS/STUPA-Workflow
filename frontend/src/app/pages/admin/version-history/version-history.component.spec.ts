import { of, throwError } from 'rxjs';
import { render } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { ConfigRevision, ConfigRevisionDiff } from '../admin.models';
import { VersionHistoryComponent } from './version-history.component';

const REVS: ConfigRevision[] = [
  {
    id: 'r2',
    entityType: 'form',
    entityId: 't1',
    version: 2,
    at: '2026-06-10T10:00:00Z',
    createdBy: 'sub-a',
    createdByName: 'Alice',
    isCurrent: true,
  },
  {
    id: 'r1',
    entityType: 'form',
    entityId: 't1',
    version: 1,
    at: '2026-06-09T10:00:00Z',
    createdBy: null,
    createdByName: null,
    isCurrent: false,
  },
];

const DIFF: ConfigRevisionDiff = {
  id: 'r2',
  entityType: 'form',
  entityId: 't1',
  version: 2,
  prevVersion: 1,
  diff: { added: [], removed: [], changed: [{ key: 'field:x', old: 'a', new: 'b' }] },
};

type Cmp = VersionHistoryComponent & {
  revisions(): ConfigRevision[];
  toggleDiff(r: ConfigRevision): void;
  askRestore(r: ConfigRevision): void;
  doRestore(): void;
  diff(): ConfigRevisionDiff | null;
  reload(): void;
};

async function setup(over: Record<string, unknown> = {}) {
  const api = {
    listConfigRevisions: jest.fn(() => of(REVS)),
    getConfigRevisionDiff: jest.fn(() => of(DIFF)),
    restoreConfigRevision: jest.fn(() => of(void 0)),
    ...over,
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(VersionHistoryComponent, {
    inputs: { entityType: 'form', entityId: 't1' },
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, c: view.fixture.componentInstance as unknown as Cmp, api, toast };
}

describe('VersionHistoryComponent', () => {
  it('lists every revision (newest first) and marks the current one', async () => {
    const { c, api, container } = await setup();
    expect(api.listConfigRevisions).toHaveBeenCalledWith('form', 't1');
    expect(c.revisions().length).toBe(2);
    expect(container.textContent).toContain('Version 2');
    expect(container.textContent).toContain('Version 1');
    // Genau ein »Aktiv«-Badge (der Kopf-Stand).
    expect(container.querySelectorAll('app-badge').length).toBe(1);
  });

  it('exposes NO delete control (a version is never removable)', async () => {
    const { container } = await setup();
    const text = (container.textContent ?? '').toLowerCase();
    expect(text).not.toContain('löschen');
    expect(text).not.toContain('delete');
    expect(container.querySelector('[data-action="delete"]')).toBeNull();
  });

  it('loads the diff on demand for a revision', async () => {
    const { c, api } = await setup();
    c.toggleDiff(REVS[0]);
    expect(api.getConfigRevisionDiff).toHaveBeenCalledWith('r2');
    expect(c.diff()).toEqual(DIFF);
  });

  it('restores a prior version on confirm and reloads + toasts', async () => {
    const { c, api, toast } = await setup();
    c.askRestore(REVS[1]);
    c.doRestore();
    expect(api.restoreConfigRevision).toHaveBeenCalledWith('r1');
    expect(toast.success).toHaveBeenCalled();
    // Reload nach Restore: zweiter Listen-Abruf.
    expect(api.listConfigRevisions).toHaveBeenCalledTimes(2);
  });

  it('toasts an error when the restore fails', async () => {
    const restoreConfigRevision = jest.fn(() => throwError(() => new Error('boom')));
    const { c, toast } = await setup({ restoreConfigRevision });
    c.askRestore(REVS[1]);
    c.doRestore();
    expect(toast.error).toHaveBeenCalled();
  });

  it('renders an empty hint when there are no revisions', async () => {
    const { container } = await setup({ listConfigRevisions: jest.fn(() => of([])) });
    expect(container.querySelector('.vh')).toBeNull();
  });
});
