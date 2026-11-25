import { TestBed } from '@angular/core/testing';
import { type ActivatedRouteSnapshot, Router, type RouterStateSnapshot, provideRouter } from '@angular/router';
import { orderAddress } from './order-address.guard';

function run(queryParams: Record<string, unknown>): string | true {
  const result = TestBed.runInInjectionContext(() =>
    orderAddress({ queryParams } as unknown as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
  );
  return result === true ? true : TestBed.inject(Router).serializeUrl(result as never);
}

describe('orderAddress', () => {
  beforeEach(() => TestBed.configureTestingModule({ providers: [provideRouter([])] }));

  it('lets the list through', () => {
    expect(run({ segment: 'open' })).toBe(true);
    expect(run({ id: ['a', 'b'], new: 'invoice' })).toBe(true);
  });

  /** §F/finance/orders/002936: `/orders?id=<id>` opens the detail of the Bestellung. */
  it('leads the address with an id to the detail and keeps the filter', () => {
    expect(run({ id: 'o-1', segment: 'done' })).toBe('/orders/o-1?segment=done');
  });

  /** §F/finance/orders/002937: `/orders?new=order&application=<id>` opens the form for this Antrag. */
  it('leads the address of a new Bestellung to the form with its Antrag', () => {
    expect(run({ new: 'order', application: 'a-1' })).toBe('/orders/new?application=a-1');
    expect(run({ new: 'order', id: 'o-1' })).toBe('/orders/new');
  });
});
