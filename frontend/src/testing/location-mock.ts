/**
 * jsdom ≥26 (Jest 30) makes `window.location` fully immutable. Neither
 * `defineProperty` nor `spyOn` works on it. The app code therefore injects the
 * `LOCATION` token (`@core/browser/location.token`). A spec mocks that token through DI:
 * `TestBed.configureTestingModule({ providers: [provideLocationMock(loc)] })`.
 */
import type { Provider } from '@angular/core';
import { LOCATION } from '../app/core/browser/location.token';

export interface LocationMock {
  assign: jest.Mock<void, [string]>;
  replace: jest.Mock<void, [string]>;
  reload: jest.Mock<void, []>;
  href: string;
  origin: string;
  pathname: string;
  search: string;
  hash: string;
  protocol: string;
  host: string;
}

export function createLocationMock(overrides: Partial<LocationMock> = {}): LocationMock {
  return {
    assign: jest.fn<void, [string]>(),
    replace: jest.fn<void, [string]>(),
    reload: jest.fn<void, []>(),
    href: 'http://localhost/',
    origin: 'http://localhost',
    pathname: '/',
    search: '',
    hash: '',
    protocol: 'http:',
    host: 'localhost',
    ...overrides,
  };
}

export function provideLocationMock(mock: LocationMock): Provider {
  return { provide: LOCATION, useValue: mock as unknown as Location };
}
