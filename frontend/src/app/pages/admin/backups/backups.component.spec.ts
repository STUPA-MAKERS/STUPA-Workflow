import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Backup, BackupList } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { BackupsComponent } from './backups.component';

const DONE: Backup = {
  id: 'b-1',
  kind: 'manual',
  status: 'done',
  createdAt: '2026-09-01T04:00:00Z',
  finishedAt: '2026-09-01T04:03:00Z',
  sizeBytes: 48_234_496,
  objectCount: 137,
  note: 'Vor der Abstimmung',
  pinned: false,
};

const PINNED: Backup = { ...DONE, id: 'b-2', pinned: true, note: null };
const RUNNING: Backup = { ...DONE, id: 'b-3', status: 'running', sizeBytes: null };

interface ApiOverrides {
  listBackups?: jest.Mock;
  getBackup?: jest.Mock;
  createBackup?: jest.Mock;
  updateBackup?: jest.Mock;
  exportBackup?: jest.Mock;
  importBackup?: jest.Mock;
  restoreBackup?: jest.Mock;
  deleteBackup?: jest.Mock;
}

function list(over: Partial<BackupList> = {}): BackupList {
  return {
    items: [DONE, PINNED],
    enabled: true,
    restoreEnabled: true,
    retentionCount: 14,
    ...over,
  };
}

