import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import type { AttachmentOutWire } from '@core/api/models';

const APP_ID = 'app-1';

function wire(over: Partial<AttachmentOutWire> = {}): AttachmentOutWire {
  return {
    id: 'att-1',
    filename: 'plan.pdf',
    mime: 'application/pdf',
    size: 2048,
    scanned: false,
    ...over,
  };
}

async function setup(canUpload = true, canDelete?: boolean) {
  const view = await render(AttachmentsPanelComponent, {
    inputs: { applicationId: APP_ID, canUpload, canDelete },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  // Empty the hydration GET (existing attachments) on init.
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

  it('shows its heading, or keeps it for screen readers only in a titled sheet', async () => {
    const { rerender } = await setup(false);
    expect(screen.getByRole('heading', { name: 'Anhänge' })).not.toHaveClass('sr-only');
    await rerender({ inputs: { applicationId: APP_ID, canUpload: false, titled: false }, partialUpdate: true });
    expect(screen.getByRole('heading', { name: 'Anhänge' })).toHaveClass('sr-only');
  });

  it('shows a thumbnail for a clean image and the clip icon for other files', async () => {
    const view = await render(AttachmentsPanelComponent, {
      inputs: { applicationId: APP_ID, canUpload: false },
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http.expectOne(`/api/applications/${APP_ID}/attachments`).flush([
      wire({ id: 'img', filename: 'foto.png', mime: 'image/png', scanned: true }),
      wire({ id: 'scan', filename: 'neu.jpg', mime: 'image/jpeg', scanned: false }),
      wire({ id: 'pdf', filename: 'plan.pdf', scanned: true }),
    ]);
    view.detectChanges();
    const thumbs = [...document.querySelectorAll<HTMLImageElement>('.att__thumb img')];
    expect(thumbs.map((i) => i.getAttribute('src'))).toEqual(['/api/attachments/img/download?inline=1']);
    expect(document.querySelectorAll('.att__icon')).toHaveLength(2);
    http.verify();
  });

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
    expect(screen.getByText('2,0 KB')).toBeInTheDocument();
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

  it('uploads but offers no delete when canDelete is false (locked state)', async () => {
    const { http, detectChanges, fixture } = await setup(true, false);
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire(), { status: 201, statusText: 'Created' });
    detectChanges();

    expect(screen.getByText('plan.pdf')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anhang löschen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    // The guards also hold when a caller bypasses the template.
    const cmp = fixture.componentInstance;
    cmp.remove(cmp.attachments()[0]);
    cmp.toggleSelect('att-1', true);
    cmp.bulkDelete();
    http.expectNone((r) => r.method === 'DELETE');
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
    // The sibling 'b' takes the unchanged branch of the map.
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

    expect(error).toHaveBeenCalledWith('Der Link zum Herunterladen ist abgelaufen. Versuche es noch einmal.');
    http.verify();
  });

  it.each([
    [413, 'Datei zu groß (max. 10 MB).'],
    [415, 'Dateityp nicht erlaubt.'],
    [429, 'Zu viele Dateien hochgeladen. Versuche es später noch einmal.'],
    [503, 'Speicher derzeit nicht verfügbar.'],
    [500, 'Hochladen fehlgeschlagen.'],
    [undefined, 'Hochladen fehlgeschlagen.'],
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
    // The flag stays set. No POST goes out, which http.verify confirms.
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

    // Only the first request goes out. concatMap holds the second one back.
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
    expect(error).toHaveBeenCalledWith('Herunterladen fehlgeschlagen.');
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

  it('formats size and shows the scan state as status text', async () => {
    const { fixture } = await setup();
    const cmp = fixture.componentInstance;
    expect(cmp.size(wire({ size: 2048 }) as never)).toBe('2,0 KB');
    expect(cmp.scan('clean')).toEqual({ kind: 'neutral', key: 'applications.attachments.scan.clean' });
    expect(cmp.scan('quarantined').kind).toBe('error');
  });

  it('reports the number of attachments after the load and after each change', async () => {
    const counts: number[] = [];
    const view = await render(AttachmentsPanelComponent, {
      inputs: { applicationId: APP_ID, canUpload: true },
      on: { countChange: (n: number) => counts.push(n) },
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    // Nothing before the list arrived: "0" would be a claim, not a count.
    view.detectChanges();
    expect(counts).toEqual([]);
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush([wire({ id: 'a' }), wire({ id: 'b' })]);
    view.detectChanges();
    expect(counts).toEqual([2]);
    view.fixture.componentInstance.attachments.set([]);
    view.detectChanges();
    expect(counts).toEqual([2, 0]);
  });

  it('counts after a failed load too', async () => {
    const counts: number[] = [];
    const view = await render(AttachmentsPanelComponent, {
      inputs: { applicationId: APP_ID },
      on: { countChange: (n: number) => counts.push(n) },
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.url === `/api/applications/${APP_ID}/attachments`)
      .flush({}, { status: 500, statusText: 'x' });
    view.detectChanges();
    expect(counts).toEqual([0]);
  });

  // Bulk select
  it('tracks per-row selection and shows the bulk bar only with a selection', async () => {
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

    expect(cmp.selectedCount()).toBe(0);
    expect(screen.queryByRole('toolbar', { name: 'Auswahl' })).toBeNull();

    cmp.toggleSelect('a', true);
    detectChanges();
    expect(cmp.isSelected('a')).toBe(true);
    expect(cmp.selectedCount()).toBe(1);
    const bar = screen.getByRole('toolbar', { name: 'Auswahl' });
    expect(within(bar).getByRole('status')).toHaveTextContent('1 ausgewählt');
    expect(within(bar).getByRole('button', { name: 'Auswahl löschen' })).toBeInTheDocument();

    // The clear button of the bar drops the selection.
    await userEvent.click(within(bar).getByRole('button', { name: 'Auswahl aufheben' }));
    detectChanges();
    expect(cmp.selectedCount()).toBe(0);
    expect(screen.queryByRole('toolbar', { name: 'Auswahl' })).toBeNull();
    cmp.toggleSelect('a', true);

    cmp.toggleSelect('a', false);
    expect(cmp.isSelected('a')).toBe(false);

    cmp.toggleSelect('a', true);
    cmp.toggleSelect('b', true);
    expect(cmp.selectedCount()).toBe(2);
    http.verify();
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

    cmp.toggleSelect('a', true);
    cmp.toggleSelect('b', true);
    cmp.bulkDelete();
    // concatMap sends the DELETE requests one after the other.
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/a').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/b').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    // refreshAfterBulk lists the attachments again.
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

    cmp.toggleSelect('a', true);
    cmp.toggleSelect('b', true);
    cmp.bulkDelete();
    // The first DELETE succeeds and the second one fails.
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/a').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/attachments/b')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    // refreshAfterBulk lists again: 'b' is still there and 'a' is gone.
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush([wire({ id: 'b', filename: 'b.pdf' })]);
    detectChanges();

    expect(cmp.bulkDeleting()).toBe(false);
    expect(error).toHaveBeenCalledWith('Anhang konnte nicht gelöscht werden.');
    expect(cmp.attachments().map((a) => a.id)).toEqual(['b']);
    // 'b' stays selected for a retry. 'a' drops out because the list lost it.
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
    // The list reload fails, so the panel removes the attempted ids locally.
    http
      .expectOne((r) => r.method === 'GET' && r.url === `/api/applications/${APP_ID}/attachments`)
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    detectChanges();

    expect(cmp.attachments().map((a) => a.id)).toEqual(['b']);
    expect(cmp.isSelected('a')).toBe(false);
    http.verify();
  });

  // Drag and drop (the counting of `appFileDrop` has its own spec)
  const pdf = () => new File(['x'], 'drop.pdf', { type: 'application/pdf' });
  const panel = (container: Element) => container.querySelector('.att') as HTMLElement;

  it('shows the overlay while files hover and uploads a drop', async () => {
    const { http, detectChanges, container } = await setup();
    fireEvent.dragEnter(panel(container), { dataTransfer: { types: ['Files'] } });
    detectChanges();
    expect(screen.getByText('Dateien zum Hochladen ablegen')).toBeInTheDocument();

    fireEvent.drop(panel(container), { dataTransfer: { types: ['Files'], files: [pdf()] } });
    detectChanges();
    expect(screen.queryByText('Dateien zum Hochladen ablegen')).not.toBeInTheDocument();
    http.expectOne(uploadUrl).flush(wire({ id: 'd', filename: 'drop.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    detectChanges();
    expect(screen.getByText('drop.pdf')).toBeInTheDocument();
    http.verify();
  });

  it('takes no drop without upload permission', async () => {
    const { http, detectChanges, container } = await setup(false);
    const enter = fireEvent.dragEnter(panel(container), { dataTransfer: { types: ['Files'] } });
    expect(enter).toBe(true); // not prevented: the page keeps the drag
    detectChanges();
    expect(screen.queryByText('Dateien zum Hochladen ablegen')).not.toBeInTheDocument();
    fireEvent.drop(panel(container), { dataTransfer: { types: ['Files'], files: [pdf()] } });
    http.verify();
  });

  it('leaves the drop to the page without its own target, and uploads what the page hands it', async () => {
    const { http, detectChanges, container, fixture, rerender } = await setup();
    await rerender({
      inputs: { applicationId: APP_ID, canUpload: true, dropTarget: false },
      partialUpdate: true,
    });
    const enter = fireEvent.dragEnter(panel(container), { dataTransfer: { types: ['Files'] } });
    expect(enter).toBe(true);
    detectChanges();
    expect(screen.queryByText('Dateien zum Hochladen ablegen')).not.toBeInTheDocument();

    fixture.componentInstance.upload([pdf()]);
    http.expectOne(uploadUrl).flush(wire({ id: 'd', filename: 'drop.pdf' }), {
      status: 201,
      statusText: 'Created',
    });
    http.verify();
  });

  it('uploads nothing that a page hands it without upload permission', async () => {
    const { http, fixture } = await setup(false);
    fixture.componentInstance.upload([pdf()]);
    http.verify();
  });

  // Preview in the full-screen kit viewer
  it('offers a preview only for clean images/PDFs and opens the PDF in the viewer', async () => {
    const { http, detectChanges, fixture } = await setup();
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();

    const cmp = fixture.componentInstance;
    // canPreview accepts a clean PDF. It rejects a scanning file or a foreign mime type.
    expect(cmp.canPreview({ ...cmp.attachments()[0] })).toBe(true);
    expect(cmp.canPreview({ ...cmp.attachments()[0], scanState: 'scanning' })).toBe(false);
    expect(cmp.canPreview({ ...cmp.attachments()[0], mime: 'application/zip' })).toBe(false);
    expect(screen.queryByRole('dialog')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    const req = http.expectOne(dlUrl('att-1'));
    expect(req.request.method).toBe('GET');
    req.flush({ url: '/api/attachments/att-1/download?sig=ok', expiresIn: 120 });
    detectChanges();

    expect(cmp.viewerOpen()).toBe(true);
    const viewer = screen.getByRole('dialog', { name: 'plan.pdf' });
    // The `inline=1` flag keeps Content-Disposition inline. The file then renders
    // instead of downloading.
    const frame = viewer.querySelector('iframe[title="plan.pdf"]');
    expect(frame?.getAttribute('src')).toBe('/api/attachments/att-1/download?sig=ok&inline=1');
    // One file: no arrows.
    expect(within(viewer).queryByRole('button', { name: 'Nächste Datei' })).toBeNull();

    await userEvent.click(within(viewer).getByRole('button', { name: 'Vorschau schließen' }));
    detectChanges();
    expect(cmp.viewerOpen()).toBe(false);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(cmp.viewerItems()[0].url).toBe('');
    http.verify();
  });

  it('previews a clean image as <img> (no iframe)', async () => {
    const { http, detectChanges } = await setup();
    await uploadFile('foto.png');
    http
      .expectOne(uploadUrl)
      .flush(wire({ id: 'att-9', filename: 'foto.png', mime: 'image/png', scanned: true }), {
        status: 201,
        statusText: 'Created',
      });
    detectChanges();

    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    http.expectOne(dlUrl('att-9')).flush({ url: '/api/attachments/att-9/download', expiresIn: 120 });
    detectChanges();

    const viewer = screen.getByRole('dialog', { name: 'foto.png' });
    expect(within(viewer).getByAltText('foto.png')).toHaveAttribute(
      'src',
      '/api/attachments/att-9/download?inline=1',
    );
    expect(viewer.querySelector('iframe')).toBeNull();
    http.verify();
  });

  it('steps through the previewable files, fetching each URL when the viewer reaches it', async () => {
    const { http, detectChanges, fixture } = await setup();
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    const cmp = fixture.componentInstance;
    const pdfAtt = cmp.attachments()[0];
    cmp.attachments.set([
      pdfAtt,
      { ...pdfAtt, id: 'att-2', filename: 'liste.zip', mime: 'application/zip' },
      { ...pdfAtt, id: 'att-3', filename: 'neu.png', mime: 'image/png', scanState: 'scanning' },
      { ...pdfAtt, id: 'att-9', filename: 'foto.png', mime: 'image/png' },
    ]);
    detectChanges();
    const open = jest
      .spyOn(cmp as unknown as { openUrl: (u: string) => void }, 'openUrl')
      .mockImplementation(() => {});

    await userEvent.click(screen.getAllByRole('button', { name: 'Vorschau' })[1]);
    http.expectOne(dlUrl('att-9')).flush({ url: '/api/attachments/att-9/download', expiresIn: 120 });
    detectChanges();
    // Only the clean image and the clean PDF are in the viewer, in the order of the list.
    expect(cmp.viewerItems().map((i) => i.name)).toEqual(['plan.pdf', 'foto.png']);
    const viewer = screen.getByRole('dialog', { name: 'foto.png' });
    expect(within(viewer).getByRole('button', { name: 'Nächste Datei' })).toBeDisabled();

    await userEvent.click(within(viewer).getByRole('button', { name: 'Vorherige Datei' }));
    detectChanges();
    expect(screen.getByRole('dialog', { name: 'plan.pdf' })).toBeInTheDocument();
    // Until the URL arrives the viewer shows the loading state and no frame.
    expect(viewer.querySelector('iframe')).toBeNull();
    expect(within(viewer).getByRole('status')).toBeInTheDocument();
    const req = http.expectOne(dlUrl('att-1'));
    // A second visit before the answer sends no second request.
    cmp.onViewerIndex(0);
    req.flush({ url: '/api/attachments/att-1/download', expiresIn: 120 });
    detectChanges();
    expect(viewer.querySelector('iframe')?.getAttribute('src')).toBe(
      '/api/attachments/att-1/download?inline=1',
    );
    // Back to the image: its URL is known, so no request.
    cmp.onViewerIndex(1);
    detectChanges();

    // The bar downloads the file it shows.
    await userEvent.click(within(viewer).getByRole('button', { name: 'Herunterladen' }));
    http.expectOne(dlUrl('att-9')).flush({ url: '/api/attachments/att-9/download', expiresIn: 120 });
    expect(open).toHaveBeenCalledWith('/api/attachments/att-9/download');
    http.verify();
  });

  it('closes the viewer with the toast when the URL of the next file fails (409 quarantines it)', async () => {
    const { http, detectChanges, fixture, toast } = await setup();
    const error = jest.spyOn(toast, 'error');
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    const cmp = fixture.componentInstance;
    const pdfAtt = cmp.attachments()[0];
    cmp.attachments.set([pdfAtt, { ...pdfAtt, id: 'att-9', filename: 'foto.png', mime: 'image/png' }]);
    detectChanges();

    cmp.openPreview(pdfAtt);
    http.expectOne(dlUrl('att-1')).flush({ url: '/api/attachments/att-1/download', expiresIn: 120 });
    detectChanges();
    cmp.onViewerIndex(1);
    http.expectOne(dlUrl('att-9')).flush({}, { status: 409, statusText: 'Conflict' });
    detectChanges();
    expect(cmp.viewerOpen()).toBe(false);
    expect(cmp.attachments()[1].scanState).toBe('quarantined');
    expect(error).toHaveBeenCalledTimes(1);

    // A late answer after the viewer closed changes nothing.
    cmp.openPreview(pdfAtt);
    http.expectOne(dlUrl('att-1')).flush({ url: '/api/attachments/att-1/download', expiresIn: 120 });
    cmp.attachments.update((list) => [...list, { ...pdfAtt, id: 'att-5', filename: 'b.png', mime: 'image/png' }]);
    cmp.onViewerIndex(1);
    const late = http.expectOne(dlUrl('att-5'));
    cmp.closePreview();
    late.flush({}, { status: 410, statusText: 'Gone' });
    expect(error).toHaveBeenCalledTimes(1);
    cmp.openPreview(pdfAtt);
    http.expectOne(dlUrl('att-1')).flush({ url: '/api/attachments/att-1/download', expiresIn: 120 });
    cmp.onViewerIndex(1);
    const ok = http.expectOne(dlUrl('att-5'));
    cmp.closePreview();
    ok.flush({ url: '/api/attachments/att-5/download', expiresIn: 120 });
    expect(cmp.viewerItems().every((i) => i.url === '')).toBe(true);
    http.verify();
  });

  it('opens PDFs in the system viewer on coarse-pointer devices (images only in the viewer)', async () => {
    const { http, detectChanges, fixture } = await setup();
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    const cmp = fixture.componentInstance;
    const pdfAtt = cmp.attachments()[0];
    cmp.attachments.set([pdfAtt, { ...pdfAtt, id: 'att-9', filename: 'foto.png', mime: 'image/png' }]);
    detectChanges();
    jest
      .spyOn(cmp as unknown as { coarsePointer: () => boolean }, 'coarsePointer')
      .mockReturnValue(true);
    const open = jest
      .spyOn(cmp as unknown as { openUrl: (u: string) => void }, 'openUrl')
      .mockImplementation(() => {});

    cmp.openPreview(pdfAtt);
    http.expectOne(dlUrl('att-1')).flush({ url: '/api/attachments/att-1/download', expiresIn: 120 });

    expect(open).toHaveBeenCalledWith('/api/attachments/att-1/download?inline=1');
    expect(cmp.viewerOpen()).toBe(false); // system viewer instead of the viewer

    cmp.openPreview(cmp.attachments()[1]);
    http.expectOne(dlUrl('att-9')).flush({ url: '/api/attachments/att-9/download', expiresIn: 120 });
    detectChanges();
    expect(cmp.viewerOpen()).toBe(true);
    expect(cmp.viewerItems().map((i) => i.name)).toEqual(['foto.png']);
    http.verify();
  });

  it('marks quarantined on 409 preview and toasts on 410/500', async () => {
    const { http, detectChanges, fixture, toast } = await setup();
    const error = jest.spyOn(toast, 'error');
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();
    const cmp = fixture.componentInstance;

    cmp.openPreview(cmp.attachments()[0]);
    http.expectOne(dlUrl('att-1')).flush({}, { status: 409, statusText: 'Conflict' });
    expect(cmp.attachments()[0].scanState).toBe('quarantined');
    expect(cmp.viewerOpen()).toBe(false);
    expect(error).toHaveBeenCalledTimes(1);

    // The 410 path and the generic error path reuse the attachment object directly.
    cmp.openPreview({ ...cmp.attachments()[0], scanState: 'clean' });
    http.expectOne(dlUrl('att-1')).flush({}, { status: 410, statusText: 'Gone' });
    expect(error).toHaveBeenCalledTimes(2);
    cmp.openPreview({ ...cmp.attachments()[0], scanState: 'clean' });
    http.expectOne(dlUrl('att-1')).flush({}, { status: 500, statusText: 'Err' });
    expect(error).toHaveBeenCalledTimes(3);
    // A file that left the list while its request ran opens no viewer.
    cmp.openPreview({ ...cmp.attachments()[0], id: 'gone', scanState: 'clean' });
    http.expectOne(dlUrl('gone')).flush({ url: '/api/attachments/gone/download', expiresIn: 120 });
    expect(cmp.viewerOpen()).toBe(false);
    // Guard: openPreview ignores further calls while a preview request is in flight.
    cmp.previewLoadingId.set('att-1');
    cmp.openPreview({ ...cmp.attachments()[0], scanState: 'clean' });
    cmp.previewLoadingId.set(null);
    http.verify();
  });
});
