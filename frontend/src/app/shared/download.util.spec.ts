import { signal } from '@angular/core';
import { Subject, throwError } from 'rxjs';
import { downloadBlob, exportDownload } from './download.util';

describe('downloadBlob', () => {
  const realCreate = URL.createObjectURL;
  const realRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    jest.useFakeTimers();
    (URL.createObjectURL as unknown) = jest.fn(() => 'blob:fake-url');
    (URL.revokeObjectURL as unknown) = jest.fn();
  });

  afterEach(() => {
    jest.useRealTimers();
    URL.createObjectURL = realCreate;
    URL.revokeObjectURL = realRevoke;
    document.body.innerHTML = '';
  });

  it('creates an anchor, clicks it, appends and removes it, then revokes the URL', () => {
    const blob = new Blob(['x'], { type: 'text/plain' });

    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(document.body.contains(this)).toBe(true);
      expect(this.href).toBe('blob:fake-url');
      expect(this.download).toBe('export.xlsx');
    });

    downloadBlob(blob, 'export.xlsx');

    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a')).toBeNull();

    // The code revokes the URL in a macrotask, which is safe for Safari and Firefox.
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    jest.runAllTimers();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake-url');

    clickSpy.mockRestore();
  });

  it('uses the provided filename as the anchor download attribute', () => {
    let captured = '';
    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      captured = this.download;
    });
    downloadBlob(new Blob(['data']), 'report-2026.csv');
    expect(captured).toBe('report-2026.csv');
    clickSpy.mockRestore();
  });
});

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
