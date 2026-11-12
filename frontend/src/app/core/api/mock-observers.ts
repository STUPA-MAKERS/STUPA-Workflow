/**
 * Demo observers of an application for the mock API (dev builds only): the routes
 * `GET/POST/DELETE /applications/{id}/observers` and `POST /observers/end`. The store
 * keeps the observers per application for the life of the page, with the refusals of the
 * server (`observer_exists`, `observer_limit`).
 */
import { signal } from '@angular/core';
import type { ApplicationObserver } from './models';

/** The answer of a mock route: the status and the body. */
export interface MockObserverReply {
  readonly status: number;
  readonly body: unknown;
}

const LIMIT = 5;

const store = signal<ReadonlyMap<string, readonly ApplicationObserver[]>>(new Map());

function listOf(appId: string): readonly ApplicationObserver[] {
  return (
    store().get(appId) ?? [
      { id: `${appId.slice(0, 8)}-0b5e-4000-8000-000000000001`, email: 'adrian.becker@example.org', addedAt: '2026-11-10T09:00:00Z' },
    ]
  );
}

function put(appId: string, list: readonly ApplicationObserver[]): void {
  store.set(new Map([...store(), [appId, list]]));
}

function refused(status: number, code: string): MockObserverReply {
  return { status, body: { type: 'about:blank', title: 'Refused', status, code } };
}

const LIST = /\/applications\/([^/]+)\/observers$/;
const ONE = /\/applications\/([^/]+)\/observers\/([^/]+)$/;

/** The answer of an observer route, or null for a path of another module. */
export function mockObservers(method: string, p: string, body: unknown): MockObserverReply | null {
  if (method === 'POST' && p.endsWith('/observers/end')) {
    const token = (body as { token?: string } | null)?.token ?? '';
    return token.includes('.') ? { status: 204, body: null } : refused(404, 'not_found');
  }
  const one = ONE.exec(p);
  if (one && method === 'DELETE') {
    put(one[1], listOf(one[1]).filter((o) => o.id !== one[2]));
    return { status: 204, body: null };
  }
  const all = LIST.exec(p);
  if (!all) return null;
  const appId = all[1];
  if (method === 'GET') return { status: 200, body: listOf(appId) };
  if (method !== 'POST') return null;
  const email = String((body as { email?: string } | null)?.email ?? '').trim();
  const list = listOf(appId);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return refused(422, '');
  if (list.some((o) => o.email.toLowerCase() === email.toLowerCase())) return refused(409, 'observer_exists');
  if (list.length >= LIMIT) return refused(422, 'observer_limit');
  const row: ApplicationObserver = {
    id: `${appId.slice(0, 8)}-0b5e-4000-8000-${String(Date.now()).slice(-12).padStart(12, '0')}`,
    email,
    addedAt: new Date().toISOString(),
  };
  put(appId, [...list, row]);
  return { status: 201, body: row };
}
