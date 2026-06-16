import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@shared/ui/toast/toast.service';
import type { AttachmentOutWire } from '@core/api/models';

const APP_ID = 'app-1';

function wire(over: Partial<AttachmentOutWire> = {}): AttachmentOutWire {
  return {
    id: 'att-1',
    filename: 'plan.pdf',
    mime: 'application/pdf',
    size: 2048,
    scanned: false,
    is_comparison_offer: false,
    ...over,
  };
}

async function setup(canUpload = true) {
  const view = await render(AttachmentsPanelComponent, {
    inputs: { applicationId: APP_ID, canUpload },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  // Hydration-GET (bestehende Anhänge) beim Init leeren.
  http
    .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
    .flush([]);
  return { ...view, http, toast };
}

const uploadUrl = (r: { url: string }) => r.url === `/api/applications/${APP_ID}/attachments`;
const dlUrl = (id: string) => (r: { url: string }) => r.url === `/api/attachments/${id}`;

async function uploadFile(name = 'plan.pdf') {
  const input = screen.getByLabelText('Datei hochladen') as HTMLInputElement;
  await userEvent.upload(input, new File(['x'], name, { type: 'application/pdf' }));
}

describe('AttachmentsPanelComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the empty state and no upload control without permission', async () => {
    await setup(false);
    expect(screen.getByText('Noch keine Anhänge hochgeladen.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Datei hochladen')).not.toBeInTheDocument();
  });

  it('uploads a file and lists it as "scanning" (download disabled)', async () => {
    const { http, detectChanges, toast } = await setup();
    const success = jest.spyOn(toast, 'success');
    await uploadFile();

    const req = http.expectOne(uploadUrl);
    expect(req.request.method).toBe('POST');
    expect(req.request.body instanceof FormData).toBe(true);
    req.flush(wire(), { status: 201, statusText: 'Created' });
    detectChanges();

    expect(screen.getByText('plan.pdf')).toBeInTheDocument();
    expect(screen.getByText('2.0 KB')).toBeInTheDocument();
    expect(screen.getByText('In Prüfung')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Herunterladen' })).toBeDisabled();
    expect(success).toHaveBeenCalled();
    http.verify();
  });

  it('deletes an attachment via DELETE and drops it from the list', async () => {
    const { http, detectChanges, toast } = await setup();
    const success = jest.spyOn(toast, 'success');
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire(), { status: 201, statusText: 'Created' });
    detectChanges();
    expect(screen.getByText('plan.pdf')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Anhang löschen' }));
    const del = http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/att-1');
    del.flush(null, { status: 204, statusText: 'No Content' });
    detectChanges();

    expect(screen.queryByText('plan.pdf')).not.toBeInTheDocument();
    expect(success).toHaveBeenCalled();
    http.verify();
  });

  it('enables download for a scanned (clean) attachment and opens the signed URL', async () => {
    const { http, detectChanges, fixture } = await setup();
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();

    const open = jest
      .spyOn(fixture.componentInstance as unknown as { openUrl: (u: string) => void }, 'openUrl')
      .mockImplementation(() => {});
    expect(screen.getByText('Gescannt')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Herunterladen' }));

    const req = http.expectOne(dlUrl('att-1'));
    expect(req.request.method).toBe('GET');
    req.flush({ url: 'https://minio/att-1?sig=ok', expiresIn: 120 });
    expect(open).toHaveBeenCalledWith('https://minio/att-1?sig=ok');
    http.verify();
  });

  it('marks an attachment quarantined and toasts on a 409 download', async () => {
    const { http, detectChanges, toast } = await setup();
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.click(screen.getByRole('button', { name: 'Herunterladen' }));
    http
      .expectOne(dlUrl('att-1'))
      .flush({ title: 'Conflict' }, { status: 409, statusText: 'Conflict' });
    detectChanges();

    expect(screen.getByText('Quarantäne')).toBeInTheDocument();
    expect(error).toHaveBeenCalledWith(
      'Noch nicht freigegeben — Prüfung läuft oder Datei in Quarantäne.',
    );
    // download now disabled (state != clean)
    expect(screen.getByRole('button', { name: 'Herunterladen' })).toBeDisabled();
    http.verify();
  });

  it('quarantines only the failing attachment, leaving siblings untouched (409)', async () => {
    const { http, detectChanges, fixture } = await setup();
    const cmp = fixture.componentInstance;
    await uploadFile('a.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'a', filename: 'a.pdf', scanned: true }), {
      status: 201,
      statusText: 'Created',
    });
    await uploadFile('b.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'b', filename: 'b.pdf', scanned: true }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();

    cmp.download(wire({ id: 'a', filename: 'a.pdf', scanned: true }) as never);
    http.expectOne(dlUrl('a')).flush({ title: 'Conflict' }, { status: 409, statusText: 'Conflict' });
    detectChanges();

    const byId = new Map(cmp.attachments().map((x) => [x.id, x.scanState]));
    expect(byId.get('a')).toBe('quarantined');
    // sibling 'b' takes the `: a` (unchanged) branch of the map
    expect(byId.get('b')).toBe('clean');
    http.verify();
  });

  it('toasts an expired-link message on a 410 download', async () => {
    const { http, detectChanges, toast } = await setup();
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.click(screen.getByRole('button', { name: 'Herunterladen' }));
    http.expectOne(dlUrl('att-1')).flush({ title: 'Gone' }, { status: 410, statusText: 'Gone' });

    expect(error).toHaveBeenCalledWith('Download-Link abgelaufen. Bitte erneut versuchen.');
    http.verify();
  });

  it.each([
    [413, 'Datei zu groß (max. 10 MB).'],
    [415, 'Dateityp nicht erlaubt.'],
    [429, 'Zu viele Uploads. Bitte später erneut versuchen.'],
    [503, 'Speicher derzeit nicht verfügbar.'],
    [500, 'Upload fehlgeschlagen.'],
    [undefined, 'Upload fehlgeschlagen.'],
  ])('maps upload error %s to its toast', async (status, message) => {
    const { http, toast } = await setup();
    const error = jest.spyOn(toast, 'error');
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush({ title: 'e' }, { status: status ?? 0, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    http.verify();
  });

  it('hydrates from the list endpoint and tolerates a list error', async () => {
    const view = await render(AttachmentsPanelComponent, {
      inputs: { applicationId: APP_ID, canUpload: true },
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush([wire({ id: 'pre', filename: 'pre.pdf', scanned: true })]);
    view.detectChanges();
    expect(screen.getByText('pre.pdf')).toBeInTheDocument();
    expect(view.fixture.componentInstance.attachments()).toHaveLength(1);
    http.verify();
  });

  it('tolerates a list-endpoint error on hydration (stays empty)', async () => {
    const view = await render(AttachmentsPanelComponent, {
      inputs: { applicationId: APP_ID, canUpload: true },
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    view.detectChanges();
    expect(view.fixture.componentInstance.attachments()).toEqual([]);
    expect(screen.getByText('Noch keine Anhänge hochgeladen.')).toBeInTheDocument();
    http.verify();
  });

  it('does nothing on file-select with no files (input value reset)', async () => {
    const { http, fixture } = await setup();
    const cmp = fixture.componentInstance;
    const input = document.createElement('input');
    input.type = 'file';
    cmp.onFileSelected({ target: input } as unknown as Event);
    expect(cmp.uploading()).toBe(false);
    expect(input.value).toBe('');
    http.verify();
  });

  it('guards against a concurrent upload while one is in flight', async () => {
    const { http, fixture } = await setup();
    const cmp = fixture.componentInstance;
    cmp.uploading.set(true);
    cmp['upload']([new File(['x'], 'a.pdf', { type: 'application/pdf' })]);
    // still flagged; no POST emitted (verified)
    expect(cmp.uploading()).toBe(true);
    http.verify();
  });

  it('uploads several files sequentially (concatMap) and toasts once', async () => {
    const { http, detectChanges, toast } = await setup();
    const success = jest.spyOn(toast, 'success');
    const input = screen.getByLabelText('Datei hochladen') as HTMLInputElement;
    await userEvent.upload(input, [
      new File(['a'], 'a.pdf', { type: 'application/pdf' }),
      new File(['b'], 'b.pdf', { type: 'application/pdf' }),
    ]);

    // first request only (concatMap holds the second until the first completes)
    const first = http.expectOne(uploadUrl);
    first.flush(wire({ id: 'att-a', filename: 'a.pdf' }), { status: 201, statusText: 'Created' });
    const second = http.expectOne(uploadUrl);
    second.flush(wire({ id: 'att-b', filename: 'b.pdf' }), { status: 201, statusText: 'Created' });
    detectChanges();

    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(screen.getByText('b.pdf')).toBeInTheDocument();
    expect(success).toHaveBeenCalledTimes(1);
    http.verify();
  });

  it('toasts both success and error when some files uploaded before a failure', async () => {
    const { http, detectChanges, toast } = await setup();
    const success = jest.spyOn(toast, 'success');
    const error = jest.spyOn(toast, 'error');
    const input = screen.getByLabelText('Datei hochladen') as HTMLInputElement;
    await userEvent.upload(input, [
      new File(['a'], 'a.pdf', { type: 'application/pdf' }),
      new File(['b'], 'b.pdf', { type: 'application/pdf' }),
    ]);

    http.expectOne(uploadUrl).flush(wire({ id: 'att-a', filename: 'a.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    http.expectOne(uploadUrl).flush({ title: 'e' }, { status: 413, statusText: 'Too Large' });
    detectChanges();

    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(success).toHaveBeenCalledWith('Anhang hochgeladen — Prüfung läuft.');
    expect(error).toHaveBeenCalledWith('Datei zu groß (max. 10 MB).');
    http.verify();
  });

  it('toasts the generic download error on a non-409/410 failure', async () => {
    const { http, detectChanges, toast } = await setup();
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.click(screen.getByRole('button', { name: 'Herunterladen' }));
    http.expectOne(dlUrl('att-1')).flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    expect(error).toHaveBeenCalledWith('Download fehlgeschlagen.');
    http.verify();
  });

  it('guards against a concurrent download while one is in flight', async () => {
    const { http, detectChanges, fixture } = await setup();
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();
    const cmp = fixture.componentInstance;
    cmp.downloadingId.set('other');
    cmp.download(wire({ scanned: true }) as never);
    expect(cmp.downloadingId()).toBe('other');
    http.verify();
  });

  it('toasts an error when a single remove fails (id cleared)', async () => {
    const { http, detectChanges, toast, fixture } = await setup();
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire(), { status: 201, statusText: 'Created' });
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.click(screen.getByRole('button', { name: 'Anhang löschen' }));
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/att-1')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    detectChanges();

    expect(error).toHaveBeenCalledWith('Anhang konnte nicht gelöscht werden.');
    expect(screen.getByText('plan.pdf')).toBeInTheDocument();
    expect(fixture.componentInstance.removingId()).toBeNull();
    http.verify();
  });

  it('guards against a concurrent remove while one is in flight', async () => {
    const { http, fixture } = await setup();
    const cmp = fixture.componentInstance;
    cmp.removingId.set('other');
    cmp.remove(wire() as never);
    expect(cmp.removingId()).toBe('other');
    http.verify();
  });

  it('opens the signed URL via window.open in a new tab', async () => {
    const { http, detectChanges } = await setup();
    await uploadFile();
    http
      .expectOne(uploadUrl)
      .flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();
    const open = jest.spyOn(window, 'open').mockReturnValue(null);

    await userEvent.click(screen.getByRole('button', { name: 'Herunterladen' }));
    http.expectOne(dlUrl('att-1')).flush({ url: 'https://minio/x?sig=1', expiresIn: 60 });

    expect(open).toHaveBeenCalledWith('https://minio/x?sig=1', '_blank', 'noopener');
    open.mockRestore();
    http.verify();
  });

  it('formats size and resolves scan labels by state', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance;
    expect(cmp.size(wire({ size: 2048 }) as never)).toBe('2.0 KB');
    expect(cmp.scanLabel('clean')).toBe('applications.attachments.scan.clean');
    expect(cmp.scanLabel('quarantined')).toBe('applications.attachments.scan.quarantined');
  });

  // --- bulk-select --------------------------------------------------------
  it('tracks per-row selection, select-all and the selected count', async () => {
    const { http, detectChanges, fixture } = await setup();
    const cmp = fixture.componentInstance;
    await uploadFile('a.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'a', filename: 'a.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    await uploadFile('b.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'b', filename: 'b.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();

    expect(cmp.allSelected()).toBe(false);
    expect(cmp.selectedCount()).toBe(0);

    cmp.toggleSelect('a', true);
    expect(cmp.isSelected('a')).toBe(true);
    expect(cmp.selectedCount()).toBe(1);
    expect(cmp.allSelected()).toBe(false);

    cmp.toggleSelect('a', false);
    expect(cmp.isSelected('a')).toBe(false);

    cmp.toggleSelectAll(true);
    expect(cmp.selectedCount()).toBe(2);
    expect(cmp.allSelected()).toBe(true);

    cmp.toggleSelectAll(false);
    expect(cmp.selectedCount()).toBe(0);
    http.verify();
  });

  it('allSelected is false for an empty list', async () => {
    const { fixture } = await setup();
    expect(fixture.componentInstance.allSelected()).toBe(false);
  });

  it('bulk-deletes selected attachments and clears them from the list', async () => {
    const { http, detectChanges, toast, fixture } = await setup();
    const cmp = fixture.componentInstance;
    const success = jest.spyOn(toast, 'success');
    await uploadFile('a.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'a', filename: 'a.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    await uploadFile('b.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'b', filename: 'b.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();

    cmp.toggleSelectAll(true);
    cmp.bulkDelete();
    // sequential DELETEs (concatMap)
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/a').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/b').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    // refreshAfterBulk re-lists the attachments
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush([]);
    detectChanges();

    expect(cmp.bulkDeleting()).toBe(false);
    expect(cmp.attachments()).toEqual([]);
    expect(cmp.selectedCount()).toBe(0);
    expect(success).toHaveBeenCalledWith('Anhang gelöscht.');
    http.verify();
  });

  it('no-ops bulkDelete with an empty selection or while already running', async () => {
    const { http, fixture } = await setup();
    const cmp = fixture.componentInstance;
    cmp.bulkDelete();
    expect(cmp.bulkDeleting()).toBe(false);

    cmp.selected.set(new Set(['x']));
    cmp.bulkDeleting.set(true);
    cmp.bulkDelete();
    expect(cmp.bulkDeleting()).toBe(true);
    http.verify();
  });

  it('keeps remaining selections on a partial bulk-delete failure (list reload succeeds)', async () => {
    const { http, detectChanges, toast, fixture } = await setup();
    const cmp = fixture.componentInstance;
    const error = jest.spyOn(toast, 'error');
    await uploadFile('a.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'a', filename: 'a.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    await uploadFile('b.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'b', filename: 'b.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();

    cmp.toggleSelectAll(true);
    cmp.bulkDelete();
    // first DELETE succeeds, second fails
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/a').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/b')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    // refreshAfterBulk re-lists: 'b' still present, 'a' gone
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush([wire({ id: 'b', filename: 'b.pdf' })]);
    detectChanges();

    expect(cmp.bulkDeleting()).toBe(false);
    expect(error).toHaveBeenCalledWith('Anhang konnte nicht gelöscht werden.');
    expect(cmp.attachments().map((a) => a.id)).toEqual(['b']);
    // 'b' stays selected so a retry is possible; 'a' dropped (no longer in list)
    expect(cmp.isSelected('b')).toBe(true);
    expect(cmp.isSelected('a')).toBe(false);
    http.verify();
  });

  it('falls back to local removal when the post-bulk list reload fails', async () => {
    const { http, detectChanges, fixture } = await setup();
    const cmp = fixture.componentInstance;
    await uploadFile('a.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'a', filename: 'a.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    await uploadFile('b.pdf');
    http.expectOne(uploadUrl).flush(wire({ id: 'b', filename: 'b.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();

    cmp.toggleSelect('a', true);
    cmp.bulkDelete();
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/a').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    // list reload fails → local removal of attempted ids
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    detectChanges();

    expect(cmp.attachments().map((a) => a.id)).toEqual(['b']);
    expect(cmp.isSelected('a')).toBe(false);
    http.verify();
  });

  // --- drag & drop --------------------------------------------------------
  function dragEvent(types: string[], files: File[] = []): DragEvent {
    return {
      preventDefault: jest.fn(),
      dataTransfer: { types, files },
    } as unknown as DragEvent;
  }

  it('activates the drop overlay on dragenter with files and hides it on leave', async () => {
    const { detectChanges, fixture } = await setup();
    const cmp = fixture.componentInstance;
    const enter = dragEvent(['Files']);
    cmp.onDragEnter(enter);
    expect(enter.preventDefault).toHaveBeenCalled();
    expect(cmp.dragActive()).toBe(true);
    detectChanges();
    expect(screen.getByText('Dateien zum Hochladen ablegen')).toBeInTheDocument();

    const over = dragEvent(['Files']);
    cmp.onDragOver(over);
    expect(over.preventDefault).toHaveBeenCalled();

    const leave = dragEvent(['Files']);
    cmp.onDragLeave(leave);
    expect(cmp.dragActive()).toBe(false);
  });

  it('counts nested enter/leave so the overlay does not flicker', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance;
    cmp.onDragEnter(dragEvent(['Files'])); // depth 1
    cmp.onDragEnter(dragEvent(['Files'])); // depth 2
    expect(cmp.dragActive()).toBe(true);
    cmp.onDragLeave(dragEvent(['Files'])); // depth 1 → still active
    expect(cmp.dragActive()).toBe(true);
    cmp.onDragLeave(dragEvent(['Files'])); // depth 0 → inactive
    expect(cmp.dragActive()).toBe(false);
  });

  it('ignores drag events without upload permission or without files', async () => {
    const { fixture } = await setup(false);
    const cmp = fixture.componentInstance;
    const noPerm = dragEvent(['Files']);
    cmp.onDragEnter(noPerm);
    expect(noPerm.preventDefault).not.toHaveBeenCalled();
    expect(cmp.dragActive()).toBe(false);
    cmp.onDragOver(noPerm);
    expect(noPerm.preventDefault).not.toHaveBeenCalled();
  });

  it('ignores dragenter/over when the payload carries no files', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance;
    const noFiles = dragEvent(['text/plain']);
    cmp.onDragEnter(noFiles);
    expect(cmp.dragActive()).toBe(false);
    expect(noFiles.preventDefault).not.toHaveBeenCalled();
    cmp.onDragOver(noFiles);
    expect(noFiles.preventDefault).not.toHaveBeenCalled();
  });

  it('ignores dragleave when no drag is active', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance;
    const leave = dragEvent(['Files']);
    cmp.onDragLeave(leave);
    expect(leave.preventDefault).not.toHaveBeenCalled();
    expect(cmp.dragActive()).toBe(false);
  });

  it('uploads files dropped onto the panel (active drop)', async () => {
    const { http, detectChanges, fixture } = await setup();
    const cmp = fixture.componentInstance;
    cmp.onDragEnter(dragEvent(['Files']));
    expect(cmp.dragActive()).toBe(true);

    const dropped = new File(['x'], 'drop.pdf', { type: 'application/pdf' });
    const drop = dragEvent(['Files'], [dropped]);
    cmp.onDrop(drop);
    expect(drop.preventDefault).toHaveBeenCalled();
    expect(cmp.dragActive()).toBe(false);

    http.expectOne(uploadUrl).flush(wire({ id: 'd', filename: 'drop.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();
    expect(screen.getByText('drop.pdf')).toBeInTheDocument();
    http.verify();
  });

  it('ignores a drop without upload permission', async () => {
    const { http, fixture } = await setup(false);
    const cmp = fixture.componentInstance;
    const drop = dragEvent(['Files'], [new File(['x'], 'd.pdf', { type: 'application/pdf' })]);
    cmp.onDrop(drop);
    expect(drop.preventDefault).not.toHaveBeenCalled();
    http.verify();
  });

  it('resets the drop overlay even when no files are dropped', async () => {
    const { http, fixture } = await setup();
    const cmp = fixture.componentInstance;
    cmp.onDragEnter(dragEvent(['Files']));
    const drop = dragEvent(['Files'], []);
    cmp.onDrop(drop);
    expect(drop.preventDefault).toHaveBeenCalled();
    expect(cmp.dragActive()).toBe(false);
    http.verify();
  });

  it('handles a drop / dragenter with no dataTransfer (?? [] fallback)', async () => {
    const { http, fixture } = await setup();
    const cmp = fixture.componentInstance;
    const noDt = { preventDefault: jest.fn(), dataTransfer: null } as unknown as DragEvent;
    // hasFiles → types ?? [] → false, so dragenter bails before preventDefault
    cmp.onDragEnter(noDt);
    expect(cmp.dragActive()).toBe(false);
    // onDrop reaches the files ?? [] fallback → empty → no upload
    cmp.onDrop(noDt);
    expect(noDt.preventDefault).toHaveBeenCalled();
    expect(cmp.dragActive()).toBe(false);
    http.verify();
  });
});
