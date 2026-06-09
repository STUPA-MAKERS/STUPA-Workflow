import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
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

  it('shows the empty + session hint and no upload control without permission', async () => {
    await setup(false);
    expect(screen.getByText('Noch keine Anhänge hochgeladen.')).toBeInTheDocument();
    expect(
      screen.getByText('Es werden nur in dieser Sitzung hochgeladene Anhänge angezeigt.'),
    ).toBeInTheDocument();
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

  it('enables download for a scanned (clean) attachment and opens the signed URL', async () => {
    const { http, detectChanges, fixture } = await setup();
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
    detectChanges();

    const open = jest
      .spyOn(fixture.componentInstance as unknown as { openUrl: (u: string) => void }, 'openUrl')
      .mockImplementation(() => {});
    expect(screen.getByText('Bereit')).toBeInTheDocument();
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
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
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

  it('toasts an expired-link message on a 410 download', async () => {
    const { http, detectChanges, toast } = await setup();
    await uploadFile();
    http.expectOne(uploadUrl).flush(wire({ scanned: true }), { status: 201, statusText: 'Created' });
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
  ])('maps upload error %s to its toast', async (status, message) => {
    const { http, toast } = await setup();
    const error = jest.spyOn(toast, 'error');
    await uploadFile();
    http.expectOne(uploadUrl).flush({ title: 'e' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    http.verify();
  });
});
