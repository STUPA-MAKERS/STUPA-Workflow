import { mockObservers } from './mock-observers';

describe('mockObservers', () => {
  const base = '/api/applications/b0000000-0000-4000-8000-000000000001/observers';

  it('refuses a bad address, the sixth observer and an unknown route', () => {
    expect(mockObservers('POST', base, { email: 'kein-mail' })?.status).toBe(422);
    expect(mockObservers('POST', base, null)?.status).toBe(422);
    for (const n of [1, 2, 3, 4]) {
      expect(mockObservers('POST', base, { email: `p${n}@example.org` })?.status).toBe(201);
    }
    expect(mockObservers('POST', base, { email: 'six@example.org' })).toMatchObject({
      status: 422,
      body: { code: 'observer_limit' },
    });
    expect(mockObservers('PUT', base, {})).toBeNull();
    expect(mockObservers('GET', '/api/applications/x/links', null)).toBeNull();
    expect(mockObservers('POST', '/api/observers/end', null)?.status).toBe(404);
  });
});
