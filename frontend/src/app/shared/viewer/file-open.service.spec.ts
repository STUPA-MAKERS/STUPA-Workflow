import { TestBed } from '@angular/core/testing';
import { FileOpenService } from './file-open.service';

/** Let `matchMedia` report a coarse pointer (a phone) or a mouse. */
function mockPointer(coarse: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('coarse') ? coarse : false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

function service(coarse = false): FileOpenService {
  mockPointer(coarse);
  TestBed.resetTestingModule();
  return TestBed.inject(FileOpenService);
}

/** The links that the service clicks: a download or a new tab. */
function clickedLinks(): { href: string; download: string; target: string }[] {
  const links: { href: string; download: string; target: string }[] = [];
  jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    links.push({ href: this.getAttribute('href') ?? '', download: this.download, target: this.target });
  });
  return links;
}

describe('FileOpenService', () => {
  afterEach(() => jest.restoreAllMocks());

  it('§ui-kit:F/administration/files/001080: opens a PDF in the viewer with its inline preview', () => {
    const files = service();
    files.open({ name: 'Antrag.pdf', url: '/api/applications/a1/pdf', kind: 'pdf' });
    expect(files.shown()).toEqual({
      item: { name: 'Antrag.pdf', url: '/api/applications/a1/pdf?inline=1', mime: undefined, kind: 'pdf' },
      downloadUrl: '/api/applications/a1/pdf',
    });
    files.close();
    expect(files.shown()).toBeNull();
  });

  it('§ui-kit:F/administration/files/001080: opens a raster image by its type, also on a phone', () => {
    const files = service(true);
    files.open({ name: 'logo', url: '/api/admin/cd-variant-logos/l1/file', mime: 'image/png' });
    expect(files.shown()?.item.url).toBe('/api/admin/cd-variant-logos/l1/file?inline=1');
  });

  it('§ui-kit:F/administration/files/001080: downloads a type that the viewer cannot show', () => {
    const files = service();
    const links = clickedLinks();
    expect(files.canView({ name: 'liste.xlsx', url: '/api/x' })).toBe(false);
    expect(files.canView({ name: 'logo.svg', url: '/api/y', mime: 'image/svg+xml' })).toBe(false);
    files.open({ name: 'logo.svg', url: '/api/y', mime: 'image/svg+xml' });
    expect(files.shown()).toBeNull();
    expect(links).toEqual([{ href: '/api/y', download: '', target: '' }]);
  });

  it('§ui-kit:NF/usability/layout/001081: opens a PDF on a coarse pointer in a new tab', () => {
    const files = service(true);
    const links = clickedLinks();
    files.open({ name: 'Protokoll.pdf', url: '/api/protocols/p1/pdf?variant=public', kind: 'pdf' });
    expect(files.shown()).toBeNull();
    expect(links).toEqual([{ href: '/api/protocols/p1/pdf?variant=public&inline=1', download: '', target: '_blank' }]);
  });

  it('§ui-kit:F/administration/files/001080: a click with a modifier keeps the default of the browser', () => {
    const files = service();
    const file = { name: 'a.pdf', url: '/api/a', kind: 'pdf' as const };
    const ctrl = new MouseEvent('click', { button: 0, ctrlKey: true, cancelable: true });
    expect(files.click(ctrl, file)).toBe(false);
    expect(ctrl.defaultPrevented).toBe(false);
    const middle = new MouseEvent('click', { button: 1, cancelable: true });
    expect(files.click(middle, file)).toBe(false);
    expect(files.shown()).toBeNull();
    const plain = new MouseEvent('click', { button: 0, cancelable: true });
    expect(files.click(plain, file)).toBe(true);
    expect(plain.defaultPrevented).toBe(true);
    expect(files.shown()?.downloadUrl).toBe('/api/a');
  });
});
