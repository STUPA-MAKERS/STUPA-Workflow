import { MOCK_EVENT_SALES, MOCK_MOLLIE, MOCK_PRETIX, MOCK_PRETIX_EVENTS, mockSalesBody } from './mock-sales';

describe('mockSalesBody', () => {
  it('answers each read and each action of the integrations', () => {
    expect(mockSalesBody('GET', '/api/admin/pretix')).toBe(MOCK_PRETIX);
    expect(mockSalesBody('GET', '/api/admin/pretix/failed-bookings')).toEqual({ items: expect.any(Array) });
    expect(mockSalesBody('GET', '/api/admin/mollie')).toBe(MOCK_MOLLIE);
    expect(mockSalesBody('GET', '/api/admin/mollie/failed-bookings')).toEqual({ items: [] });
    expect(mockSalesBody('GET', '/api/pretix/events')).toBe(MOCK_PRETIX_EVENTS);
    expect(mockSalesBody('GET', '/api/events/e-1/sales')).toBe(MOCK_EVENT_SALES);
    expect(mockSalesBody('GET', '/api/sales-sync')).toEqual({ pretix: true, mollie: true });
    expect(mockSalesBody('POST', '/api/admin/mollie/test')).toEqual(expect.objectContaining({ ok: true }));
    expect(mockSalesBody('POST', '/api/sales-sync')).toEqual({ booked: 0, failures: [] });
    expect(mockSalesBody('POST', '/api/events/e-1/sales/refresh')).toEqual({ booked: 0, failures: [] });
  });

  it('leaves every other call to the rest of the mock', () => {
    expect(mockSalesBody('GET', '/api/events/e-1')).toBeUndefined();
    expect(mockSalesBody('PUT', '/api/admin/pretix')).toBeUndefined();
  });
});
