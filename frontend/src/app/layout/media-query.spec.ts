import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { mediaQuerySignal } from './media-query';

@Component({ standalone: true, template: '' })
class Host {
  readonly phone = mediaQuerySignal('(max-width: 768px)');
}

describe('mediaQuerySignal', () => {
  const original = window.matchMedia;
  let listener: ((e: MediaQueryListEvent) => void) | null = null;
  const remove = jest.fn();

  beforeEach(() => {
    listener = null;
    remove.mockReset();
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => (listener = cb),
      removeEventListener: remove,
    })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => (window.matchMedia = original));

  it('starts with the current match and follows the changes', () => {
    const fixture = TestBed.createComponent(Host);
    expect(fixture.componentInstance.phone()).toBe(true);
    listener?.({ matches: false } as MediaQueryListEvent);
    expect(fixture.componentInstance.phone()).toBe(false);
  });

  it('removes its listener with the component', () => {
    const fixture = TestBed.createComponent(Host);
    fixture.destroy();
    expect(remove).toHaveBeenCalledWith('change', listener);
  });
});