function makeApi(o: ApiOverrides = {}) {
  return {
    listBackups: o.listBackups ?? jest.fn(() => of(list())),
    getBackup: o.getBackup ?? jest.fn(() => of(DONE)),
    createBackup: o.createBackup ?? jest.fn(() => of({ ...DONE, id: 'b-new', status: 'pending' })),
    updateBackup: o.updateBackup ?? jest.fn((_id: string, patch: Record<string, unknown>) =>
      of({ ...DONE, ...patch }),
    ),
    exportBackup:
      o.exportBackup ?? jest.fn(() => of(new Blob(['cipher'], { type: 'application/octet-stream' }))),
    importBackup: o.importBackup ?? jest.fn(() => of({ ...DONE, id: 'b-imp', kind: 'imported' })),
    restoreBackup: o.restoreBackup ?? jest.fn(() => of(DONE)),
    deleteBackup: o.deleteBackup ?? jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn(), show: jest.fn() };
  const view = await render(BackupsComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

describe('BackupsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.useRealTimers());

  it('loads the catalogue on init', async () => {
    const { api } = await setup();
    expect(api.listBackups).toHaveBeenCalled();
    expect(screen.getByText('Vor der Abstimmung')).toBeInTheDocument();
  });

  it('formats sizes in units a person can read', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance as unknown as {
      sizeLabel: (b: number | null) => string;
    };
    expect(cmp.sizeLabel(null)).toBe('—');
    expect(cmp.sizeLabel(512)).toBe('512 B');
    expect(cmp.sizeLabel(48_234_496)).toBe('46.0 MB');
    expect(cmp.sizeLabel(3_221_225_472)).toBe('3.0 GB');
  });

  it('explains itself instead of offering a button when backups are not configured', async () => {
    const api = makeApi({ listBackups: jest.fn(() => of(list({ enabled: false }))) });
    await setup(api);
    expect(screen.getByText(/nicht eingerichtet/i)).toBeInTheDocument();
  });

  it('hides restore when the platform cannot decrypt its own archives', async () => {
    const api = makeApi({ listBackups: jest.fn(() => of(list({ restoreEnabled: false }))) });
    await setup(api);
    expect(screen.queryByRole('button', { name: 'Zurücksetzen' })).not.toBeInTheDocument();
  });

  it('says why the import is dead rather than leaving a greyed-out button', async () => {
    // The button was disabled with nothing beside it, which reads as a broken page. An
    // import decrypts the archive to verify it, so it needs the private key.
    const api = makeApi({ listBackups: jest.fn(() => of(list({ restoreEnabled: false }))) });
    await setup(api);
    expect(screen.getByText(/BACKUP_AGE_IDENTITY_FILE/)).toBeInTheDocument();
  });

  it('says nothing about the key when the key is there', async () => {
    await setup();
    expect(screen.queryByText(/BACKUP_AGE_IDENTITY_FILE/)).not.toBeInTheDocument();
  });

  it('creates a backup with the typed note', async () => {
    const { api } = await setup();
    const note = screen.getByLabelText(/Notiz/i);
    await userEvent.type(note, 'vor dem Umzug');
    await userEvent.click(screen.getByRole('button', { name: /Sicherung anlegen/i }));
    expect(api.createBackup).toHaveBeenCalledWith('vor dem Umzug');
  });

  it('sends null rather than an empty note', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /Sicherung anlegen/i }));
    expect(api.createBackup).toHaveBeenCalledWith(null);
  });

  it('downloads the archive bytes instead of opening a store URL', async () => {
    // Regression: MinIO is internal, so a presigned URL names a host the browser cannot
    // resolve. The bytes come through the API and are saved as a blob.
    (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
    (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
    const open = jest.spyOn(window, 'open').mockImplementation(() => null);
    const { api } = await setup();
    await userEvent.click(screen.getAllByRole('button', { name: 'Herunterladen' })[0]);
    expect(api.exportBackup).toHaveBeenCalledWith('b-1');
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it('pins and unpins an archive', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getAllByRole('button', { name: 'Anheften' })[0]);
    expect(api.updateBackup).toHaveBeenCalledWith('b-1', { pinned: true });
  });

  // A restore replaces the whole platform, so the confirmation is the safety rail.
  describe('restore', () => {
    it('stays disabled until the confirmation word is typed', async () => {
      await setup();
      await userEvent.click(screen.getAllByRole('button', { name: 'Zurücksetzen' })[0]);
      const confirm = screen.getAllByRole('button', { name: 'Zurücksetzen' }).at(-1)!;
      expect(confirm).toBeDisabled();
    });

    it('does not fire on a near miss', async () => {
      const { api } = await setup();
      await userEvent.click(screen.getAllByRole('button', { name: 'Zurücksetzen' })[0]);
      await userEvent.type(screen.getByLabelText(/RESTORE/i), 'restor');
      expect(screen.getAllByRole('button', { name: 'Zurücksetzen' }).at(-1)!).toBeDisabled();
      expect(api.restoreBackup).not.toHaveBeenCalled();
    });

    it('fires once the word matches, and warns that the session ends', async () => {
      const { api, toast } = await setup();
      await userEvent.click(screen.getAllByRole('button', { name: 'Zurücksetzen' })[0]);
      await userEvent.type(screen.getByLabelText(/RESTORE/i), 'RESTORE');
      await userEvent.click(screen.getAllByRole('button', { name: 'Zurücksetzen' }).at(-1)!);
      expect(api.restoreBackup).toHaveBeenCalledWith('b-1');
      expect(toast.show).toHaveBeenCalledWith(expect.stringMatching(/abgemeldet/i), 'warning');
    });
  });

  describe('delete', () => {
    it('deletes after the confirmation', async () => {
      const { api } = await setup();
      await userEvent.click(screen.getAllByRole('button', { name: 'Löschen' })[0]);
      await userEvent.click(screen.getAllByRole('button', { name: 'Löschen' }).at(-1)!);
      expect(api.deleteBackup).toHaveBeenCalledWith('b-1');
    });

    it('refuses a pinned archive in the UI, not only in the API', async () => {
      await setup();
      // The second row is pinned, so its delete button is disabled.
      expect(screen.getAllByRole('button', { name: 'Löschen' })[1]).toBeDisabled();
    });
  });

  it('polls while a job runs and stops when it finishes', async () => {
    jest.useFakeTimers();
    const getBackup = jest.fn(() => of({ ...RUNNING, status: 'done' as const }));
    const api = makeApi({
      listBackups: jest.fn(() => of(list({ items: [RUNNING] }))),
      getBackup,
    });
    const toast = { success: jest.fn(), error: jest.fn(), show: jest.fn() };
    const view = await render(BackupsComponent, {
      providers: [
        { provide: AdminApiService, useValue: api },
        { provide: ToastService, useValue: toast },
      ],
    });
    jest.advanceTimersByTime(3000);
    expect(getBackup).toHaveBeenCalledWith('b-3');
    expect(toast.success).toHaveBeenCalled();
    // The row is done now, so a second tick must not poll again.
    getBackup.mockClear();
    jest.advanceTimersByTime(9000);
    expect(getBackup).not.toHaveBeenCalled();
    view.fixture.destroy();
  });

  it('keeps the page usable when the catalogue cannot be loaded', async () => {
    const api = makeApi({ listBackups: jest.fn(() => throwError(() => new Error('boom'))) });
    const { fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as { loading: () => boolean };
    expect(cmp.loading()).toBe(false);
  });
  describe('import', () => {
    function fileEvent(file?: File): Event {
      const input = document.createElement('input');
      Object.defineProperty(input, 'files', {
        value: file ? [file] : [],
        configurable: true,
      });
      return { target: input } as unknown as Event;
    }

    it('uploads the chosen file and clears the picker', async () => {
      const { fixture, api } = await setup();
      const cmp = fixture.componentInstance as unknown as { upload: (e: Event) => void };
      const file = new File(['x'], 'archive.tar.age');
      const event = fileEvent(file);
      cmp.upload(event);
      expect(api.importBackup).toHaveBeenCalledWith(file);
      expect((event.target as HTMLInputElement).value).toBe('');
    });

    it('does nothing when the picker was dismissed', async () => {
      const { fixture, api } = await setup();
      const cmp = fixture.componentInstance as unknown as { upload: (e: Event) => void };
      cmp.upload(fileEvent());
      expect(api.importBackup).not.toHaveBeenCalled();
    });

    it('releases the busy flag when the upload is rejected', async () => {
      const api = makeApi({ importBackup: jest.fn(() => throwError(() => new Error('422'))) });
      const { fixture } = await setup(api);
      const cmp = fixture.componentInstance as unknown as {
        upload: (e: Event) => void;
        busy: () => boolean;
      };
      cmp.upload(fileEvent(new File(['x'], 'a.age')));
      expect(cmp.busy()).toBe(false);
    });
  });

  describe('failures release the UI', () => {
    it('after a failed create', async () => {
      const api = makeApi({ createBackup: jest.fn(() => throwError(() => new Error('503'))) });
      const { fixture } = await setup(api);
      const cmp = fixture.componentInstance as unknown as {
        create: () => void;
        creating: () => boolean;
      };
      cmp.create();
      expect(cmp.creating()).toBe(false);
    });

    it('after a failed restore', async () => {
      const api = makeApi({ restoreBackup: jest.fn(() => throwError(() => new Error('503'))) });
      const { fixture } = await setup(api);
      const cmp = fixture.componentInstance as unknown as {
        askRestore: (r: Backup) => void;
        restoreConfirmText: { set: (v: string) => void };
        doRestore: () => void;
        busy: () => boolean;
      };
      cmp.askRestore(DONE);
      cmp.restoreConfirmText.set('RESTORE');
      cmp.doRestore();
      expect(cmp.busy()).toBe(false);
    });

    it('after a failed delete', async () => {
      const api = makeApi({ deleteBackup: jest.fn(() => throwError(() => new Error('409'))) });
      const { fixture } = await setup(api);
      const cmp = fixture.componentInstance as unknown as {
        askDelete: (r: Backup) => void;
        doDelete: () => void;
        busy: () => boolean;
      };
      cmp.askDelete(DONE);
      cmp.doDelete();
      expect(cmp.busy()).toBe(false);
    });
  });

  describe('guards that stop a destructive action firing on nothing', () => {
    it('restore does nothing without a target', async () => {
      const { fixture, api } = await setup();
      const cmp = fixture.componentInstance as unknown as { doRestore: () => void };
      cmp.doRestore();
      expect(api.restoreBackup).not.toHaveBeenCalled();
    });

    it('delete does nothing without a target', async () => {
      const { fixture, api } = await setup();
      const cmp = fixture.componentInstance as unknown as { doDelete: () => void };
      cmp.doDelete();
      expect(api.deleteBackup).not.toHaveBeenCalled();
    });
  });

  describe('polling', () => {
    it('reports a job that ends in failure', async () => {
      jest.useFakeTimers();
      const api = makeApi({
        listBackups: jest.fn(() => of(list({ items: [RUNNING] }))),
        getBackup: jest.fn(() => of({ ...RUNNING, status: 'failed' as const, error: 'pg_dump failed' })),
      });
      const toast = { success: jest.fn(), error: jest.fn(), show: jest.fn() };
      const view = await render(BackupsComponent, {
        providers: [
          { provide: AdminApiService, useValue: api },
          { provide: ToastService, useValue: toast },
        ],
      });
      jest.advanceTimersByTime(3000);
      expect(toast.error).toHaveBeenCalled();
      view.fixture.destroy();
    });

    it('gives up rather than polling for ever behind a stuck worker', async () => {
      jest.useFakeTimers();
      const getBackup = jest.fn(() => of(RUNNING));
      const api = makeApi({
        listBackups: jest.fn(() => of(list({ items: [RUNNING] }))),
        getBackup,
      });
      const toast = { success: jest.fn(), error: jest.fn(), show: jest.fn() };
      const view = await render(BackupsComponent, {
        providers: [
          { provide: AdminApiService, useValue: api },
          { provide: ToastService, useValue: toast },
        ],
      });
      jest.advanceTimersByTime(31 * 60 * 1000);
      getBackup.mockClear();
      jest.advanceTimersByTime(9000);
      expect(getBackup).not.toHaveBeenCalled();
      view.fixture.destroy();
    });

    it('stops polling when a poll request fails', async () => {
      jest.useFakeTimers();
      const getBackup = jest.fn(() => throwError(() => new Error('500')));
      const api = makeApi({
        listBackups: jest.fn(() => of(list({ items: [RUNNING] }))),
        getBackup,
      });
      const toast = { success: jest.fn(), error: jest.fn(), show: jest.fn() };
      const view = await render(BackupsComponent, {
        providers: [
          { provide: AdminApiService, useValue: api },
          { provide: ToastService, useValue: toast },
        ],
      });
      jest.advanceTimersByTime(3000);
      getBackup.mockClear();
      jest.advanceTimersByTime(9000);
      expect(getBackup).not.toHaveBeenCalled();
      view.fixture.destroy();
    });
  });
});
