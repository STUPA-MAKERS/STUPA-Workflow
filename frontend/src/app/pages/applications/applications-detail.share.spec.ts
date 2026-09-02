/**
 * Public share links on the application detail page.
 *
 * Its own spec file for the same reason as the PDF/comments one: the base spec is
 * already large, and a single file compiles this component past the jest timeout under
 * `--coverage`.
 *
 * What matters here is what the UI promises about the token. It is shown once, the server
 * keeps a hash, and a listing can never hand it back — so a test that only checked "a
 * dialog opens" would miss the whole point.
 */
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject } from 'rxjs';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type {
  ApplicationOutWire,
  ApplicationShareLink,
  StateOutWire,
  VersionOutWire,
} from '@core/api/models';

const SUBMITTED: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};

function appWire(): ApplicationOutWire {
  return {
    id: 'app-1',
    typeId: 't1',
    state: SUBMITTED,
    gremiumId: null,
    budgetPotId: null,
    amount: '250.00',
    currency: 'EUR',
    data: { title: 'Förderung Fest' },
    version: 2,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T11:00:00Z',
    applicant: null,
  };
}

const VERSIONS: VersionOutWire[] = [
  { version: 1, data: { title: 'Fest' }, diff: null, changedBy: 'Mia', at: '2026-06-05T10:00:00Z' },
];

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

function fakeAuth(permissions: string[]): Partial<AuthService> {
  return {
    can: (p: string) => permissions.includes(p),
    roles: (() => []) as unknown as AuthService['roles'],
  };
}

async function setup(permissions: string[] = ['application.read', 'application.share']) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(permissions) },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: new BehaviorSubject(convertToParamMap({ id: 'app-1' })) },
      },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, http, cmp: view.fixture.componentInstance };
}

const url =
  (suffix: string) =>
  (r: { url: string }) =>
    r.url === `/api/applications/app-1${suffix}`;

/** Answer every request of one page load. */
function flushPage(http: HttpTestingController) {
  http.expectOne(url('')).flush(appWire());
  http.expectOne(url('/versions')).flush(VERSIONS);
  http.expectOne(url('/comments')).flush([]);
  http
    .expectOne(url('/form'))
    .flush({ applicationTypeId: 't1', formVersionId: 'fv1', sections: [] });
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
}

/** The attachments panel and the budget list load on their own schedule. */
function flushRest(http: HttpTestingController) {
  for (const req of http.match((r) => /\/attachments$/.test(r.url) || r.url === '/api/budgets')) {
    req.flush([]);
  }
}

