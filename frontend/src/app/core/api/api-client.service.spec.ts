import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ApiClient } from './api-client.service';
import { USE_MOCK_API } from './api.config';
import type {
  ApplicationOutWire,
  ApplicationTypeListItemWire,
  CommentOutWire,
  Page,
  StateOutWire,
  TimelineEventOutWire,
} from './models';

const STATE: StateOutWire = {
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
    state: STATE,
    gremiumId: null,
    budgetPotId: 'p1',
    amount: '10.00',
    currency: 'EUR',
    data: { title: 'X' },
    version: 1,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T10:00:00Z',
  };
}

describe('ApiClient', () => {
  let api: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    api = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('GETs the principal from /api/auth/me', () => {
    api.me().subscribe();
    const req = http.expectOne('/api/auth/me');
    expect(req.request.method).toBe('GET');
    req.flush({ sub: 'x', display_name: 'A', email: 'a@b', roles: [], permissions: [], groups: [] });
  });

  it('unwraps the application-types Page into a mapped array', (done) => {
    const page: Page<ApplicationTypeListItemWire> = {
      items: [
        { id: 't1', name: 'Finanzantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    };
    api.applicationTypes().subscribe((types) => {
      expect(types).toEqual([
        {
          id: 't1',
          name: 'Finanzantrag',
          active: true,
          hasBudget: true,
          activeFormVersionId: 'v1',
          key: null,
          gremiumId: null,
        },
      ]);
      done();
    });
    http.expectOne('/api/application-types').flush(page);
  });

  it('serialises list query params and maps the page items', (done) => {
    api.listApplications({ state: 'draft', q: 'foo', limit: 10 }).subscribe((page) => {
      expect(page.total).toBe(1);
      expect(page.items[0].typeId).toBe('t1');
      expect(page.items[0].state?.label).toBe('Eingereicht');
      done();
    });
    const req = http.expectOne((r) => r.url === '/api/applications');
    expect(req.request.params.get('state')).toBe('draft');
    expect(req.request.params.get('q')).toBe('foo');
    expect(req.request.params.get('limit')).toBe('10');
    req.flush({ items: [appWire()], total: 1, limit: 10, offset: 0 });
  });

  it('maps a single application from the wire DTO', (done) => {
    api.getApplication('app-1').subscribe((app) => {
      expect(app.typeId).toBe('t1');
      expect(app.budgetPotId).toBe('p1');
      expect(app.state?.editAllowed).toBe(true);
      expect(app.createdAt).toBe('2026-06-05T10:00:00Z');
      done();
    });
    http.expectOne('/api/applications/app-1').flush(appWire());
  });

  it('POSTs a camelCase create body and unwraps applicationId', (done) => {
    api
      .createApplication({
        typeId: 't1',
        budgetPotId: 'p1',
        data: { title: 'X' },
        applicantEmail: 'a@b.de',
        applicantName: 'Max',
        lang: 'de',
        altcha: 'sol',
      })
      .subscribe((created) => {
        expect(created).toEqual({ applicationId: 'app-9' });
        done();
      });
    const req = http.expectOne('/api/applications');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      typeId: 't1',
      budgetPotId: 'p1',
      data: { title: 'X' },
      applicantEmail: 'a@b.de',
      applicantName: 'Max',
      lang: 'de',
      altcha: 'sol',
    });
    req.flush({ applicationId: 'app-9' }, { status: 201, statusText: 'Created' });
  });

  it('POSTs a transition with the camelCase transitionId', () => {
    api.fireTransition('app-1', { transitionId: 't-1', note: 'ok' }).subscribe();
    const req = http.expectOne('/api/applications/app-1/transition');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ transitionId: 't-1', note: 'ok' });
    req.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });
  });

  it('maps the timeline events into view entries', (done) => {
    const events: TimelineEventOutWire[] = [
      { fromStateId: null, toStateId: 's1', toState: STATE, actor: null, at: '2026-06-05T10:00:00Z', note: null },
    ];
    api.timeline('app-9').subscribe((entries) => {
      expect(entries[0].label).toBe('Eingereicht');
      expect(entries[0].toStateId).toBe('s1');
      done();
    });
    http.expectOne('/api/applications/app-9/timeline').flush(events);
  });

  it('maps the version history with its diff into iterable lists', (done) => {
    api.versions('app-7').subscribe((versions) => {
      expect(versions).toHaveLength(2);
      expect(versions[0].diff).toBeNull(); // erste Version: kein Diff
      expect(versions[1].changedBy).toBe('Mia');
      expect(versions[1].diff?.added).toEqual([{ key: 'note', value: 'neu' }]);
      expect(versions[1].diff?.changed).toEqual([
        { key: 'title', old: 'Alt', new: 'Neu' },
      ]);
      expect(versions[1].diff?.removed).toEqual([]);
      done();
    });
    const req = http.expectOne('/api/applications/app-7/versions');
    expect(req.request.method).toBe('GET');
    req.flush([
      { version: 1, data: { title: 'Alt' }, diff: null, changedBy: null, at: '2026-06-01T10:00:00Z' },
      {
        version: 2,
        data: { title: 'Neu', note: 'neu' },
        diff: {
          added: { note: 'neu' },
          removed: {},
          changed: { title: { old: 'Alt', new: 'Neu' } },
        },
        changedBy: 'Mia',
        at: '2026-06-02T10:00:00Z',
      },
    ]);
  });

  it('uploads an attachment as multipart FormData and maps the result', (done) => {
    const file = new File(['hello'], 'plan.pdf', { type: 'application/pdf' });
    api.uploadAttachment('app-1', file, { isComparisonOffer: true }).subscribe((att) => {
      expect(att.isComparisonOffer).toBe(true);
      expect(att.scanState).toBe('scanning');
      done();
    });
    const req = http.expectOne('/api/applications/app-1/attachments');
    expect(req.request.method).toBe('POST');
    expect(req.request.body instanceof FormData).toBe(true);
    const form = req.request.body as FormData;
    expect((form.get('file') as File).name).toBe('plan.pdf');
    expect(form.get('is_comparison_offer')).toBe('true');
    req.flush(
      {
        id: 'att-1',
        filename: 'plan.pdf',
        mime: 'application/pdf',
        size: 5,
        scanned: false,
        is_comparison_offer: true,
      },
      { status: 201, statusText: 'Created' },
    );
  });

  it('GETs a signed download URL for an attachment', (done) => {
    api.attachmentUrl('att-9').subscribe((signed) => {
      expect(signed.url).toContain('minio');
      expect(signed.expiresIn).toBe(120);
      done();
    });
    const req = http.expectOne('/api/attachments/att-9');
    expect(req.request.method).toBe('GET');
    req.flush({ url: 'https://minio/att-9?sig=abc', expiresIn: 120 });
  });

  it('propagates a 409 when the attachment is not yet clean', (done) => {
    api.attachmentUrl('att-q').subscribe({
      error: (err: { status: number }) => {
        expect(err.status).toBe(409);
        done();
      },
    });
    http
      .expectOne('/api/attachments/att-q')
      .flush({ title: 'Conflict', status: 409 }, { status: 409, statusText: 'Conflict' });
  });

  it('POSTs the magic-link token to verify (snake_case response)', () => {
    api.verifyMagicLink('tok-1').subscribe();
    const req = http.expectOne('/api/auth/magic-link/verify');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ token: 'tok-1' });
    req.flush({ application_id: 'a', scope: 'edit' });
  });

  it('GETs the effective form with the budgetPotId param (not ?pot)', () => {
    api.effectiveForm('type-1', 'pot-9').subscribe();
    const req = http.expectOne((r) => r.url === '/api/application-types/type-1/form');
    expect(req.request.params.get('budgetPotId')).toBe('pot-9');
    expect(req.request.params.get('pot')).toBeNull();
    req.flush({ applicationTypeId: 'type-1', formVersionId: 'v1', sections: [] });
  });

  it('PATCHes application data and maps the result', (done) => {
    api.updateApplication('app-1', { title: 'Neu' }).subscribe((app) => {
      expect(app.data).toEqual({ title: 'X' });
      done();
    });
    const req = http.expectOne('/api/applications/app-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ data: { title: 'Neu' } });
    req.flush(appWire());
  });

  it('GETs and POSTs comments with mapped view models', (done) => {
    const wire: CommentOutWire = {
      id: 'c1',
      author: 'Referat',
      authorKind: 'principal',
      body: 'Hi',
      visibility: 'public',
      at: '2026-06-05T13:00:00Z',
    };
    api.comments('app-3').subscribe((comments) => {
      expect(comments[0].isPublic).toBe(true);
      expect(comments[0].author).toBe('Referat');
    });
    http.expectOne('/api/applications/app-3/comments').flush([wire]);

    api.addComment('app-3', 'Hallo').subscribe((c) => {
      expect(c.isPublic).toBe(true);
      done();
    });
    const req = http.expectOne('/api/applications/app-3/comments');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ body: 'Hallo', visibility: 'public' });
    req.flush(wire, { status: 201, statusText: 'Created' });
  });

  it('GETs a vote state + tally from /votes/{id}', (done) => {
    api.getVote('v1').subscribe((vote) => {
      expect(vote.status).toBe('open');
      expect(vote.config.options).toEqual(['yes', 'no', 'abstain']);
      expect(vote.tally.counts['yes']).toBe(5);
      done();
    });
    const req = http.expectOne('/api/votes/v1');
    expect(req.request.method).toBe('GET');
    req.flush({
      id: 'v1',
      applicationId: 'app-1',
      eligibleGroup: 'stupa',
      config: { options: ['yes', 'no', 'abstain'], majorityRule: 'two_thirds', allowChange: true },
      status: 'open',
      opensAt: null,
      closesAt: null,
      result: null,
      secret: false,
      tally: { counts: { yes: 5, no: 2, abstain: 1 }, eligible: 12, quorumMet: true, leading: 'yes' },
    });
  });

  it('POSTs a ballot choice to /votes/{id}/ballot', (done) => {
    api.castBallot('v1', 'yes').subscribe((res) => {
      expect(res.status).toBe('cast');
      done();
    });
    const req = http.expectOne('/api/votes/v1/ballot');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ choice: 'yes' });
    req.flush({ status: 'cast' });
  });
});
