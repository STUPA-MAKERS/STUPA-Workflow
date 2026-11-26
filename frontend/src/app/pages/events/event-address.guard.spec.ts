import { TestBed } from '@angular/core/testing';
import { type ActivatedRouteSnapshot, Router, type RouterStateSnapshot, provideRouter } from '@angular/router';
import { eventAddress } from './event-address.guard';

function run(queryParams: Record<string, unknown>): string | true {
  const result = TestBed.runInInjectionContext(() =>
    eventAddress({ queryParams } as unknown as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
  );
  return result === true ? true : TestBed.inject(Router).serializeUrl(result as never);
}

describe('eventAddress', () => {
  beforeEach(() => TestBed.configureTestingModule({ providers: [provideRouter([])] }));

  it('lets the list through', () => {
    expect(run({ segment: 'past' })).toBe(true);
    expect(run({ id: ['a', 'b'], new: 'order' })).toBe(true);
  });

  /** §F/collaboration/events/003027: `/events?id=<id>` opens the detail of the Event. */
  it('leads the address with an id to the detail and keeps the filter', () => {
    expect(run({ id: 'e-1', segment: 'done' })).toBe('/events/e-1?segment=done');
  });

  it('leads the address of a new Event to the form', () => {
    expect(run({ new: 'event', from: 'e-1' })).toBe('/events/new?from=e-1');
  });
});
