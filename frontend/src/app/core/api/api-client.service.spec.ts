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
    expect(req.request.body).toEqual({ choice: 'yes', asDelegation: false });
    req.flush({ status: 'cast' });
  });

  it('POSTs a delegated ballot with asDelegation=true', () => {
    api.castBallot('v1', 'no', true).subscribe();
    const req = http.expectOne('/api/votes/v1/ballot');
    expect(req.request.body).toEqual({ choice: 'no', asDelegation: true });
    req.flush({ status: 'changed' });
  });

  // --- auth / calendar -----------------------------------------------------
  it('POSTs an empty body to /auth/logout', () => {
    api.logout().subscribe();
    const req = http.expectOne('/api/auth/logout');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush({ logout_url: null });
  });

  it('GETs my calendar feed', (done) => {
    api.myCalendar().subscribe((feed) => {
      expect(feed.url).toBeNull();
      done();
    });
    const req = http.expectOne('/api/calendar/me');
    expect(req.request.method).toBe('GET');
    req.flush({ url: null });
  });

  it('POSTs to rotate the calendar feed token', (done) => {
    api.rotateCalendar().subscribe((feed) => {
      expect(feed.url).toContain('ics');
      done();
    });
    const req = http.expectOne('/api/calendar/me/rotate');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush({ url: 'https://example/feed.ics?t=abc' });
  });

  // --- forms ---------------------------------------------------------------
  it('GETs the effective form WITHOUT a budgetPotId param when none given', () => {
    api.effectiveForm('type-1').subscribe();
    const req = http.expectOne((r) => r.url === '/api/application-types/type-1/form');
    expect(req.request.params.keys()).toHaveLength(0);
    req.flush({ applicationTypeId: 'type-1', formVersionId: 'v1', sections: [] });
  });

  it('GETs the pinned form for an existing application', () => {
    api.applicationForm('app-1').subscribe();
    const req = http.expectOne('/api/applications/app-1/form');
    expect(req.request.method).toBe('GET');
    req.flush({ applicationTypeId: 't1', formVersionId: 'v1', sections: [] });
  });

  // --- applications list extras --------------------------------------------
  it('lists applications with no query (default {} param, no query params)', () => {
    api.listApplications().subscribe();
    const req = http.expectOne((r) => r.url === '/api/applications');
    expect(req.request.params.keys()).toHaveLength(0);
    req.flush({ items: [], total: 0, limit: 20, offset: 0 });
  });

  it('exports xlsx with no query (default {} param)', () => {
    api.exportApplicationsXlsx().subscribe();
    const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
    expect(req.request.params.keys()).toHaveLength(0);
    req.flush(new Blob(['x']));
  });

  it('skips null/undefined query values when serialising the list query', () => {
    api.listApplications({ state: undefined, q: null as unknown as string, limit: 5 }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/applications');
    expect(req.request.params.has('state')).toBe(false);
    expect(req.request.params.has('q')).toBe(false);
    expect(req.request.params.get('limit')).toBe('5');
    req.flush({ items: [], total: 0, limit: 5, offset: 0 });
  });

  it('exports xlsx as a Blob, dropping limit/offset but keeping filters', (done) => {
    api
      .exportApplicationsXlsx({ state: 'draft', q: 'x', limit: 50, offset: 10 })
      .subscribe((blob) => {
        expect(blob).toBeInstanceOf(Blob);
        done();
      });
    const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
    expect(req.request.responseType).toBe('blob');
    expect(req.request.params.get('state')).toBe('draft');
    expect(req.request.params.get('q')).toBe('x');
    expect(req.request.params.has('limit')).toBe(false);
    expect(req.request.params.has('offset')).toBe(false);
    req.flush(new Blob(['x']));
  });

  it('skips null/undefined values from the export query', () => {
    api.exportApplicationsXlsx({ state: undefined }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/applications/export.xlsx');
    expect(req.request.params.has('state')).toBe(false);
    req.flush(new Blob(['x']));
  });

  it('lists tasks and maps each item', (done) => {
    api.listTasks().subscribe((tasks) => {
      expect(tasks).toHaveLength(1);
      expect(tasks[0].state?.label).toBe('Eingereicht');
      done();
    });
    const req = http.expectOne('/api/applications/tasks');
    expect(req.request.method).toBe('GET');
    req.flush([
      {
        id: 'a1',
        typeId: 't1',
        state: STATE,
        amount: '10.00',
        currency: 'EUR',
        createdAt: '2026-06-05T10:00:00Z',
        updatedAt: '2026-06-05T10:00:00Z',
      },
    ]);
  });

  // --- altcha (success + 404 → null + other error rethrow) -----------------
  it('returns the altcha challenge when the endpoint succeeds', (done) => {
    api.altchaChallenge().subscribe((c) => {
      expect(c).toEqual({ algorithm: 'SHA-256', challenge: 'ch', salt: 's', signature: 'sig' });
      done();
    });
    http
      .expectOne('/api/altcha/challenge')
      .flush({ algorithm: 'SHA-256', challenge: 'ch', salt: 's', signature: 'sig' });
  });

  it('maps a 404 from altcha to null (captcha disabled)', (done) => {
    api.altchaChallenge().subscribe((c) => {
      expect(c).toBeNull();
      done();
    });
    http
      .expectOne('/api/altcha/challenge')
      .flush(null, { status: 404, statusText: 'Not Found' });
  });

  it('rethrows non-404 altcha errors', (done) => {
    api.altchaChallenge().subscribe({
      error: (err: { status: number }) => {
        expect(err.status).toBe(500);
        done();
      },
    });
    http
      .expectOne('/api/altcha/challenge')
      .flush(null, { status: 500, statusText: 'Server Error' });
  });

  // --- delete / erasure ----------------------------------------------------
  it('DELETEs an application', () => {
    api.deleteApplication('app-1').subscribe();
    const req = http.expectOne('/api/applications/app-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('POSTs a DSGVO erasure request', () => {
    api.requestErasure('app-1').subscribe();
    const req = http.expectOne('/api/applications/app-1/erasure-request');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(null);
  });

  // --- transitions (regular + applicant) -----------------------------------
  it('maps the transition list', (done) => {
    api.transitions('app-1').subscribe((ts) => {
      expect(ts[0].label).toBe('In Prüfung');
      done();
    });
    const req = http.expectOne('/api/applications/app-1/transitions');
    expect(req.request.method).toBe('GET');
    req.flush([
      { id: 'tr1', fromStateId: 's1', toStateId: 's2', label: { de: 'In Prüfung', en: 'Review' } },
    ]);
  });

  it('maps the applicant transition list', (done) => {
    api.applicantTransitions('app-1').subscribe((ts) => {
      expect(ts[0].id).toBe('tr2');
      done();
    });
    const req = http.expectOne('/api/applications/app-1/applicant-transitions');
    expect(req.request.method).toBe('GET');
    req.flush([
      { id: 'tr2', fromStateId: 's1', toStateId: 's3', label: { de: 'Zurückziehen' } },
    ]);
  });

  it('POSTs an applicant transition', () => {
    api.fireApplicantTransition('app-1', { transitionId: 'tr2' }).subscribe();
    const req = http.expectOne('/api/applications/app-1/applicant-transition');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ transitionId: 'tr2' });
    req.flush({ newStateId: 's3', statusEventId: 'e1', dispatchedActions: [] });
  });

  // --- attachments extras --------------------------------------------------
  it('uploads an attachment with a field key (and not a comparison offer)', () => {
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    api.uploadAttachment('app-1', file, { fieldKey: 'invoice' }).subscribe();
    const req = http.expectOne('/api/applications/app-1/attachments');
    const form = req.request.body as FormData;
    expect(form.get('field_key')).toBe('invoice');
    expect(form.has('is_comparison_offer')).toBe(false);
    req.flush(
      { id: 'att-1', filename: 'a.pdf', mime: 'application/pdf', size: 1, scanned: false, is_comparison_offer: false },
      { status: 201, statusText: 'Created' },
    );
  });

  it('uploads an attachment with no opts (neither field_key nor offer flag)', () => {
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    api.uploadAttachment('app-1', file).subscribe();
    const req = http.expectOne('/api/applications/app-1/attachments');
    const form = req.request.body as FormData;
    expect(form.has('field_key')).toBe(false);
    expect(form.has('is_comparison_offer')).toBe(false);
    req.flush(
      { id: 'att-1', filename: 'a.pdf', mime: 'application/pdf', size: 1, scanned: true, is_comparison_offer: false },
      { status: 201, statusText: 'Created' },
    );
  });

  it('lists attachments and maps them', (done) => {
    api.listAttachments('app-1').subscribe((list) => {
      expect(list).toHaveLength(1);
      expect(list[0].scanState).toBe('clean');
      done();
    });
    const req = http.expectOne('/api/applications/app-1/attachments');
    expect(req.request.method).toBe('GET');
    req.flush([
      { id: 'att-1', filename: 'a.pdf', mime: 'application/pdf', size: 1, scanned: true, is_comparison_offer: false },
    ]);
  });

  it('DELETEs an attachment', () => {
    api.deleteAttachment('att-1').subscribe();
    const req = http.expectOne('/api/attachments/att-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  // --- meetings ------------------------------------------------------------
  function meetingWire(over: Partial<import('./models').MeetingOutWire> = {}): import('./models').MeetingOutWire {
    return {
      id: 'm-1',
      title: 'Sitzung',
      status: 'live',
      votes: [],
      createdAt: '2026-06-12T17:00:00Z',
      ...over,
    } as import('./models').MeetingOutWire;
  }

  it('creates a meeting and maps it', (done) => {
    api.createMeeting({ title: 'Neu' }).subscribe((m) => {
      expect(m.title).toBe('Sitzung');
      done();
    });
    const req = http.expectOne('/api/meetings');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ title: 'Neu' });
    req.flush(meetingWire());
  });

  it('lists meeting members (no mapping)', (done) => {
    api.listMeetingMembers('g-1').subscribe((members) => {
      expect(members).toEqual([{ principalId: 'p-1', displayName: 'Mia' }]);
      done();
    });
    const req = http.expectOne('/api/gremien/g-1/meeting-members');
    expect(req.request.method).toBe('GET');
    req.flush([{ principalId: 'p-1', displayName: 'Mia' }]);
  });

  it('lists meetings without a gremium filter and maps them', (done) => {
    api.listMeetings().subscribe((ms) => {
      expect(ms).toHaveLength(1);
      done();
    });
    const req = http.expectOne((r) => r.url === '/api/meetings');
    expect(req.request.params.has('gremiumId')).toBe(false);
    req.flush([meetingWire()]);
  });

  it('lists meetings with a gremium filter param', () => {
    api.listMeetings('g-9').subscribe();
    const req = http.expectOne((r) => r.url === '/api/meetings');
    expect(req.request.params.get('gremiumId')).toBe('g-9');
    req.flush([]);
  });

  it('fetches the meetings timeline with only the direction (minimal opts)', (done) => {
    api.listMeetingsTimeline({ direction: 'upcoming' }).subscribe((page) => {
      expect(page.items).toEqual([]);
      expect(page.nextCursor).toBeNull();
      done();
    });
    const req = http.expectOne((r) => r.url === '/api/meetings/timeline');
    expect(req.request.params.get('direction')).toBe('upcoming');
    expect(req.request.params.has('cursor')).toBe(false);
    expect(req.request.params.has('q')).toBe(false);
    req.flush({ items: [], nextCursor: null });
  });

  it('fetches the meetings timeline with all optional params', () => {
    api
      .listMeetingsTimeline({ direction: 'past', cursor: 'c1', limit: 10, gremiumId: 'g-1', q: '  hi  ' })
      .subscribe();
    const req = http.expectOne((r) => r.url === '/api/meetings/timeline');
    expect(req.request.params.get('direction')).toBe('past');
    expect(req.request.params.get('cursor')).toBe('c1');
    expect(req.request.params.get('limit')).toBe('10');
    expect(req.request.params.get('gremiumId')).toBe('g-1');
    expect(req.request.params.get('q')).toBe('hi'); // trimmed
    req.flush({ items: [meetingWire()], nextCursor: 'c2' });
  });

  it('omits a whitespace-only q from the timeline query', () => {
    api.listMeetingsTimeline({ direction: 'upcoming', q: '   ' }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/meetings/timeline');
    expect(req.request.params.has('q')).toBe(false);
    req.flush({ items: [], nextCursor: null });
  });

  it('lists the meeting-filter gremien (no mapping)', (done) => {
    api.listMeetingFilterGremien().subscribe((g) => {
      expect(g).toEqual([{ id: 'g-1', name: 'STUPA' }]);
      done();
    });
    const req = http.expectOne('/api/meetings/gremien');
    expect(req.request.method).toBe('GET');
    req.flush([{ id: 'g-1', name: 'STUPA' }]);
  });

  it('fetches a single meeting and maps it', (done) => {
    api.getMeeting('m-1').subscribe((m) => {
      expect(m.id).toBe('m-1');
      done();
    });
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('GET');
    req.flush(meetingWire());
  });

  it('PATCHes a meeting and maps it', () => {
    api.patchMeeting('m-1', { status: 'closed' }).subscribe();
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ status: 'closed' });
    req.flush(meetingWire({ status: 'closed' }));
  });

  it('DELETEs a meeting', () => {
    api.deleteMeeting('m-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  // --- attendance ----------------------------------------------------------
  it('lists attendance (no mapping)', (done) => {
    api.listAttendance('m-1').subscribe((a) => {
      expect(a).toEqual([]);
      done();
    });
    const req = http.expectOne('/api/meetings/m-1/attendance');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('PUTs own attendance', () => {
    api.setOwnAttendance('m-1', 'present').subscribe();
    const req = http.expectOne('/api/meetings/m-1/attendance/me');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ status: 'present' });
    req.flush([]);
  });

  it('PUTs a member attendance', () => {
    api.setMemberAttendance('m-1', 'p-2', 'excused').subscribe();
    const req = http.expectOne('/api/meetings/m-1/attendance/p-2');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ status: 'excused' });
    req.flush([]);
  });

  // --- agenda --------------------------------------------------------------
  it('lists the agenda', () => {
    api.listAgenda('m-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('lists assignable applications', () => {
    api.listAssignableApplications('m-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda/assignable');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('adds an application agenda item', () => {
    api.addAgendaItem('m-1', 'app-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ applicationId: 'app-1' });
    req.flush([]);
  });

  it('adds a freetext agenda item', () => {
    api.addAgendaFreetext('m-1', 'Sonstiges').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ title: 'Sonstiges' });
    req.flush([]);
  });

  it('removes an agenda item', () => {
    api.removeAgendaItem('m-1', 'ag-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda/ag-1');
    expect(req.request.method).toBe('DELETE');
    req.flush([]);
  });

  it('sets an agenda item body (markdown)', () => {
    api.setAgendaBody('m-1', 'ag-1', '## Text').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda/ag-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ body: '## Text' });
    req.flush([]);
  });

  it('renames an agenda item', () => {
    api.renameAgendaItem('m-1', 'ag-1', 'Neuer Titel').subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda/ag-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ title: 'Neuer Titel' });
    req.flush([]);
  });

  it('toggles an agenda item non-public flag', () => {
    api.setAgendaNonPublic('m-1', 'ag-1', true).subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda/ag-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ nonPublic: true });
    req.flush([]);
  });

  it('reorders the agenda', () => {
    api.reorderAgenda('m-1', ['ag-2', 'ag-1']).subscribe();
    const req = http.expectOne('/api/meetings/m-1/agenda/order');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ itemIds: ['ag-2', 'ag-1'] });
    req.flush([]);
  });

  // --- meeting votes -------------------------------------------------------
  it('opens a meeting vote and maps the meeting', (done) => {
    api
      .openMeetingVote('m-1', { agendaItemId: 'ag-1', question: 'Beschluss?', majorityRule: 'simple' })
      .subscribe((m) => {
        expect(m.id).toBe('m-1');
        done();
      });
    const req = http.expectOne('/api/meetings/m-1/votes');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ agendaItemId: 'ag-1', question: 'Beschluss?', majorityRule: 'simple' });
    req.flush(meetingWire());
  });

  it('deletes a meeting vote and maps the meeting', () => {
    api.deleteMeetingVote('m-1', 'v-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1/votes/v-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(meetingWire());
  });

  it('opens a vote (POST empty body)', () => {
    api.openVote('v-1').subscribe();
    const req = http.expectOne('/api/votes/v-1/open');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(null);
  });

  it('closes a vote', () => {
    api.closeVote('v-1').subscribe();
    const req = http.expectOne('/api/votes/v-1/close');
    expect(req.request.method).toBe('POST');
    req.flush(null);
  });

  it('cancels a vote', () => {
    api.cancelVote('v-1').subscribe();
    const req = http.expectOne('/api/votes/v-1/cancel');
    expect(req.request.method).toBe('POST');
    req.flush(null);
  });

  // --- site config ---------------------------------------------------------
  it('GETs the public site config', (done) => {
    api.publicSiteConfig().subscribe((c) => {
      expect(c).toEqual({ name: 'STUPA' });
      done();
    });
    const req = http.expectOne('/api/site-config');
    expect(req.request.method).toBe('GET');
    req.flush({ name: 'STUPA' });
  });

  // --- protocol ------------------------------------------------------------
  function protocolWire(): import('./models').ProtocolOutWire {
    return { id: 'p-1', meetingId: 'm-1', markdown: '# x', status: 'draft' };
  }

  it('loads (POSTs) a protocol and maps it', (done) => {
    api.loadProtocol('m-1').subscribe((p) => {
      expect(p.isFinal).toBe(false);
      done();
    });
    const req = http.expectOne('/api/meetings/m-1/protocol');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(protocolWire());
  });

  it('GETs a protocol and maps it', () => {
    api.getProtocol('m-1').subscribe();
    const req = http.expectOne('/api/meetings/m-1/protocol');
    expect(req.request.method).toBe('GET');
    req.flush(protocolWire());
  });

  it('PATCHes protocol markdown', () => {
    api.updateProtocol('p-1', '# neu').subscribe();
    const req = http.expectOne('/api/protocols/p-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ markdown: '# neu' });
    req.flush(protocolWire());
  });

  it('embeds votes into a protocol', () => {
    api.embedVotes('p-1', ['v-1', 'v-2']).subscribe();
    const req = http.expectOne('/api/protocols/p-1/votes');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ voteIds: ['v-1', 'v-2'] });
    req.flush(protocolWire());
  });

  it('finalizes a protocol', (done) => {
    api.finalizeProtocol('p-1').subscribe((p) => {
      expect(p.isFinal).toBe(true);
      done();
    });
    const req = http.expectOne('/api/protocols/p-1/finalize');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush({ id: 'p-1', meetingId: 'm-1', markdown: '# x', status: 'final' });
  });

  // --- notification preferences --------------------------------------------
  it('lists notification preferences', (done) => {
    api.listNotificationPreferences().subscribe((prefs) => {
      expect(prefs).toEqual([]);
      done();
    });
    const req = http.expectOne('/api/notifications/preferences');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('sets notification preferences (bulk PUT)', () => {
    const prefs = [{ key: 'app.submitted', email: true, inApp: false }] as unknown as import('./models').NotificationPreference[];
    api.setNotificationPreferences(prefs).subscribe();
    const req = http.expectOne('/api/notifications/preferences');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ preferences: prefs });
    req.flush(prefs);
  });

  // --- oauth grants + consent + mcp ----------------------------------------
  it('lists oauth grants', () => {
    api.listGrants().subscribe();
    const req = http.expectOne('/api/oauth/grants');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('revokes a single grant', () => {
    api.revokeGrant('grant-1').subscribe();
    const req = http.expectOne('/api/oauth/grants/grant-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('revokes all grants', () => {
    api.revokeAllGrants().subscribe();
    const req = http.expectOne('/api/oauth/grants');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('GETs the pending consent request', (done) => {
    api.consentRequest().subscribe((c) => {
      expect(c).toEqual({ client: 'agent' });
      done();
    });
    const req = http.expectOne('/api/oauth/consent-request');
    expect(req.request.method).toBe('GET');
    req.flush({ client: 'agent' });
  });

  it('submits a consent decision', (done) => {
    api.submitConsent({ approve: true, scopes: ['read'], lifetime: '30d' }).subscribe((r) => {
      expect(r.redirect).toBe('https://app/cb');
      done();
    });
    const req = http.expectOne('/api/oauth/consent');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ approve: true, scopes: ['read'], lifetime: '30d' });
    req.flush({ redirect: 'https://app/cb' });
  });

  it('GETs the mcp config snippet', () => {
    api.mcpConfig().subscribe();
    const req = http.expectOne('/api/mcp/config');
    expect(req.request.method).toBe('GET');
    req.flush({ mcpServers: {} });
  });

  it('downloads the mcp package as a Blob', (done) => {
    api.downloadMcpPackage().subscribe((blob) => {
      expect(blob).toBeInstanceOf(Blob);
      done();
    });
    const req = http.expectOne('/api/mcp/package');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(['pkg']));
  });
});
