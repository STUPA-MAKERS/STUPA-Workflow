import { NO_ZOOM, lockInstalledAppZoom } from './zoom-lock';

const BASE = 'width=device-width, initial-scale=1';

function gesture(): Event {
  const e = new Event('gesturestart', { bubbles: true, cancelable: true });
  document.body.dispatchEvent(e);
  return e;
}

describe('lockInstalledAppZoom', () => {
  let meta: HTMLMetaElement;
  beforeEach(() => {
    meta = document.createElement('meta');
    meta.name = 'viewport';
    meta.content = BASE;
    document.head.appendChild(meta);
  });
  afterEach(() => meta.remove());

  it('keeps the zoom in a browser tab', () => {
    const remove = lockInstalledAppZoom(document, false);
    expect(meta.content).toBe(BASE);
    expect(gesture().defaultPrevented).toBe(false);
    remove();
  });

  it('stops the pinch zoom in the installed app and restores it on remove', () => {
    const remove = lockInstalledAppZoom(document, true);
    expect(meta.content).toBe(`${BASE}, ${NO_ZOOM}`);
    expect(gesture().defaultPrevented).toBe(true);
    remove();
    expect(meta.content).toBe(BASE);
    expect(gesture().defaultPrevented).toBe(false);
  });

  it('does not add the limit twice', () => {
    meta.content = `${BASE}, ${NO_ZOOM}`;
    const remove = lockInstalledAppZoom(document, true);
    expect(meta.content).toBe(`${BASE}, ${NO_ZOOM}`);
    remove();
  });

  it('works without a viewport tag', () => {
    meta.remove();
    const remove = lockInstalledAppZoom(document, true);
    expect(gesture().defaultPrevented).toBe(true);
    remove();
  });
});
