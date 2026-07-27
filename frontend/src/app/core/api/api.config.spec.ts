import { TestBed } from '@angular/core/testing';
import { API_BASE_URL, USE_MOCK_API, detectMockFlag } from './api.config';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';

/**
 * `detectMockFlag` reads the mock opt-in from a global flag, the URL `?mock=1`
 * or `localStorage['useMockApi']`. The caller passes `location` as a parameter
 * (DI token `LOCATION`). Fake objects therefore cover every branch. The
 * token-factory path runs once through TestBed and `provideLocationMock`.
 */
describe('api.config', () => {
  function locWith(search: string): Location {
    return createLocationMock({ search }) as unknown as Location;
  }

  afterEach(() => {
    delete (window as unknown as { __USE_MOCK_API__?: boolean }).__USE_MOCK_API__;
    window.localStorage.clear();
    TestBed.resetTestingModule();
  });

  it('API_BASE_URL defaults to /api', () => {
    expect(TestBed.inject(API_BASE_URL)).toBe('/api');
  });

  it('defaults to false with no opt-in present', () => {
    expect(detectMockFlag(locWith(''))).toBe(false);
  });

  it('returns true when the global __USE_MOCK_API__ flag is set', () => {
    (window as unknown as { __USE_MOCK_API__?: boolean }).__USE_MOCK_API__ = true;
    expect(detectMockFlag(locWith(''))).toBe(true);
  });

  it('returns true for the ?mock=1 query param', () => {
    expect(detectMockFlag(locWith('?mock=1'))).toBe(true);
  });

  it('ignores ?mock with another value', () => {
    expect(detectMockFlag(locWith('?mock=0'))).toBe(false);
  });

  it('returns true when localStorage useMockApi === "1"', () => {
    window.localStorage.setItem('useMockApi', '1');
    expect(detectMockFlag(locWith(''))).toBe(true);
  });

  it('ignores a non-"1" localStorage value', () => {
    window.localStorage.setItem('useMockApi', 'nope');
    expect(detectMockFlag(locWith(''))).toBe(false);
  });

  it('swallows errors thrown while reading URL/localStorage (catch branch)', () => {
    // `new URLSearchParams(location.search)` throws because `.search` is a
    // throwing getter. `detectMockFlag` must catch the error and return false.
    const throwing = {
      get search(): string {
        throw new Error('boom');
      },
    } as unknown as Location;
    expect(detectMockFlag(throwing)).toBe(false);
  });

  it('USE_MOCK_API token factory reads the injected LOCATION', () => {
    TestBed.configureTestingModule({
      providers: [provideLocationMock(createLocationMock({ search: '?mock=1' }))],
    });
    expect(TestBed.inject(USE_MOCK_API)).toBe(true);
  });
});
