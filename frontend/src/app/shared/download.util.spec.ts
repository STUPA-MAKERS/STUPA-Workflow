import { downloadBlob } from './download.util';

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

    // Spy on the click that fires the actual download, and verify the anchor is
    // attached to the DOM at click-time then removed afterwards.
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
    // Anchor removed synchronously after the click.
    expect(document.querySelector('a')).toBeNull();

    // Revoke is deferred to a macrotask (Safari/Firefox-safe).
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
