import { TestBed } from '@angular/core/testing';
import { KeyboardService } from './keyboard.service';

/** A visual viewport that a test resizes like a keyboard or a pinch zoom would. */
class FakeViewport extends EventTarget {
  width = 390;
  height = 760;
  scale = 1;

  set(patch: Partial<Pick<FakeViewport, 'width' | 'height' | 'scale'>>): void {
    Object.assign(this, patch);
    this.dispatchEvent(new Event('resize'));
  }
}

describe('KeyboardService', () => {
  let vv: FakeViewport | undefined;

  function create(viewport: FakeViewport | undefined): KeyboardService {
    vv = viewport;
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    return TestBed.inject(KeyboardService);
  }

  afterEach(() => {
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: undefined });
  });

  it('is open while the keyboard takes the lower part of the viewport, and closed after it', () => {
    const kb = create(new FakeViewport());
    expect(kb.open()).toBe(false);
    vv?.set({ height: 420 });
    expect(kb.open()).toBe(true);
    // The back gesture closes the keyboard; the field keeps the focus.
    vv?.set({ height: 760 });
    expect(kb.open()).toBe(false);
  });

  it('takes no address bar for a keyboard', () => {
    const kb = create(new FakeViewport());
    vv?.set({ height: 700 });
    expect(kb.open()).toBe(false);
  });

  it('takes no pinch zoom for a keyboard', () => {
    const kb = create(new FakeViewport());
    vv?.set({ width: 195, height: 380, scale: 2 });
    expect(kb.open()).toBe(false);
  });

  it('starts a new reference height when the width changes', () => {
    const kb = create(new FakeViewport());
    vv?.set({ width: 760, height: 390 });
    expect(kb.open()).toBe(false);
    vv?.set({ height: 200 });
    expect(kb.open()).toBe(true);
  });

  it('stays closed without a visual viewport', () => {
    expect(create(undefined).open()).toBe(false);
  });
});
