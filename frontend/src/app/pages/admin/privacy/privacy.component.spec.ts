import { of, throwError } from 'rxjs';
import { provideRouter, Router } from '@angular/router';
import { render, screen, fireEvent } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import type { AdminPrincipal, ErasureRequest, PrivacySettings } from '../admin.models';
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

const ANNA: AdminPrincipal = {
  id: 'p-7',
  sub: 'kc|anna',
  email: 'anna@x',
  displayName: 'Anna Alt',
  lastLogin: null,
  active: true,
  oidcGroups: [],
  assignments: [],
} as unknown as AdminPrincipal;
const NAMELESS: AdminPrincipal = {
  ...ANNA,
  id: 'p-8',
  sub: 'kc|nameless',
  email: null,
  displayName: null,
} as unknown as AdminPrincipal;
const MERGED: AdminPrincipal = {
  ...ANNA,
  id: 'p-9',
  sub: 'kc|merged',
  mergedIntoId: 'p-7',
} as unknown as AdminPrincipal;

interface ApiOverrides {
  listPrincipals?: jest.Mock;
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
    listPrincipals: o.listPrincipals ?? jest.fn(() => of([ANNA, NAMELESS, MERGED])),
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

async function setup(api = makeApi(), url = '/') {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(PrivacyComponent, {
    providers: [
      provideRouter([{ path: '**', children: [] }]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  if (url !== '/') {
    await view.fixture.ngZone!.run(() => view.fixture.debugElement.injector.get(Router).navigateByUrl(url));
  }
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

describe('PrivacyComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the erasure queue and retention default on init', async () => {
    const { api } = await setup();
    expect(api.listErasures).toHaveBeenCalled();
    expect(api.getPrivacySettings).toHaveBeenCalled();
    expect(screen.getByText('a@x')).toBeInTheDocument();
    // The executed row has no email any more: it reads "anonymisiert".
    expect(screen.getByText('anonymisiert')).toBeInTheDocument();
    // The retention input shows the loaded default.
    expect(screen.getByDisplayValue('24')).toBeInTheDocument();
  });

  it('shows a dash for an open request without an e-mail address', async () => {
    const api = makeApi({ listErasures: jest.fn(() => of([{ ...OPEN, email: null }])) });
    await setup(api);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('anonymisiert')).toBeNull();
  });

  it('translates status and subject labels and renders the localized columns', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance as unknown as {
      subjectLabel: (s: string) => string;
      columns: () => { key: string }[];
    };
    // The status is coloured text: an open request waits (warn).
    const open = screen.getByText('Offen');
    expect(open.closest('app-status-text')).toHaveClass('st--warn');
    expect(cmp.subjectLabel('applicant')).toBeTruthy();
    expect(cmp.columns().map((c) => c.key)).toEqual([
      'status',
      'subjectType',
      'email',
      'createdAt',
      'actions',
    ]);
  });

  it('executes an open erasure after confirmation and reloads', async () => {
    const api = makeApi();
    const { toast } = await setup(api);
    await userEvent.click(screen.getAllByRole('button', { name: /^Ausführen: / })[0]);
    const confirm = screen.getAllByRole('button', { name: 'Ausführen' });
    await userEvent.click(confirm[confirm.length - 1]);
    expect(api.executeErasure).toHaveBeenCalledWith('er-1');
    expect(toast.success).toHaveBeenCalled();
    // The queue loads once on init and once after the execute.
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
    // A failure does not reload the queue, so only the init call counts.
    expect(api.listErasures).toHaveBeenCalledTimes(1);
  });

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

  it('does nothing when asking to erase without a picked person', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance as unknown as {
      askPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.askPrincipalErase();
    expect(cmp.confirmPrincipal()).toBe(false);
    expect(screen.getByRole('button', { name: 'Konto löschen' })).toBeDisabled();
  });

  it('picks the person by name or e-mail, never by a raw id (D1)', async () => {
    jest.useFakeTimers({ advanceTimers: true });
    const { api, fixture } = await setup();
    expect(screen.queryByLabelText(/UUID/)).toBeNull();
    await userEvent.type(screen.getByRole('searchbox', { name: /Person suchen/ }), 'an');
    jest.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(api.listPrincipals).toHaveBeenCalledWith('an');
    // A merged account is a locked reference and is not offered; a nameless one reads "Ohne Namen".
    const hits = screen.getByRole('list', { name: 'Gefundene Konten' });
    expect(hits.querySelectorAll('button')).toHaveLength(2);
    expect(screen.getByText('Ohne Namen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Anna Alt/ }));
    fixture.detectChanges();
    expect(screen.queryByRole('list', { name: 'Gefundene Konten' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Konto löschen' }));
    fixture.detectChanges();
    // The confirmation names the person, not an id.
    expect(screen.getAllByText('Anna Alt').length).toBeGreaterThan(1);
    expect(screen.queryByText('p-7')).toBeNull();
    jest.useRealTimers();
  });

  it('shows the sub as a tooltip only for a nameless person (D7)', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance as unknown as { pickPerson: (p: AdminPrincipal) => void };
    cmp.pickPerson(ANNA);
    fixture.detectChanges();
    expect(screen.getByText('Anna Alt')).not.toHaveAttribute('title');
    cmp.pickPerson(NAMELESS);
    fixture.detectChanges();
    expect(screen.getByText('Ohne Namen')).toHaveAttribute('title', 'kc|nameless');
  });

  it('can change the picked person', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance as unknown as {
      pickPerson: (p: AdminPrincipal) => void;
      person: () => AdminPrincipal | null;
    };
    cmp.pickPerson(ANNA);
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Ändern' }));
    expect(cmp.person()).toBeNull();
  });

  it('preselects the person from ?person=<sub> (the row action in Benutzer)', async () => {
    const { api, fixture } = await setup(makeApi(), '/admin/privacy?person=kc%7Canna');
    const cmp = fixture.componentInstance as unknown as { person: () => AdminPrincipal | null };
    expect(api.listPrincipals).toHaveBeenCalledWith('kc|anna');
    expect(cmp.person()?.id).toBe('p-7');
  });

  it('ignores a ?person=<sub> without an exact match', async () => {
    const { fixture } = await setup(makeApi(), '/admin/privacy?person=kc%7Cnobody');
    expect((fixture.componentInstance as unknown as { person: () => unknown }).person()).toBeNull();
  });

  it('ignores a ?person=<sub> when the lookup fails', async () => {
    const failing = makeApi({ listPrincipals: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture } = await setup(failing, '/admin/privacy?person=kc%7Canna');
    expect((fixture.componentInstance as unknown as { person: () => unknown }).person()).toBeNull();
  });

  it('empties the hits when the search fails or is cleared', async () => {
    const { fixture } = await setup(
      makeApi({ listPrincipals: jest.fn(() => throwError(() => new Error('x'))) }),
    );
    const cmp = fixture.componentInstance as unknown as {
      personSearch: { set: (v: string) => void; flush: () => void; clear: () => void };
      personHits: () => AdminPrincipal[];
    };
    cmp.personSearch.set('anna');
    cmp.personSearch.flush();
    expect(cmp.personHits()).toEqual([]);
    cmp.personSearch.clear();
    expect(cmp.personHits()).toEqual([]);
  });

  it('doPrincipalErase is a no-op without a picked person', async () => {
    const api = makeApi();
    const { fixture } = await setup(api);
    (
      fixture.componentInstance as unknown as { doPrincipalErase: () => void }
    ).doPrincipalErase();
    expect(api.erasePrincipal).not.toHaveBeenCalled();
  });

  it('erases the principal, clears the pick and closes the dialog', async () => {
    const api = makeApi();
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      pickPerson: (p: AdminPrincipal) => void;
      person: () => AdminPrincipal | null;
      askPrincipalErase: () => void;
      doPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.pickPerson(ANNA);
    cmp.askPrincipalErase();
    expect(cmp.confirmPrincipal()).toBe(true);
    cmp.doPrincipalErase();
    expect(api.erasePrincipal).toHaveBeenCalledWith('p-7');
    expect(cmp.person()).toBeNull();
    expect(cmp.confirmPrincipal()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('on principal-erase error closes the dialog and toasts an error', async () => {
    const api = makeApi({ erasePrincipal: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture, toast } = await setup(api);
    const cmp = fixture.componentInstance as unknown as {
      pickPerson: (p: AdminPrincipal) => void;
      doPrincipalErase: () => void;
      confirmPrincipal: () => boolean;
    };
    cmp.pickPerson(ANNA);
    cmp.doPrincipalErase();
    expect(cmp.confirmPrincipal()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });

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

  it('names the request in each row button and leaves a closed row without actions', async () => {
    const { container } = await setup();
    expect(screen.getByRole('button', { name: 'Ablehnen: a@x' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ausführen: a@x' })).toBeInTheDocument();
    // The done row renders nothing in its actions cell, so the card leaves the label out.
    const cells = [...container.querySelectorAll('td[data-label="Aktionen"]')];
    expect(cells).toHaveLength(2);
    expect(cells[1].children).toHaveLength(0);
    expect(container.querySelector('.dt--rowgroup')).not.toBeNull();
  });

  it('wires the reject action button click through the queue row', async () => {
    // This covers the rendered template and the openReject path that opens the dialog.
    const { container } = await setup();
    fireEvent.click(screen.getByRole('button', { name: /^Ablehnen: / }));
    expect(container.querySelector('textarea')).toBeInTheDocument();
  });

  it('stops loading when the list fails, rather than spinning forever', async () => {
    const api = makeApi({ listErasures: jest.fn(() => throwError(() => new Error('boom'))) });
    const { fixture } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((fixture.componentInstance as any).loading()).toBe(false);
  });
});
