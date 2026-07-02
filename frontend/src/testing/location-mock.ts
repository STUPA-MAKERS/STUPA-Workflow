/**
 * jsdom ≥26 (Jest 30) macht `window.location` komplett unveränderlich — weder
 * `defineProperty` noch `spyOn` funktionieren. App-Code injiziert deshalb das
 * `LOCATION`-Token (#jest30, `@core/browser/location.token`); Specs mocken es
 * per DI: `TestBed.configureTestingModule({ providers: [provideLocationMock(loc)] })`.
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

/** Ein frisches Location-Double mit Jest-Mocks; Felder per *overrides* anpassbar. */
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

/** TestBed-Provider, der das `LOCATION`-Token auf *mock* setzt. */
export function provideLocationMock(mock: LocationMock): Provider {
  return { provide: LOCATION, useValue: mock as unknown as Location };
}
