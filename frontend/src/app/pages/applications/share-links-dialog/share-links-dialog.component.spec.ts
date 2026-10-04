/**
 * The public share links of one application.
 *
 * What matters is what the UI promises about the token. It is shown once, the server
 * keeps a hash, and a listing can never hand it back — so a test that only checked "a
 * dialog opens" would miss the whole point.
 */
import { Component, signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { ApplicationShareLink } from '@core/api/models';
import { ShareLinksDialogComponent } from './share-links-dialog.component';

@Component({
  standalone: true,
  imports: [ShareLinksDialogComponent],
  template: `<app-share-links-dialog [applicationId]="id()" [(open)]="open" />`,
})
class Host {
  readonly id = signal<string | null>('app-1');
  readonly open = signal(false);
}

/** A live link, as the listing returns it: no `url`, because the server has only a hash. */
function liveShare(over: Partial<ApplicationShareLink> = {}): ApplicationShareLink {
  return {
    id: 'sh-1',
    createdAt: '2026-06-05T10:00:00Z',
    expiresAt: '2099-01-01T00:00:00Z',
    revokedAt: null,
    createdBy: 'office',
    label: 'An die Fachschaft',
    url: null,
    ...over,
  };
}

const LIST = (r: { url: string; method: string }) =>
  r.method === 'GET' && r.url === '/api/applications/app-1/shares';

async function setup() {
  const view = await render(Host, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const host = view.fixture.componentInstance;
  const cmp = view.fixture.debugElement.children[0].componentInstance as ShareLinksDialogComponent;
  /** Open the dialog and answer the listing. */
  const openWith = (rows: ApplicationShareLink[]) => {
    host.open.set(true);
    view.detectChanges();
    http.expectOne(LIST).flush(rows);
    view.detectChanges();
  };
  return { ...view, http, host, cmp, openWith };
}

describe('ShareLinksDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads nothing while closed', async () => {
    const { http } = await setup();
    http.verify();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('lists the existing links when it opens', async () => {
    const { openWith } = await setup();
    openWith([liveShare()]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('An die Fachschaft')).toBeInTheDocument();
  });

  it('shows a freshly minted link once, and nothing before there is one', async () => {
    const { http, detectChanges, cmp, openWith } = await setup();
    openWith([]);
    // Nothing to copy yet: the token exists only in the response to the create call.
    expect(screen.queryByRole('button', { name: 'Kopieren' })).not.toBeInTheDocument();
    expect(screen.getByText('Es gibt noch keinen Link zu diesem Antrag.')).toBeInTheDocument();

    cmp.create();
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/shares')
      .flush(liveShare({ url: 'https://x.example/s/token-abc' }));
    detectChanges();

    expect(screen.getByDisplayValue('https://x.example/s/token-abc')).toBeInTheDocument();
  });

  it('sends the chosen lifetime and drops an empty note', async () => {
    // An empty label must not travel as `""`: the server would store a blank note.
    const { http, cmp, openWith } = await setup();
    openWith([]);
    cmp.ttl.set('7');
    cmp.label.set('   ');
    cmp.create();
    const post = http.expectOne((r) => r.method === 'POST');
    expect(post.request.body).toEqual({ ttlDays: 7 });
    post.flush(liveShare({ url: 'https://x.example/s/t' }));
  });

  it('sends a note when there is one', async () => {
    const { http, cmp, openWith } = await setup();
    openWith([]);
    cmp.label.set(' Presse ');
    cmp.create();
    const post = http.expectOne((r) => r.method === 'POST');
    expect(post.request.body).toEqual({ ttlDays: 30, label: 'Presse' });
    post.flush(liveShare({ url: 'https://x/s/t' }));
    expect(cmp.label()).toBe('');
  });

  it('copies the fresh link to the clipboard', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, detectChanges, cmp, openWith } = await setup();
    openWith([]);
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x.example/s/token-abc' }));
    detectChanges();

    await userEvent.click(screen.getByRole('button', { name: 'Kopieren' }));
    expect(writeText).toHaveBeenCalledWith('https://x.example/s/token-abc');
    expect(cmp.copied()).toBe(true);
  });

  it('survives a browser without the clipboard API', async () => {
    Object.assign(navigator, { clipboard: undefined });
    const { http, cmp, openWith } = await setup();
    openWith([]);
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    expect(() => cmp.copy()).not.toThrow();
    expect(cmp.copied()).toBe(false);
  });

  it('marks the link as not copied when the clipboard write is refused', async () => {
    const writeText = jest.fn().mockRejectedValue(new Error('denied'));
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, cmp, openWith } = await setup();
    openWith([]);
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    cmp.copy();
    await Promise.resolve();
    await Promise.resolve();
    expect(cmp.copied()).toBe(false);
  });

  it('copies nothing when there is no fresh link', async () => {
    const writeText = jest.fn();
    Object.assign(navigator, { clipboard: { writeText } });
    const { cmp, openWith } = await setup();
    openWith([]);
    cmp.copy();
    expect(writeText).not.toHaveBeenCalled();
  });

  it('replaces a revoked link in place rather than dropping it from the list', async () => {
    const { http, detectChanges, cmp, openWith } = await setup();
    openWith([liveShare()]);
    await userEvent.click(screen.getByRole('button', { name: 'Zurückziehen' }));
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-1/shares/sh-1')
      .flush(liveShare({ revokedAt: '2026-06-06T10:00:00Z' }));
    detectChanges();

    expect(cmp.shares()).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Zurückziehen' })).not.toBeInTheDocument();
    expect(screen.getByText(/Zurückgezogen am/)).toBeInTheDocument();
  });

  it('treats an expired link as dead even though it was never revoked', async () => {
    const { openWith } = await setup();
    openWith([liveShare({ expiresAt: '2020-01-01T00:00:00Z' })]);
    expect(screen.queryByRole('button', { name: 'Zurückziehen' })).not.toBeInTheDocument();
    expect(screen.getByText(/Abgelaufen am/)).toBeInTheDocument();
  });

  it('names a link without a note rather than showing an empty row', async () => {
    const { openWith } = await setup();
    openWith([liveShare({ label: null })]);
    expect(screen.getAllByText('Ohne Notiz').length).toBeGreaterThan(0);
  });

  it('forgets the token when it closes and opens again', async () => {
    const { http, detectChanges, host, cmp, openWith } = await setup();
    openWith([]);
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    expect(cmp.freshUrl()).toBe('https://x/s/t');

    await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(host.open()).toBe(false);
    expect(cmp.freshUrl()).toBeNull();

    host.open.set(true);
    detectChanges();
    http.expectOne(LIST).flush([]);
    expect(cmp.freshUrl()).toBeNull();
  });

  it('reports a failed create instead of leaving the button spinning', async () => {
    const { http, cmp, openWith } = await setup();
    openWith([]);
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush({}, { status: 403, statusText: 'Forbidden' });
    expect(cmp.creating()).toBe(false);
    expect(cmp.freshUrl()).toBeNull();
  });

  it('reports a failed revoke and keeps the link listed as live', async () => {
    const { http, cmp, openWith } = await setup();
    openWith([liveShare()]);
    cmp.revoke('sh-1');
    http.expectOne((r) => r.method === 'DELETE').flush({}, { status: 404, statusText: 'Not Found' });
    expect(cmp.revoking()).toBeNull();
    expect(cmp.shares()[0].revokedAt).toBeNull();
  });

  it('shows an empty list rather than a stale one when the listing fails', async () => {
    const { http, detectChanges, host, cmp } = await setup();
    host.open.set(true);
    detectChanges();
    expect(cmp.loading()).toBe(true);
    http.expectOne(LIST).flush({}, { status: 403, statusText: 'Forbidden' });
    expect(cmp.loading()).toBe(false);
    expect(cmp.shares()).toEqual([]);
  });

  it('clears the copyable link when that very link is revoked, keeps it for another', async () => {
    const { http, cmp, openWith } = await setup();
    openWith([liveShare({ id: 'sh-old' })]);
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ id: 'sh-new', url: 'https://x/s/new' }));

    cmp.revoke('sh-old');
    http.expectOne((r) => r.method === 'DELETE').flush(liveShare({ id: 'sh-old', revokedAt: 'x' }));
    expect(cmp.freshUrl()).toBe('https://x/s/new');

    cmp.revoke('sh-new');
    http.expectOne((r) => r.method === 'DELETE').flush(liveShare({ id: 'sh-new', revokedAt: 'x' }));
    expect(cmp.freshUrl()).toBeNull();
  });

  it('does nothing while a create or a revoke is already in flight', async () => {
    const { http, cmp, openWith } = await setup();
    openWith([liveShare()]);
    cmp.create();
    cmp.create();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    cmp.revoke('sh-1');
    cmp.revoke('sh-1');
    http.expectOne((r) => r.method === 'DELETE').flush(liveShare({ revokedAt: 'x' }));
    http.verify();
  });

  it('makes no request at all without an application', async () => {
    const { http, detectChanges, host, cmp } = await setup();
    host.id.set(null);
    host.open.set(true);
    detectChanges();
    cmp.create();
    cmp.revoke('sh-1');
    http.verify();
  });

  it('drops a late listing of an application it no longer shows', async () => {
    const { http, detectChanges, host, cmp } = await setup();
    host.open.set(true);
    detectChanges();
    const first = http.expectOne(LIST);
    host.id.set('app-2');
    detectChanges();
    const second = http.expectOne((r) => r.url === '/api/applications/app-2/shares');
    first.flush([liveShare({ label: 'alt' })]);
    expect(cmp.shares()).toEqual([]);
    second.flush([liveShare({ label: 'neu' })]);
    expect(cmp.shares()[0].label).toBe('neu');
    // A late error of the old listing changes nothing either.
    host.id.set('app-3');
    detectChanges();
    const third = http.expectOne((r) => r.url === '/api/applications/app-3/shares');
    host.id.set('app-4');
    detectChanges();
    third.flush({}, { status: 500, statusText: 'x' });
    expect(cmp.loading()).toBe(true);
    http.expectOne((r) => r.url === '/api/applications/app-4/shares').flush([]);
  });
});
