import type { Router } from '@angular/router';
import { routeInternalLink } from './internal-link';

function click(html: string, init: MouseEventInit = {}): { event: MouseEvent; target: Element } {
  document.body.innerHTML = html;
  const target = document.body.querySelector('[data-t]') as Element;
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init });
  Object.defineProperty(event, 'target', { value: target });
  return { event, target };
}

describe('routeInternalLink', () => {
  const router = { url: '/a/b#x', navigateByUrl: jest.fn().mockResolvedValue(true) };
  const r = router as unknown as Router;
  beforeEach(() => router.navigateByUrl.mockClear());

  it('navigates an app path and an anchor', () => {
    const a = click('<a href="/todos?x=1"><span data-t>x</span></a>');
    routeInternalLink(a.event, r);
    expect(a.event.defaultPrevented).toBe(true);
    expect(router.navigateByUrl).toHaveBeenCalledWith('/todos?x=1');
    const b = click('<a data-t href="#top">x</a>');
    routeInternalLink(b.event, r);
    expect(router.navigateByUrl).toHaveBeenLastCalledWith('/a/b#top');
    const c = click('<a data-t href="/apix/s">x</a>');
    routeInternalLink(c.event, r);
    expect(router.navigateByUrl).toHaveBeenLastCalledWith('/apix/s');
  });

  it.each([
    ['an external link', '<a data-t href="https://x.de" target="_blank">x</a>', {}],
    ['a protocol-relative href', '<a data-t href="//x.de">x</a>', {}],
    ['a link without href', '<a data-t>x</a>', {}],
    ['text outside a link', '<p data-t>x</p>', {}],
    ['a middle click', '<a data-t href="/a">x</a>', { button: 1 }],
    ['a ctrl click', '<a data-t href="/a">x</a>', { ctrlKey: true }],
    ['an API path', '<a data-t href="/api/attachments/1/download">x</a>', {}],
    ['the API root', '<a data-t href="/api">x</a>', {}],
    ['a share link', '<a data-t href="/s/abc">x</a>', {}],
    ['a well-known path', '<a data-t href="/.well-known/security.txt">x</a>', {}],
  ])('leaves %s to the browser', (_k, html, init) => {
    const { event } = click(html, init);
    routeInternalLink(event, r);
    expect(event.defaultPrevented).toBe(false);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('does nothing without a router or after another handler', () => {
    const a = click('<a data-t href="/a">x</a>');
    routeInternalLink(a.event, null);
    expect(a.event.defaultPrevented).toBe(false);
    const b = click('<a data-t href="/a">x</a>');
    b.event.preventDefault();
    routeInternalLink(b.event, r);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('copes with a target that is not an element', () => {
    const event = new MouseEvent('click', { button: 0 });
    Object.defineProperty(event, 'target', { value: null });
    routeInternalLink(event, r);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });
});
