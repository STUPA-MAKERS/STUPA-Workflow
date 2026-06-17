import { TestBed } from '@angular/core/testing';
import { API_BASE_URL, USE_MOCK_API } from './api.config';

/**
 * `detectMockFlag` is the `USE_MOCK_API` token factory; it reads from the
 * global flag / URL `?mock=1` / `localStorage['useMockApi']`. We exercise each
 * branch by mutating `window` before injecting the token in a fresh TestBed.
 */
describe('api.config', () => {
  const origLocation = window.location;

  function setSearch(search: string): void {
    Object.defineProperty(window, 'location', {
      value: { search },
      writable: true,
      configurable: true,
    });
  }

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: origLocation,
      writable: true,
      configurable: true,
    });
    delete (window as unknown as { __USE_MOCK_API__?: boolean }).__USE_MOCK_API__;
    window.localStorage.clear();
    TestBed.resetTestingModule();
  });

  function detect(): boolean {
    return TestBed.inject(USE_MOCK_API);
  }

  it('API_BASE_URL defaults to /api', () => {
    expect(TestBed.inject(API_BASE_URL)).toBe('/api');
  });

  it('defaults to false with no opt-in present', () => {
    setSearch('');
    expect(detect()).toBe(false);
  });

  it('returns true when the global __USE_MOCK_API__ flag is set', () => {
    (window as unknown as { __USE_MOCK_API__?: boolean }).__USE_MOCK_API__ = true;
    expect(detect()).toBe(true);
  });

  it('returns true for the ?mock=1 query param', () => {
    setSearch('?mock=1');
    expect(detect()).toBe(true);
  });

  it('ignores ?mock with another value', () => {
    setSearch('?mock=0');
    expect(detect()).toBe(false);
  });

  it('returns true when localStorage useMockApi === "1"', () => {
    setSearch('');
    window.localStorage.setItem('useMockApi', '1');
    expect(detect()).toBe(true);
  });

  it('ignores a non-"1" localStorage value', () => {
    setSearch('');
    window.localStorage.setItem('useMockApi', 'nope');
    expect(detect()).toBe(false);
  });

  it('swallows errors thrown while reading URL/localStorage (catch branch)', () => {
    // Force `new URLSearchParams(window.location.search)` to throw by making
    // `.search` a throwing getter; detectMockFlag must catch and return false.
    Object.defineProperty(window, 'location', {
      value: {
        get search(): string {
          throw new Error('boom');
        },
      },
      writable: true,
      configurable: true,
    });
    expect(detect()).toBe(false);
  });
});
