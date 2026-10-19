import { signal } from '@angular/core';
import { Subject, throwError } from 'rxjs';
import { exportDownload } from './download.util';

describe('exportDownload', () => {
  const realCreate = URL.createObjectURL;

  beforeEach(() => {
    (URL.createObjectURL as unknown) = jest.fn(() => 'blob:fake-url');
  });

  afterEach(() => {
    URL.createObjectURL = realCreate;
  });

  it('sets the busy flag, downloads the file and clears the flag', () => {
    const busy = signal(false);
    const response = new Subject<Blob>();
    const onError = jest.fn();
    let filename = '';
    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      filename = this.download;
    });

    exportDownload(busy, () => response, 'budget.xlsx', onError);
    expect(busy()).toBe(true);
    response.next(new Blob(['x']));

    expect(filename).toBe('budget.xlsx');
    expect(busy()).toBe(false);
    expect(onError).not.toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it('does not build a second request while busy', () => {
    const busy = signal(true);
    const request = jest.fn(() => new Subject<Blob>());
    exportDownload(busy, request, 'x.xlsx', jest.fn());
    expect(request).not.toHaveBeenCalled();
    expect(busy()).toBe(true);
  });

  it('clears the flag and reports a failure', () => {
    const busy = signal(false);
    const onError = jest.fn();
    const err = new Error('boom');
    exportDownload(busy, () => throwError(() => err), 'x.xlsx', onError);
    expect(busy()).toBe(false);
    expect(onError).toHaveBeenCalledWith(err);
  });
});
