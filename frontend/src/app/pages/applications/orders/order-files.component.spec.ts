import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Attachment } from '@core/api/models';
import { OrdersApiService } from '@core/api/orders.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastMock } from '../../../../testing/toast';
import { OrderFilesComponent } from './order-files.component';

const file = (over: Partial<Attachment> = {}): Attachment => ({
  id: 'f-1',
  filename: 'bestaetigung.pdf',
  mime: 'application/pdf',
  size: 2048,
  scanned: true,
  scanState: 'clean',
  ...over,
});

async function setup(opts: { files?: Attachment[]; canManage?: boolean; fail?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const orders = {
    files: jest.fn(() => (opts.fail ? throwError(() => ({ status: 500 })) : of(opts.files ?? [file()]))),
    uploadFile: jest.fn((_id: string, f: File) => of(file({ id: `n-${f.name}`, filename: f.name, scanState: 'scanning' }))),
    removeFile: jest.fn(() => of(undefined)),
  };
  const api = { attachmentUrl: jest.fn(() => of({ url: '/api/attachments/f-1/download' })) };
  const toast = toastMock();
  const view = await render(OrderFilesComponent, {
    inputs: { orderId: 'o-1', canManage: opts.canManage ?? true },
    providers: [
      { provide: OrdersApiService, useValue: orders },
      { provide: ApiClient, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const opened = jest.spyOn(cmp, 'openUrl').mockImplementation(() => undefined);
  return { ...view, cmp, orders, api, toast, opened };
}

/** §F/finance/orders/002871: a Bestellung has files of its own. */
describe('OrderFilesComponent', () => {
  afterEach(() => localStorage.clear());

  it('lists the files of the Bestellung and downloads a clean one', async () => {
    const { orders, api, opened } = await setup({
      files: [file(), file({ id: 'f-2', filename: 'neu.pdf', scanState: 'scanning' })],
    });
    expect(orders.files).toHaveBeenCalledWith('o-1');
    expect(screen.getByRole('heading', { name: 'Dateien' })).toBeInTheDocument();
    expect(screen.getByText('bestaetigung.pdf')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Herunterladen: neu.pdf' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Herunterladen: bestaetigung.pdf' }));
    expect(api.attachmentUrl).toHaveBeenCalledWith('f-1');
    expect(opened).toHaveBeenCalledWith('/api/attachments/f-1/download');
  });

  it('shows a reader no upload and no delete, and the empty state without files', async () => {
    await setup({ fail: true, canManage: false });
    expect(screen.getByText('Noch keine Dateien')).toBeInTheDocument();
    expect(screen.queryByText('Datei hochladen')).not.toBeInTheDocument();
  });

  it('keeps a reader from an upload and from a delete', async () => {
    const { cmp, orders } = await setup({ canManage: false });
    cmp.upload([new File(['x'], 'a.pdf')]);
    expect(orders.uploadFile).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Anhang löschen: bestaetigung.pdf' })).not.toBeInTheDocument();
  });

  it('uploads the picked files one after the other and names a refused upload', async () => {
    const { cmp, orders, toast, fixture } = await setup({ files: [] });
    expect(cmp.picked({ files: null })).toEqual([]);
    cmp.upload([]);
    cmp.upload([new File(['x'], 'a.pdf'), new File(['y'], 'b.pdf')]);
    fixture.detectChanges();
    expect(orders.uploadFile).toHaveBeenCalledTimes(2);
    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(screen.getByText('b.pdf')).toBeInTheDocument();

    orders.uploadFile.mockReturnValueOnce(throwError(() => ({ status: 413 })));
    cmp.upload([new File(['x'], 'gross.pdf')]);
    expect(toast.error).toHaveBeenCalledWith('Datei zu groß (max. 10 MB).');
    orders.uploadFile.mockReturnValueOnce(throwError(() => ({})));
    cmp.upload([new File(['x'], 'c.pdf')]);
    expect(toast.error).toHaveBeenCalledTimes(2);

    const pending = new Subject<Attachment>();
    orders.uploadFile.mockReturnValueOnce(pending);
    cmp.upload([new File(['x'], 'd.pdf')]);
    cmp.upload([new File(['x'], 'e.pdf')]);
    expect(orders.uploadFile).toHaveBeenCalledTimes(5);
  });

  it('opens the address of a download in a new tab', async () => {
    const { cmp, opened } = await setup();
    opened.mockRestore();
    const open = jest.spyOn(window, 'open').mockImplementation(() => null);
    cmp.openUrl('/api/x');
    expect(open).toHaveBeenCalledWith('/api/x', '_blank', 'noopener');
    open.mockRestore();
  });

  it('reads the files of the file input', async () => {
    const { orders } = await setup({ files: [] });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(['x'], 'a.pdf', { type: 'application/pdf' }));
    expect(orders.uploadFile).toHaveBeenCalledTimes(1);
  });

  it('asks before the delete and removes the file', async () => {
    const { orders, cmp, toast, fixture } = await setup();
    cmp.remove();
    expect(orders.removeFile).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Anhang löschen: bestaetigung.pdf' }));
    expect(cmp.confirming()?.id).toBe('f-1');
    cmp.remove();
    fixture.detectChanges();
    expect(orders.removeFile).toHaveBeenCalledWith('o-1', 'f-1');
    expect(screen.queryByText('bestaetigung.pdf')).not.toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('names a failed delete and a failed download, and runs one request at a time', async () => {
    const { orders, api, cmp, toast } = await setup();
    orders.removeFile.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.confirming.set(file());
    cmp.remove();
    expect(cmp.confirming()).toBeNull();
    api.attachmentUrl.mockReturnValueOnce(throwError(() => ({ status: 409 })));
    cmp.download(file());
    expect(toast.error).toHaveBeenCalledTimes(2);

    const pending = new Subject<{ url: string }>();
    api.attachmentUrl.mockReturnValueOnce(pending);
    cmp.download(file());
    cmp.download(file());
    cmp.confirming.set(file());
    cmp.remove();
    expect(api.attachmentUrl).toHaveBeenCalledTimes(2);
    expect(orders.removeFile).toHaveBeenCalledTimes(1);
  });
});
