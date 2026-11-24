import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { NO_ORDER_LIST, order } from '../../../testing/order-fixtures';
import { USE_MOCK_API } from './api.config';
import { OrdersApiService } from './orders.service';

describe('OrdersApiService', () => {
  let svc: OrdersApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    svc = TestBed.inject(OrdersApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('reads the Bestellungen of an Antrag', () => {
    const got = jest.fn();
    svc.list('a-1').subscribe(got);
    const req = http.expectOne('/api/applications/a-1/orders');
    expect(req.request.method).toBe('GET');
    req.flush(NO_ORDER_LIST);
    expect(got).toHaveBeenCalledWith(NO_ORDER_LIST);
  });

  it('creates, changes with the version, sets the status and deletes', () => {
    svc.create('a-1', { title: 'Beamer' }).subscribe();
    const create = http.expectOne('/api/applications/a-1/orders');
    expect(create.request.method).toBe('POST');
    expect(create.request.body).toEqual({ title: 'Beamer' });
    create.flush(order());

    svc.update('o-1', 3, { note: 'x' }).subscribe();
    const update = http.expectOne('/api/orders/o-1');
    expect(update.request.method).toBe('PATCH');
    expect(update.request.body).toEqual({ note: 'x', version: 3 });
    update.flush(order());

    svc.setStatus('o-1', 'ordered', 3).subscribe();
    const status = http.expectOne('/api/orders/o-1/status');
    expect(status.request.body).toEqual({ status: 'ordered', version: 3 });
    status.flush(order());

    svc.remove('o-1').subscribe();
    const remove = http.expectOne('/api/orders/o-1');
    expect(remove.request.method).toBe('DELETE');
    remove.flush(null);
  });

  /** §F/finance/orders/002871 */
  it('reads, uploads and deletes the files of a Bestellung', () => {
    const wire = { id: 'f-1', filename: 'a.pdf', mime: 'application/pdf', size: 10, scanned: true, scanResult: 'clean' };
    const listed = jest.fn();
    svc.files('o-1').subscribe(listed);
    http.expectOne('/api/orders/o-1/attachments').flush([wire]);
    expect(listed.mock.calls[0][0][0]).toMatchObject({ id: 'f-1', filename: 'a.pdf' });

    const uploaded = jest.fn();
    svc.uploadFile('o-1', new File(['x'], 'a.pdf')).subscribe(uploaded);
    const upload = http.expectOne('/api/orders/o-1/attachments');
    expect(upload.request.method).toBe('POST');
    expect((upload.request.body as FormData).get('file')).toBeInstanceOf(File);
    upload.flush(wire);
    expect(uploaded.mock.calls[0][0]).toMatchObject({ id: 'f-1' });

    svc.removeFile('o-1', 'f-1').subscribe();
    const remove = http.expectOne('/api/orders/o-1/attachments/f-1');
    expect(remove.request.method).toBe('DELETE');
    remove.flush(null);
  });
});
