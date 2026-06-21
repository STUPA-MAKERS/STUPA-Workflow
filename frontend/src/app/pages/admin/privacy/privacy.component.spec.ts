import { of, throwError } from 'rxjs';
import { render, screen, fireEvent } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import type { ErasureRequest, PrivacySettings } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { PrivacyComponent } from './privacy.component';

const OPEN: ErasureRequest = {
  id: 'er-1',
  createdAt: '2026-06-01T10:00:00Z',
  subjectType: 'applicant',
  email: 'a@x',
  status: 'open',
};
const DONE: ErasureRequest = {
  id: 'er-2',
  createdAt: '2026-06-02T10:00:00Z',
  subjectType: 'principal',
  email: null,
  status: 'executed',
};

interface ApiOverrides {
  listErasures?: jest.Mock;
  getPrivacySettings?: jest.Mock;
  executeErasure?: jest.Mock;
  rejectErasure?: jest.Mock;
  downloadAuskunft?: jest.Mock;
  erasePrincipal?: jest.Mock;
  putPrivacySettings?: jest.Mock;
}

function makeApi(o: ApiOverrides = {}) {
  return {
    listErasures: o.listErasures ?? jest.fn(() => of([OPEN, DONE])),
    getPrivacySettings:
      o.getPrivacySettings ?? jest.fn(() => of<PrivacySettings>({ defaultRetentionMonths: 24 })),
    executeErasure: o.executeErasure ?? jest.fn(() => of(OPEN)),
    rejectErasure: o.rejectErasure ?? jest.fn(() => of(OPEN)),
    downloadAuskunft:
      o.downloadAuskunft ?? jest.fn(() => of(new Blob(['x'], { type: 'application/octet-stream' }))),
    erasePrincipal: o.erasePrincipal ?? jest.fn(() => of(void 0)),
    putPrivacySettings:
      o.putPrivacySettings ??
      jest.fn((s: PrivacySettings) => of<PrivacySettings>({ ...s })),
  };
}

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(PrivacyComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

describe('PrivacyComponent (#PII-Re-Add)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the erasure queue and retention default on init', async () => {
    const { api } = await setup();
    expect(api.listErasures).toHaveBeenCalled();
    expect(api.getPrivacySettings).toHaveBeenCalled();
    // open + executed rows present; only the open one renders action buttons.
    expect(screen.getByText('a@x')).toBeInTheDocument();
    // executed row has no email → em dash placeholder.
    expect(screen.getByText('—')).toBeInTheDocument();
    // retention input reflects the loaded default.
    expect(screen.getByDisplayValue('24')).toBeInTheDocument();
  });

  it('translates status and subject labels and renders the localized columns', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance as unknown as {
      statusLabel: (s: string) => string;
      subjectLabel: (s: string) => string;
      columns: () => { key: string }[];
    };
    expect(cmp.statusLabel('open')).toContain('Offen');
    expect(cmp.subjectLabel('applicant')).toBeTruthy();
    expect(cmp.columns().map((c) => c.key)).toEqual([
      'status',
      'subjectType',
      'email',
      'createdAt',
      'actions',
    ]);
  });

  // ----------------------------------------------------------------- execute
  it('executes an open erasure after confirmation and reloads', async () => {
    const api = makeApi();
    const { toast } = await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Ausführen' }));
    // confirm dialog → execute.
    const confirm = screen.getAllByRole('button', { name: 'Ausführen' });
    await userEvent.click(confirm[confirm.length - 1]);
    expect(api.executeErasure).toHaveBeenCalledWith('er-1');
    expect(toast.success).toHaveBeenCalled();
    // reloaded the queue once on init + once after execute.
    expect(api.listErasures).toHaveBeenCalledTimes(2);
  });

  it('doExecute is a no-op when nothing is queued for execution', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    (fixture.componentInstance as unknown as { doExecute: () => void }).doExecute();
    expect(api.executeErasure).not.toHaveBeenCalled();
  });

  it('toasts an error when execute fails', async () => {
    const api = makeApi({ executeErasure: jest.fn(() => throwError(() => new Error('boom'))) });
    const { toast, fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      askExecute: (r: ErasureRequest) => void;
      doExecute: () => void;
    };
    cmp.askExecute(OPEN);
    cmp.doExecute();
    expect(toast.error).toHaveBeenCalled();
    // queue not reloaded on failure (only the init call).
    expect(api.listErasures).toHaveBeenCalledTimes(1);
  });

  // ------------------------------------------------------------------ reject
  it('rejects an erasure with a trimmed reason', async () => {
    const api = makeApi();
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      openReject: (r: ErasureRequest) => void;
      rejectReason: { set: (v: string) => void };
      doReject: () => void;
    };
    cmp.openReject(OPEN);
    cmp.rejectReason.set('  spam  ');
    cmp.doReject();
    expect(api.rejectErasure).toHaveBeenCalledWith('er-1', 'spam');
    expect(toast.success).toHaveBeenCalled();
  });

  it('rejects with null reason when the reason is blank', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      openReject: (r: ErasureRequest) => void;
      doReject: () => void;
    };
    cmp.openReject(OPEN);
    cmp.doReject();
    expect(api.rejectErasure).toHaveBeenCalledWith('er-1', null);
  });

  it('doReject is a no-op when nothing is being rejected', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    (fixture.componentInstance as unknown as { doReject: () => void }).doReject();
    expect(api.rejectErasure).not.toHaveBeenCalled();
  });

  it('toasts an error when reject fails', async () => {
    const api = makeApi({ rejectErasure: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      openReject: (r: ErasureRequest) => void;
      doReject: () => void;
    };
    cmp.openReject(OPEN);
    cmp.doReject();
    expect(toast.error).toHaveBeenCalled();
  });

  // --------------------------------------------------------------- auskunft
  it('does nothing when exporting with an empty email', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    (fixture.componentInstance as unknown as { exportAuskunft: () => void }).exportAuskunft();
    expect(api.downloadAuskunft).not.toHaveBeenCalled();
  });

  it('downloads the Auskunft XLSX and triggers a browser download', async () => {
    const createObjectURL = jest.fn(() => 'blob:url');
    const revokeObjectURL = jest.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const api = makeApi();
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      auskunftEmail: { set: (v: string) => void };
      exportAuskunft: () => void;
    };
    cmp.auskunftEmail.set('  user@x  ');
    cmp.exportAuskunft();
    expect(api.downloadAuskunft).toHaveBeenCalledWith('user@x');
    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:url');
    expect(toast.success).toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it('toasts an error when the Auskunft download fails', async () => {
    const api = makeApi({ downloadAuskunft: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      auskunftEmail: { set: (v: string) => void };
      exportAuskunft: () => void;
    };
    cmp.auskunftEmail.set('user@x');
    cmp.exportAuskunft();
    expect(toast.error).toHaveBeenCalled();
  });

  // ----------------------------------------------------- principal erasure
  it('does nothing when asking to erase a principal with empty id', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      askPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.askPrincipalErase();
    expect(cmp.confirmPrincipal()).toBe(false);
  });

  it('opens the confirm dialog when a principal id is set', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      principalId: { set: (v: string) => void };
      askPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.principalId.set('  p-1  ');
    cmp.askPrincipalErase();
    expect(cmp.confirmPrincipal()).toBe(true);
  });

  it('doPrincipalErase is a no-op when the id is blank', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    (
      fixture.componentInstance as unknown as { doPrincipalErase: () => void }
    ).doPrincipalErase();
    expect(api.erasePrincipal).not.toHaveBeenCalled();
  });

  it('erases the principal, clears the field and closes the dialog', async () => {
    const api = makeApi();
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      principalId: { set: (v: string) => void; (): string };
      askPrincipalErase: () => void;
      doPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.principalId.set(' p-7 ');
    cmp.askPrincipalErase();
    cmp.doPrincipalErase();
    expect(api.erasePrincipal).toHaveBeenCalledWith('p-7');
    expect(cmp.principalId()).toBe('');
    expect(cmp.confirmPrincipal()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('on principal-erase error closes the dialog and toasts an error', async () => {
    const api = makeApi({ erasePrincipal: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      principalId: { set: (v: string) => void };
      doPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.principalId.set('p-9');
    cmp.doPrincipalErase();
    expect(cmp.confirmPrincipal()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });

  // --------------------------------------------------------------- retention
  it('does nothing when saving a null retention', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      retentionMonths: { set: (v: number | null) => void };
      saveRetention: () => void;
    };
    cmp.retentionMonths.set(null);
    cmp.saveRetention();
    expect(api.putPrivacySettings).not.toHaveBeenCalled();
  });

  it('does nothing when saving a retention below 1', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      retentionMonths: { set: (v: number | null) => void };
      saveRetention: () => void;
    };
    cmp.retentionMonths.set(0);
    cmp.saveRetention();
    expect(api.putPrivacySettings).not.toHaveBeenCalled();
  });

  it('saves a valid retention and reflects the server echo', async () => {
    const api = makeApi({
      putPrivacySettings: jest.fn(() => of<PrivacySettings>({ defaultRetentionMonths: 36 })),
    });
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      retentionMonths: { set: (v: number | null) => void; (): number | null };
      saveRetention: () => void;
    };
    cmp.retentionMonths.set(36);
    cmp.saveRetention();
    expect(api.putPrivacySettings).toHaveBeenCalledWith({ defaultRetentionMonths: 36 });
    expect(cmp.retentionMonths()).toBe(36);
    expect(toast.success).toHaveBeenCalled();
  });

  it('toasts an error when saving the retention fails', async () => {
    const api = makeApi({ putPrivacySettings: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      retentionMonths: { set: (v: number | null) => void };
      saveRetention: () => void;
    };
    cmp.retentionMonths.set(12);
    cmp.saveRetention();
    expect(toast.error).toHaveBeenCalled();
  });

  it('wires the reject action button click through the queue row', async () => {
    // Smoke-tests the rendered template + openReject → dialog open path.
    const { container } = await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Ablehnen' }));
    expect(container.querySelector('textarea')).toBeInTheDocument();
  });
});