describe('ApplicationsDetailComponent — share links', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('hides the share action from someone who may only read', async () => {
    // Reading an application and deciding it may be read by anyone holding a URL are
    // different decisions. The server gates on `application.share`; so does the button.
    const { http, detectChanges } = await setup(['application.read', 'application.manage']);
    flushPage(http);
    detectChanges();

    expect(screen.queryByRole('button', { name: 'Teilen' })).not.toBeInTheDocument();
    flushRest(http);
  });

  it('offers the share action to a holder of application.share', async () => {
    const { http, detectChanges } = await setup();
    flushPage(http);
    detectChanges();

    expect(screen.getByRole('button', { name: 'Teilen' })).toBeInTheDocument();
    flushRest(http);
  });

  it('lists the existing links when the dialog opens', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare()]);
    detectChanges();

    expect(screen.getByText('An die Fachschaft')).toBeInTheDocument();
    flushRest(http);
  });

  it('shows a freshly minted link once, and nothing before there is one', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    detectChanges();
    // Nothing to copy yet: the token exists only in the response to the create call.
    expect(screen.queryByRole('button', { name: 'Kopieren' })).not.toBeInTheDocument();

    cmp.createShare();
    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/shares');
    post.flush(liveShare({ url: 'https://x.example/s/token-abc' }));
    detectChanges();

    expect(screen.getByDisplayValue('https://x.example/s/token-abc')).toBeInTheDocument();
    flushRest(http);
  });

  it('sends the chosen lifetime and drops an empty note', async () => {
    // An empty label must not travel as `""`: the server would store a blank note where
    // "no note" is what the user meant.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.shareTtl.set('7');
    cmp.shareLabel.set('   ');
    cmp.createShare();

    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/shares');
    expect(post.request.body).toEqual({ ttlDays: 7 });
    post.flush(liveShare({ url: 'https://x.example/s/t' }));
    flushRest(http);
  });

  it('copies the fresh link to the clipboard', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http
      .expectOne((r) => r.method === 'POST')
      .flush(liveShare({ url: 'https://x.example/s/token-abc' }));
    detectChanges();

    await userEvent.click(screen.getByRole('button', { name: 'Kopieren' }));
    expect(writeText).toHaveBeenCalledWith('https://x.example/s/token-abc');
    flushRest(http);
  });

  it('survives a browser without the clipboard API', async () => {
    Object.assign(navigator, { clipboard: undefined });
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    detectChanges();

    expect(() => cmp.copyShareUrl()).not.toThrow();
    expect(cmp.shareCopied()).toBe(false);
    flushRest(http);
  });

  it('replaces a revoked link in place rather than dropping it from the list', async () => {
    // "Revocable" only means something if you can see what you revoked.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare()]);
    cmp.revokeShare('sh-1');
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-1/shares/sh-1')
      .flush(liveShare({ revokedAt: '2026-06-06T10:00:00Z' }));
    detectChanges();

    expect(cmp.shares()).toHaveLength(1);
    expect(cmp.shares()[0].revokedAt).toBe('2026-06-06T10:00:00Z');
    // No revoke button on a link that no longer opens.
    expect(screen.queryByRole('button', { name: 'Zurückziehen' })).not.toBeInTheDocument();
    flushRest(http);
  });

  it('treats an expired link as dead even though it was never revoked', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare({ expiresAt: '2020-01-01T00:00:00Z' })]);
    detectChanges();

    expect(screen.queryByRole('button', { name: 'Zurückziehen' })).not.toBeInTheDocument();
    flushRest(http);
  });

  it('forgets the token when the dialog is reopened', async () => {
    // The plaintext is gone for good once the dialog closes. Showing a stale one on the
    // next open would promise a link the server can no longer confirm.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    expect(cmp.freshShareUrl()).toBe('https://x/s/t');

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    expect(cmp.freshShareUrl()).toBeNull();
    flushRest(http);
  });

  it('reports a failed create instead of leaving the button spinning', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http
      .expectOne((r) => r.method === 'POST')
      .flush({ code: 'forbidden' }, { status: 403, statusText: 'Forbidden' });

    expect(cmp.creatingShare()).toBe(false);
    expect(cmp.freshShareUrl()).toBeNull();
    flushRest(http);
  });

  it('reports a failed revoke and keeps the link listed as live', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare()]);
    cmp.revokeShare('sh-1');
    http
      .expectOne((r) => r.method === 'DELETE')
      .flush({ code: 'not_found' }, { status: 404, statusText: 'Not Found' });

    expect(cmp.revokingShare()).toBeNull();
    expect(cmp.shares()[0].revokedAt).toBeNull();
    flushRest(http);
  });

  it('shows an empty list rather than a stale one when the listing fails', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http
      .expectOne(url('/shares'))
      .flush({ code: 'forbidden' }, { status: 403, statusText: 'Forbidden' });
    detectChanges();

    expect(cmp.sharesLoading()).toBe(false);
    expect(cmp.shares()).toEqual([]);
    flushRest(http);
  });
  it('clears the copyable link when that very link is revoked', async () => {
    // Leaving it on screen would offer a URL that no longer opens anything.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));
    expect(cmp.freshShareUrl()).toBe('https://x/s/t');

    cmp.revokeShare('sh-1');
    http
      .expectOne((r) => r.method === 'DELETE')
      .flush(liveShare({ revokedAt: '2026-06-06T10:00:00Z' }));

    expect(cmp.freshShareUrl()).toBeNull();
    flushRest(http);
  });

  it('keeps the copyable link when a different one is revoked', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare({ id: 'sh-old' })]);
    cmp.createShare();
    http
      .expectOne((r) => r.method === 'POST')
      .flush(liveShare({ id: 'sh-new', url: 'https://x/s/new' }));

    cmp.revokeShare('sh-old');
    http
      .expectOne((r) => r.method === 'DELETE')
      .flush(liveShare({ id: 'sh-old', revokedAt: '2026-06-06T10:00:00Z' }));

    expect(cmp.freshShareUrl()).toBe('https://x/s/new');
    flushRest(http);
  });

  it('names a link without a note rather than showing an empty row', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare({ label: null })]);
    detectChanges();

    expect(screen.getByText('Ohne Notiz')).toBeInTheDocument();
    flushRest(http);
  });

  it('says when a link was withdrawn, not only that it was', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare({ revokedAt: '2026-06-06T10:00:00Z' })]);
    detectChanges();

    expect(screen.getByText(/Zurückgezogen am/)).toBeInTheDocument();
    flushRest(http);
  });

  it('says when an expired link ran out', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare({ expiresAt: '2020-01-01T00:00:00Z' })]);
    detectChanges();

    expect(screen.getByText(/Abgelaufen am/)).toBeInTheDocument();
    flushRest(http);
  });

  it('does nothing while a create or a revoke is already in flight', async () => {
    // The guards keep a double click from minting two links or racing two revokes.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([liveShare()]);

    cmp.createShare();
    cmp.createShare();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));

    cmp.revokeShare('sh-1');
    cmp.revokeShare('sh-1');
    http.expectOne((r) => r.method === 'DELETE').flush(liveShare({ revokedAt: 'x' }));

    flushRest(http);
    http.verify();
  });
  it('marks the link as not copied when the clipboard write is refused', async () => {
    // A denied clipboard permission must not leave "Kopiert" on the button.
    const writeText = jest.fn().mockRejectedValue(new Error('denied'));
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));

    cmp.copyShareUrl();
    await Promise.resolve();
    expect(cmp.shareCopied()).toBe(false);
    flushRest(http);
  });

  it('copies nothing when there is no fresh link', async () => {
    const writeText = jest.fn();
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.copyShareUrl();
    expect(writeText).not.toHaveBeenCalled();
    flushRest(http);
  });

  it('makes no request at all when the application is not loaded', async () => {
    // Every share call reads the application for its id. Without one there is nothing to
    // share, and firing a request against `undefined` would 404 in the user\'s face.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();
    flushRest(http);

    cmp.app.set(null);
    cmp.openShareDialog();
    cmp.createShare();
    cmp.revokeShare('sh-1');

    http.verify();
  });
  it('marks the link as not copied when the clipboard write is refused', async () => {
    // A denied clipboard permission must not leave "Kopiert" on the button.
    const writeText = jest.fn().mockRejectedValue(new Error('denied'));
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.openShareDialog();
    http.expectOne(url('/shares')).flush([]);
    cmp.createShare();
    http.expectOne((r) => r.method === 'POST').flush(liveShare({ url: 'https://x/s/t' }));

    cmp.copyShareUrl();
    await Promise.resolve();
    expect(cmp.shareCopied()).toBe(false);
    flushRest(http);
  });

  it('copies nothing when there is no fresh link', async () => {
    const writeText = jest.fn();
    Object.assign(navigator, { clipboard: { writeText } });
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();

    cmp.copyShareUrl();
    expect(writeText).not.toHaveBeenCalled();
    flushRest(http);
  });

  it('makes no request at all when the application is not loaded', async () => {
    // Every share call reads the application for its id. Without one there is nothing to
    // share, and firing a request at an undefined id would 404 in the user's face.
    const { http, detectChanges, cmp } = await setup();
    flushPage(http);
    detectChanges();
    flushRest(http);

    cmp.app.set(null);
    cmp.openShareDialog();
    cmp.createShare();
    cmp.revokeShare('sh-1');

    http.verify();
  });
});
