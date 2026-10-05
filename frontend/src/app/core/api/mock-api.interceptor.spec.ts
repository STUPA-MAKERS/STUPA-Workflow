import { TestBed } from '@angular/core/testing';
import {
  HttpClient,
  HttpParams,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from './api-client.service';
import { USE_MOCK_API } from './api.config';
import { mockApiInterceptor } from './mock-api.interceptor';

describe('mockApiInterceptor', () => {
  function setup(useMock: boolean): { api: ApiClient; http: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: useMock },
      ],
    });
    return { api: TestBed.inject(ApiClient), http: TestBed.inject(HttpTestingController) };
  }

  it('short-circuits known GET endpoints with canned, mapped data', (done) => {
    const { api, http } = setup(true);
    api.applicationTypes().subscribe((types) => {
      expect(types.length).toBeGreaterThan(0);
      // The mapper turned the wire Page into the view shape with hasBudget.
      expect(typeof types[0].hasBudget).toBe('boolean');
      done();
    });
    http.expectNone((r) => r.url === '/api/application-types');
  });

  it('passes through when the mock is disabled', () => {
    const { api, http } = setup(false);
    api.applicationTypes().subscribe();
    http
      .expectOne((r) => r.url === '/api/application-types')
      .flush({ items: [], total: 0, limit: 20, offset: 0 });
    http.verify();
  });

  it('passes through requests that are not /api/ (mock enabled)', () => {
    const { http } = setup(true);
    const client = TestBed.inject(HttpClient);
    client.get('/assets/logo.svg', { responseType: 'text' }).subscribe();
    http.expectOne('/assets/logo.svg').flush('<svg/>');
    http.verify();
  });

  it('passes through unmatched /api/ methods/paths (final next)', () => {
    const { http } = setup(true);
    const client = TestBed.inject(HttpClient);
    // No branch matches OPTIONS → the request falls through to next().
    client.request('OPTIONS', '/api/unknown').subscribe();
    http.expectOne('/api/unknown').flush(null);
    http.verify();
  });

  it('serves the effective form (with sections) for the apply wizard', (done) => {
    const { api, http } = setup(true);
    api.effectiveForm('22222222-2222-2222-2222-222222222222').subscribe((form) => {
      expect(form.sections.length).toBeGreaterThan(0);
      expect(form.hasBudget).toBe(false);
      done();
    });
    http.expectNone((r) => r.url.includes('/form'));
  });

  it('serves the form of the demo applications for the demo type', async () => {
    const { api } = setup(true);
    const form = await firstValueFrom(api.effectiveForm('11111111-1111-1111-1111-111111111111'));
    expect(form.sections.map((s) => s.key)).toEqual(['plan', 'costs_section', 'contact']);
    expect(form.sections[2].fields.some((f) => f.isPII)).toBe(true);
  });

  it('plays a visitor without a session when mockAnonymous is set', async () => {
    const { api } = setup(true);
    localStorage.setItem('mockAnonymous', '1');
    try {
      await expect(firstValueFrom(api.me())).rejects.toMatchObject({ status: 401 });
    } finally {
      localStorage.removeItem('mockAnonymous');
    }
    await expect(firstValueFrom(api.me())).resolves.toBeTruthy();
    // A storage that throws plays the signed-in user.
    const spy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    try {
      await expect(firstValueFrom(api.me())).resolves.toBeTruthy();
    } finally {
      spy.mockRestore();
    }
  });

  it('answers a draft upload without a form body with a default file', async () => {
    const { http } = setup(true);
    const client = TestBed.inject(HttpClient);
    const res = await firstValueFrom(client.post<Record<string, unknown>>('/api/apply/attachments', {}));
    expect(res).toMatchObject({ mime: 'application/pdf', size: 1024, is_comparison_offer: false });
    expect(String(res['filename'])).toMatch(/^datei-\d+\.pdf$/);
    const form = new FormData();
    form.append('file', new File(['x'], 'ohne-typ'));
    const typeless = await firstValueFrom(client.post<Record<string, unknown>>('/api/apply/attachments', form));
    expect(typeless['mime']).toBe('application/pdf');
    http.verify();
  });

  it('answers a draft upload with the file and a token, and a draft delete', async () => {
    const { api } = setup(true);
    const file = new File(['x'.repeat(10)], 'Angebot.pdf', { type: 'application/pdf' });
    const res = await firstValueFrom(
      api.uploadDraftAttachment(file, { isComparisonOffer: true, altcha: 'sol' }),
    );
    expect(res.attachment).toMatchObject({
      filename: 'Angebot.pdf',
      mime: 'application/pdf',
      size: 10,
      isComparisonOffer: true,
      scanState: 'scanning',
    });
    expect(res.draftToken).toBe('mock-draft-token');
    expect(Date.parse(res.draftExpiresAt)).toBeGreaterThan(Date.now());
    await expect(
      firstValueFrom(api.deleteDraftAttachment(res.attachment.id, res.draftToken)),
    ).resolves.toBeNull();
  });

  it('creates an application returning an applicationId', (done) => {
    const { api } = setup(true);
    api
      .createApplication({
        typeId: '11111111-1111-1111-1111-111111111111',
        data: { title: 'X' },
        applicantEmail: 'a@b.de',
        lang: 'de',
        altcha: 'sol',
      })
      .subscribe((created) => {
        expect(created.applicationId).toBeTruthy();
        done();
      });
  });

  it('verifies a magic-link token and returns an applicant scope', (done) => {
    const { api } = setup(true);
    api.verifyMagicLink('tok').subscribe((res) => {
      expect(res.scope).toBe('edit');
      expect(res.application_id).toBeTruthy();
      done();
    });
  });

  it('serves a single application, its timeline and comments, and accepts a PATCH', (done) => {
    const { api } = setup(true);
    api.getApplication('33333333-3333-3333-3333-333333333333').subscribe((app) => {
      expect(app.state?.editAllowed).toBe(true);
      // The mapper resolved the i18n label (de default).
      expect(app.state?.label).toBe('Eingereicht');
      api.timeline(app.id).subscribe((t) => {
        expect(t.length).toBeGreaterThan(0);
        expect(t[0].label).toBeTruthy();
        api.comments(app.id).subscribe((c) => {
          expect(c.length).toBeGreaterThan(0);
          expect(c[0].isPublic).toBe(true);
          api.addComment(app.id, 'Neu').subscribe((created) => {
            expect(created.isPublic).toBe(true);
            api.updateApplication(app.id, { title: 'Y' }).subscribe((updated) => {
              expect(updated.data).toEqual({ title: 'Y' });
              done();
            });
          });
        });
      });
    });
  });

  describe('mock router branches (raw HttpClient)', () => {
    let http: HttpClient;
    let ctrl: HttpTestingController;

    beforeEach(() => {
      const s = setup(true);
      http = TestBed.inject(HttpClient);
      ctrl = s.http;
    });

    afterEach(() => ctrl.verify());

    function get<T>(url: string, params?: HttpParams): Promise<T> {
      return firstValueFrom(http.get<T>(url, params ? { params } : undefined));
    }

    it('GET /auth/me → mock principal', async () => {
      const me = await get<{ display_name: string; permissions: string[] }>('/api/auth/me');
      expect(me.display_name).toBe('Demo Mitglied');
      expect(me.permissions).toContain('budget.book');
    });

    it('GET /altcha/challenge → 404 error', async () => {
      await expect(get('/api/altcha/challenge')).rejects.toMatchObject({ status: 404 });
    });

    it('GET /application-types/{id}/form → effective form', async () => {
      const form = await get<{ sections: unknown[] }>('/api/application-types/abc/form');
      expect(form.sections.length).toBeGreaterThan(0);
    });

    it('GET …/timeline → events', async () => {
      const events = await get<unknown[]>('/api/applications/x/timeline');
      expect(events.length).toBe(3);
    });

    it('GET /site-config → the platform defaults; the admin config is not this route', async () => {
      const cfg = await get<{ linkTtlDays: number | null; confirmTtlHours: number }>('/api/site-config');
      expect(cfg).toMatchObject({ linkTtlDays: null, confirmTtlHours: 12 });
    });

    it('GET the attachments of the magic-link demo application', async () => {
      const list = await get<unknown[]>('/api/applications/33333333-3333-3333-3333-333333333333/attachments');
      expect(list).toHaveLength(2);
    });

    it('GET …/versions → version history', async () => {
      const v = await get<unknown[]>('/api/applications/x/versions');
      expect(v.length).toBe(2);
    });

    it('GET …/transitions → transitions', async () => {
      const t = await get<unknown[]>('/api/applications/x/transitions');
      expect(t.length).toBe(2);
    });

    it('GET /attachments/{id} → signed url', async () => {
      const s = await get<{ url: string; expiresIn: number }>('/api/attachments/att-1');
      expect(s.url).toContain('minio');
      expect(s.expiresIn).toBe(120);
    });

    it('GET /expenses → the demo bookings, filtered and paged', async () => {
      type E = { id: string; kind: string; budgetId: string; childCount: number };
      const all = await get<{ items: E[]; total: number }>('/api/expenses');
      expect(all.total).toBeGreaterThan(5);
      expect(all.items.some((e) => e.kind === 'income')).toBe(true);
      expect(all.items.some((e) => e.childCount > 0)).toBe(true);

      const income = await get<{ items: E[] }>(
        '/api/expenses',
        new HttpParams().set('kind', 'income'),
      );
      expect(income.items.every((e) => e.kind === 'income')).toBe(true);

      // A cost centre filters its whole subtree: "Fachschaften" holds 210, 220 and 231.
      const sub = await get<{ items: E[] }>(
        '/api/expenses',
        new HttpParams().set('budget', 'b1000000-0000-0000-0000-000000000020'),
      );
      expect(sub.items.length).toBeGreaterThan(0);
      expect(sub.items.every((e) => /0000000000(2\d)$/.test(e.budgetId))).toBe(true);

      const searched = await get<{ items: E[] }>('/api/expenses', new HttpParams().set('q', 'turnier'));
      expect(searched.items.length).toBe(2);

      const paged = await get<{ items: E[]; offset: number }>(
        '/api/expenses',
        new HttpParams().set('limit', '2').set('offset', '2'),
      );
      expect(paged.items).toHaveLength(2);
      expect(paged.offset).toBe(2);
    });

    it('GET sub-bookings, transfers and one invoice → the demo rows', async () => {
      const subs = await get<{ parentExpenseId: string }[]>(
        '/api/budget-expenses/e1000000-0000-0000-0000-000000000002/sub-bookings',
      );
      expect(subs).toHaveLength(2);
      const transfers = await get<{ items: unknown[] }>('/api/budget-transfers');
      expect(transfers.items).toHaveLength(1);
      const inv = await get<{ number: string } | null>(
        '/api/invoices/d1000000-0000-0000-0000-000000000003',
      );
      expect(inv?.number).toBe('SP-88213');
      expect(await get('/api/invoices/unknown')).toBeNull();
    });

    it('GET /invoices → the demo invoices with their bookings', async () => {
      type I = { id: string; status: string; linkedBookings: unknown[] };
      const all = await get<{ items: I[] }>('/api/invoices');
      expect(all.items.some((i) => i.linkedBookings.length > 1)).toBe(true);
      expect(all.items.some((i) => i.linkedBookings.length === 0)).toBe(true);
      const open = await get<{ items: I[] }>('/api/invoices', new HttpParams().set('status', 'open'));
      expect(open.items.every((i) => i.status === 'open')).toBe(true);
      const byId = await get<{ items: I[] }>(
        '/api/invoices',
        new HttpParams().set('id', 'd1000000-0000-0000-0000-000000000002'),
      );
      expect(byId.items).toHaveLength(1);
      const q = await get<{ items: I[] }>('/api/invoices', new HttpParams().set('q', 'neckar'));
      expect(q.items).toHaveLength(1);
    });

    it('GET /invoices → the segments and their counts (FE10c)', async () => {
      type I = { status: string; linkedBookings: unknown[] };
      type P = { items: I[]; counts: { all: number; inbox: number; booked: number; paid: number } };
      const all = await get<P>('/api/invoices');
      const c = all.counts;
      expect(c.all).toBe(all.items.length);
      expect(c.inbox + c.booked + c.paid).toBe(c.all);
      expect(c.inbox).toBeGreaterThan(0);
      expect(c.booked).toBeGreaterThan(0);
      const inbox = await get<P>(
        '/api/invoices',
        new HttpParams().set('status', 'open').set('booked', 'false'),
      );
      expect(inbox.items).toHaveLength(c.inbox);
      expect(inbox.items.every((i) => i.status === 'open' && i.linkedBookings.length === 0)).toBe(true);
      const booked = await get<P>(
        '/api/invoices',
        new HttpParams().set('status', 'open').set('booked', 'true'),
      );
      expect(booked.items.every((i) => i.linkedBookings.length > 0)).toBe(true);
      // The counts ignore the segment itself.
      expect(booked.counts).toEqual(c);
    });

    it('POST /invoices/parse → a known invoice, flagged as a duplicate', async () => {
      const form = new FormData();
      form.append('file', new File(['%PDF'], 'beleg.pdf', { type: 'application/pdf' }));
      const parsed = await firstValueFrom(
        http.post<{ fileName: string; duplicate: boolean }>('/api/invoices/parse', form),
      );
      expect(parsed.fileName).toBe('beleg.pdf');
      expect(parsed.duplicate).toBe(true);
      const bare = await firstValueFrom(
        http.post<{ fileName: string }>('/api/invoices/parse', new FormData()),
      );
      expect(bare.fileName).toBe('rechnung.pdf');
    });

    it('GET /budgets → the demo tree with consistent rollups', async () => {
      type N = { id: string; pathKey: string; color: string | null; children: N[];
        byFiscalYear: { allocated: string; committed: string; income: string; available: string }[] };
      const tree = await get<N[]>('/api/budgets');
      expect(tree).toHaveLength(1);
      const root = tree[0];
      // Path keys join with "-", like the server.
      expect(root.children[1].children[0].pathKey).toBe('HH-200-210');
      // available = allocated - committed + income.
      const a = root.byFiscalYear[0];
      expect(Number(a.available)).toBe(Number(a.allocated) - Number(a.committed) + Number(a.income));
      // One node inherits its colour: it has none of its own under a coloured parent.
      const gestaltung = root.children[1].children[2];
      expect(gestaltung.color).toMatch(/^#/);
      expect(gestaltung.children[0].color).toBeNull();
    });

    it('GET /budgets/{id}/fiscal-years → the years of the demo budget', async () => {
      const fys = await get<{ year: number }[]>('/api/budgets/x/fiscal-years');
      expect(fys.map((f) => f.year)).toEqual([2026, 2025, 2024]);
    });

    it('GET /budgets/{id}/applications → the subtree, filtered by year', async () => {
      type A = { budgetId: string; pathKey: string };
      const root = 'b1000000-0000-0000-0000-000000000001';
      const all = await get<A[]>(`/api/budgets/${root}/applications`);
      expect(all.length).toBe(5);
      const fs = await get<A[]>('/api/budgets/b1000000-0000-0000-0000-000000000020/applications');
      expect(fs.length).toBe(3);
      expect(fs.every((x) => x.pathKey.startsWith('HH-200-'))).toBe(true);
      const old = await get<A[]>(
        `/api/budgets/${root}/applications`,
        new HttpParams().set('fiscalYear', 'f1000000-0000-0000-0000-000000000002'),
      );
      expect(old).toEqual([]);
      expect(await get<A[]>('/api/budgets/unknown/applications')).toEqual([]);
    });

    it('GET /applications/tasks → task list', async () => {
      const tasks = await get<{ stateSince?: string }[]>('/api/applications/tasks');
      expect(tasks.length).toBe(2);
      // One task carries stateSince (A9), one shows the updatedAt fallback.
      expect(tasks[0].stateSince).toBeTruthy();
      expect(tasks[1].stateSince).toBeUndefined();
    });

    describe('demo applications (mock-applications.ts)', () => {
      type Row = { id: string; title: string; amount: string | null; archivedAt: string | null; state: { id: string; key: string } };
      const first = 'a1000000-0000-0000-0000-000000000001';
      const second = 'a1000000-0000-0000-0000-000000000002';

      beforeEach(async () => (await import('./mock-applications')).resetMockApplications());

      it('GET /applications → the demo page, newest first, without archived rows', async () => {
        const page = await get<{ items: Row[]; total: number }>('/api/applications');
        expect(page.total).toBe(15);
        expect(page.items).toHaveLength(15);
        expect(page.items[0].id).toBe(first);
        expect(page.items.some((r) => r.archivedAt)).toBe(false);
      });

      it('filters by state (repeated), type, text, amount, date and archive', async () => {
        const review = '66666666-6666-6666-6666-666666666662';
        const agenda = '66666666-6666-6666-6666-666666666665';
        let params = new HttpParams().append('state', review).append('state', agenda);
        let page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items.every((r) => [review, agenda].includes(r.state.id))).toBe(true);
        expect(page.items.length).toBe(7);

        params = new HttpParams().set('type', '22222222-2222-2222-2222-222222222222').set('q', 'zur');
        page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items.map((r) => r.title)).toEqual([
          'Anreise zur Bundeskonferenz der Studierendenschaften',
          'Bahnfahrt zur Gremienschulung',
        ]);

        params = new HttpParams().set('amountMin', '1000').set('amountMax', '2000');
        page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items.every((r) => Number(r.amount) >= 1000 && Number(r.amount) <= 2000)).toBe(true);

        params = new HttpParams().set('createdFrom', '2026-08-01').set('createdTo', '2026-08-31');
        page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items).toHaveLength(3);

        params = new HttpParams().set('archived', 'true');
        page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items.map((r) => r.title)).toEqual(['Quizabend im Studierendencafé']);
        params = new HttpParams().set('archived', 'all');
        expect((await get<{ total: number }>('/api/applications', params)).total).toBe(16);
      });

      it('sorts by amount and by date in both directions and pages', async () => {
        let params = new HttpParams().set('sort', 'amount').set('order', 'desc');
        let page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items[0].amount).toBe('2260.00');
        params = new HttpParams().set('sort', 'amount').set('order', 'asc');
        page = await get<{ items: Row[] }>('/api/applications', params);
        expect(page.items[0].amount).toBeNull();
        params = new HttpParams().set('order', 'asc').set('limit', '5').set('offset', '5');
        const paged = await get<{ items: Row[]; offset: number; limit: number }>('/api/applications', params);
        expect(paged.items).toHaveLength(5);
        expect(paged.offset).toBe(5);
      });

      it('GET the detail, its transitions, attachments, shares and flow states', async () => {
        const app = await get<{ id: string; data: Record<string, unknown>; applicant: { name: string } }>(
          `/api/applications/${first}`,
        );
        expect(app.id).toBe(first);
        expect(app.applicant.name).toBeTruthy();
        expect(await get<unknown[]>(`/api/applications/${first}/transitions`)).toEqual([]);
        const fromReview = await get<{ addsToAgenda: boolean }[]>(
          '/api/applications/a1000000-0000-0000-0000-000000000004/transitions',
        );
        expect(fromReview.map((t) => t.addsToAgenda)).toEqual([true, false, false]);
        expect(await get<unknown[]>(`/api/applications/${first}/attachments`)).toHaveLength(3);
        expect(await get<unknown[]>(`/api/applications/${second}/attachments`)).toEqual([]);
        expect(await get<unknown[]>(`/api/applications/${first}/shares`)).toEqual([]);
        expect((await get<unknown[]>(`/api/applications/${first}/flow-states`)).length).toBe(5);
      });

      it('answers 404 for an unknown demo id', async () => {
        await expect(get('/api/applications/a1000000-0000-0000-0000-000000009999')).rejects.toMatchObject({
          status: 404,
        });
      });

      it('fires a transition, archives, forces a state, edits and deletes a demo row', async () => {
        const start = (await get<{ id: string }[]>(`/api/applications/${second}/transitions`))[0];
        await firstValueFrom(http.post(`/api/applications/${second}/transition`, { transitionId: start.id }));
        expect((await get<Row>(`/api/applications/${second}`)).state.key).toBe('review');
        // An unknown transition keeps the state.
        await firstValueFrom(http.post(`/api/applications/${second}/transition`, { transitionId: 'x' }));
        expect((await get<Row>(`/api/applications/${second}`)).state.key).toBe('review');

        const archived = await firstValueFrom(http.post<Row>(`/api/applications/${second}/archive`, {}));
        expect(archived.archivedAt).toBeTruthy();
        const back = await firstValueFrom(http.delete<Row>(`/api/applications/${second}/archive`));
        expect(back.archivedAt).toBeNull();

        await firstValueFrom(
          http.post(`/api/applications/${second}/force-status`, { stateId: '66666666-6666-6666-6666-666666666666' }),
        );
        expect((await get<Row>(`/api/applications/${second}`)).state.key).toBe('approved');
        await firstValueFrom(http.post(`/api/applications/${second}/force-status`, { stateId: 'nope' }));
        expect((await get<Row>(`/api/applications/${second}`)).state.key).toBe('approved');

        const edited = await firstValueFrom(
          http.patch<{ title: string; version: number; data: { title: string } }>(`/api/applications/${second}`, {
            data: { title: ' Neuer Titel ' },
          }),
        );
        // The edit stores the answers as sent and makes a new version.
        expect(edited.data.title).toBe(' Neuer Titel ');
        expect(edited.version).toBe(3);
        await firstValueFrom(http.patch(`/api/applications/${second}`, { data: { title: '  ' } }));
        const list = await get<{ items: Row[] }>('/api/applications', new HttpParams().set('archived', 'all'));
        // A blank title keeps the row title of the list.
        expect(list.items.find((r) => r.id === second)?.title).toBe('Neuer Titel');
        const versions = await get<{ version: number; diff: { changed: Record<string, unknown> } }[]>(
          `/api/applications/${second}/versions`,
        );
        expect(versions.map((v) => v.version)).toEqual([1, 2, 3, 4]);
        expect(Object.keys(versions[2].diff.changed)).toContain('title');

        await firstValueFrom(http.delete(`/api/applications/${second}`));
        await expect(get(`/api/applications/${second}`)).rejects.toMatchObject({ status: 404 });
      });

      it('serves the form, the history and the versions of a demo row', async () => {
        const form = await get<{ sections: { key: string }[] }>(`/api/applications/${first}/form`);
        expect(form.sections.map((s) => s.key)).toEqual(['plan', 'costs_section', 'contact']);
        const app = await get<{ data: { costs: { offers: unknown[]; noOffers?: boolean }[] } }>(
          `/api/applications/${first}`,
        );
        expect(app.data.costs).toHaveLength(3);
        expect(app.data.costs[2].noOffers).toBe(true);
        // Row 1 stands "Auf Tagesordnung": submitted, review, agenda.
        const timeline = await get<{ toState: { key: string }; transitionLabel: unknown }[]>(
          `/api/applications/${first}/timeline`,
        );
        expect(timeline.map((e) => e.toState.key)).toEqual(['submitted', 'review', 'agenda']);
        expect(timeline[0].transitionLabel).toBeNull();
        expect(await get<unknown[]>(`/api/applications/${first}/versions`)).toHaveLength(2);
        // Every third row has one version only; an approved row went through "Bewilligen".
        expect(await get<unknown[]>('/api/applications/a1000000-0000-0000-0000-000000000003/versions')).toHaveLength(1);
        const approved = await get<{ transitionLabel: { de: string } | null }[]>(
          '/api/applications/a1000000-0000-0000-0000-000000000010/timeline',
        );
        expect(approved.at(-1)?.transitionLabel?.de).toBe('Bewilligen');
        // A row without an amount has no cost positions.
        const noAmount = await get<{ data: Record<string, unknown> }>(
          '/api/applications/a1000000-0000-0000-0000-000000000015',
        );
        expect('costs' in noAmount.data).toBe(false);
      });

      it('answers 422 for a cost position without any offer (D12)', async () => {
        const data = { title: 'x', costs: [{ label: 'A', noOffers: true, noOffersReason: 'r', offers: [] }, { label: 'B' }] };
        await expect(firstValueFrom(http.patch(`/api/applications/${second}`, { data }))).rejects.toMatchObject({
          status: 422,
          error: { errors: [{ field: 'costs[0]' }] },
        });
      });

      it('puts a row on the agenda of a planned demo meeting and refuses another meeting', async () => {
        const review = 'a1000000-0000-0000-0000-000000000004';
        const meetings = await get<{ id: string; status: string; title: string }[]>(
          '/api/meetings',
          new HttpParams().set('gremiumId', 'g0000000-0000-0000-0000-000000000001'),
        );
        expect(meetings).toHaveLength(3);
        expect(meetings.every((m) => m.status === 'planned')).toBe(true);
        const [agenda] = await get<{ id: string }[]>(`/api/applications/${review}/transitions`);
        await expect(
          firstValueFrom(http.post(`/api/applications/${review}/transition`, { transitionId: agenda.id, meetingId: 'gone' })),
        ).rejects.toMatchObject({ status: 422, error: { code: 'agenda_meeting_invalid' } });
        await firstValueFrom(
          http.post(`/api/applications/${review}/transition`, {
            transitionId: agenda.id,
            meetingId: meetings[0].id,
            nonPublic: true,
            note: 'Bitte vorziehen',
          }),
        );
        const timeline = await get<{ toState: { key: string }; note: string | null }[]>(
          `/api/applications/${review}/timeline`,
        );
        expect(timeline.map((e) => e.toState.key)).toEqual(['submitted', 'review', 'agenda']);
        expect(timeline.at(-1)?.note).toBe(`${meetings[0].title} · Bitte vorziehen`);
        // A transition without meeting or note records no note.
        const second2 = 'a1000000-0000-0000-0000-000000000002';
        const [start] = await get<{ id: string }[]>(`/api/applications/${second2}/transitions`);
        await firstValueFrom(http.post(`/api/applications/${second2}/transition`, { transitionId: start.id }));
        expect((await get<{ note: string | null }[]>(`/api/applications/${second2}/timeline`)).at(-1)?.note).toBeNull();
      });

      it('answers 404 for a write it does not know', async () => {
        await expect(
          firstValueFrom(http.put(`/api/applications/${first}`, {})),
        ).rejects.toMatchObject({ status: 404 });
        await expect(
          firstValueFrom(http.post(`/api/applications/${first}`, {})),
        ).rejects.toMatchObject({ status: 404 });
      });
    });

    it('GET /votes/{id} → vote', async () => {
      const v = await get<{ id: string; status: string }>('/api/votes/vote-x');
      expect(v.status).toBe('open');
    });

    it('GET /votes/{id} of a closed demo meeting → its closed result', async () => {
      const v = await get<{ status: string; result: string; meetingId: string; agendaItemId: string }>(
        '/api/votes/a0000000-0000-0000-0000-000000000101',
      );
      expect(v).toMatchObject({
        status: 'closed',
        result: 'passed',
        meetingId: 'd0000000-0000-0000-0000-000000000101',
        agendaItemId: 'ag-c01-3',
      });
    });

    it('GET /delegations/votes/{id}/status → the demo user represents a member', async () => {
      const s = await get<{ exercising: boolean; delegatedByName: string }>(
        '/api/delegations/votes/vote-x/status',
      );
      expect(s.exercising).toBe(true);
      expect(s.delegatedByName).toBeTruthy();
    });

    it('POST /votes/{id}/ballot keeps the ballots and refuses a second one', async () => {
      const cast = (body: unknown) =>
        firstValueFrom(http.post<{ status: string }>('/api/votes/vote-ballots/ballot', body));
      expect((await cast({ choice: 'no' })).status).toBe('cast');
      await expect(cast({ choice: 'yes' })).rejects.toMatchObject({
        status: 409,
        error: { code: 'already_voted' },
      });
      expect((await cast({ asDelegation: true })).status).toBe('cast');
      const v = await get<{ myBallot: { cast: boolean; choice: string }; representedCast: boolean; tally: { voted: number } }>(
        '/api/votes/vote-ballots',
      );
      expect(v.myBallot).toEqual({ cast: true, choice: 'no' });
      expect(v.representedCast).toBe(true);
      expect(v.tally.voted).toBe(10);
    });

    it('POST /votes/{id}/ballot without a body still counts', async () => {
      const res = await firstValueFrom(http.post<{ status: string }>('/api/votes/vote-empty/ballot', null));
      expect(res.status).toBe('cast');
    });

    describe('vote list (mock-votes.ts)', () => {
      type Row = { id: string; status: string; myBallot: { cast: boolean; choice: string | null }; meetingTitle: string | null };
      type VotePage = { items: Row[]; total: number; limit: number; offset: number };
      const list = (params = new HttpParams()) => get<VotePage>('/api/votes', params);

      it('GET /votes → the open votes first, without the drafts', async () => {
        const page = await list();
        // The ended votes follow by the time they ended, the newest first.
        expect(page.items.map((r) => r.status)).toEqual(['open', 'open', 'closed', 'cancelled', 'closed']);
        expect(page.items.find((r) => r.id === 'vote-demo')?.meetingTitle).toBe('STUPA-Sitzung 12.06.');
        expect(page.total).toBe(5);
      });

      it('filters by status, gremium and search, and pages', async () => {
        const drafts = await list(new HttpParams().append('status', 'draft'));
        expect(drafts.items.map((r) => r.id)).toEqual(['b0000000-0000-0000-0000-000000000002']);
        const hha = await list(new HttpParams().set('gremiumId', 'g0000000-0000-0000-0000-000000000002'));
        expect(hha.total).toBe(2);
        const found = await list(new HttpParams().set('q', 'campuszeitung'));
        expect(found.items.map((r) => r.status)).toEqual(['cancelled']);
        const byMeeting = await list(new HttpParams().set('q', '33. sitzung'));
        expect(byMeeting.total).toBe(1);
        const second = await list(new HttpParams().set('limit', '2').set('offset', '2'));
        expect(second.items).toHaveLength(2);
        expect(second.offset).toBe(2);
      });

      it('shows the ballots of this mock session in the rows and the detail', async () => {
        const id = 'b0000000-0000-0000-0000-000000000001';
        expect((await get<{ myBallot: { cast: boolean } }>(`/api/votes/${id}`)).myBallot.cast).toBe(false);
        await firstValueFrom(http.post(`/api/votes/${id}/ballot`, { choice: 'no' }));
        const detail = await get<{ myBallot: { cast: boolean; choice: string }; tally: { voted: number } }>(
          `/api/votes/${id}`,
        );
        expect(detail.myBallot).toEqual({ cast: true, choice: 'no' });
        expect(detail.tally.voted).toBe(5);
        const row = (await list()).items.find((r) => r.id === id);
        expect(row?.myBallot).toEqual({ cast: true, choice: 'no' });
      });

      it('keeps the choice of a secret vote out of the row', async () => {
        const id = 'b0000000-0000-0000-0000-000000000003';
        await firstValueFrom(http.post(`/api/votes/${id}/ballot`, { choice: 'yes' }));
        const row = (await list(new HttpParams().append('status', 'closed'))).items.find((r) => r.id === id);
        expect(row?.myBallot).toEqual({ cast: true, choice: null });
        // The detail already had a cast ballot: the turnout stays.
        const detail = await get<{ tally: { voted: number } }>(`/api/votes/${id}`);
        expect(detail.tally.voted).toBe(4);
      });

      it('answers 404 for an unknown demo vote', async () => {
        await expect(
          get('/api/votes/b0000000-0000-0000-0000-000000000099'),
        ).rejects.toMatchObject({ status: 404 });
      });
    });

    it('GET /meetings/timeline?direction=upcoming → the live meeting first, then the planned ones', async () => {
      const page = await get<{ items: { status: string }[]; nextCursor: string | null }>(
        '/api/meetings/timeline',
        new HttpParams().set('direction', 'upcoming'),
      );
      expect(page.items.length).toBe(5);
      expect(page.items[0].status).toBe('live');
      expect(page.items.slice(1).every((m) => m.status === 'planned')).toBe(true);
      expect(page.nextCursor).toBeNull();
    });

    it('GET /meetings/timeline?direction=past → closed meetings, newest first', async () => {
      const page = await get<{ items: { status: string; date: string }[] }>(
        '/api/meetings/timeline',
        new HttpParams().set('direction', 'past'),
      );
      expect(page.items.length).toBe(4);
      expect(page.items.every((m) => m.status === 'closed')).toBe(true);
      expect(page.items[0].date > page.items[1].date).toBe(true);
    });

    it('GET /meetings/timeline with no direction defaults to upcoming', async () => {
      const page = await get<{ items: { status: string }[] }>('/api/meetings/timeline');
      expect(page.items[0].status).toBe('live');
    });

    it('GET /meetings/timeline pages with limit and cursor', async () => {
      const first = await get<{ items: unknown[]; nextCursor: string | null }>(
        '/api/meetings/timeline',
        new HttpParams().set('direction', 'past').set('limit', '3'),
      );
      expect(first.items.length).toBe(3);
      expect(first.nextCursor).toBe('3');
      const rest = await get<{ items: unknown[]; nextCursor: string | null }>(
        '/api/meetings/timeline',
        new HttpParams().set('direction', 'past').set('limit', '3').set('cursor', '3'),
      );
      expect(rest.items.length).toBe(1);
      expect(rest.nextCursor).toBeNull();
    });

    it('GET /meetings/timeline with q searches both directions, with gremiumId filters', async () => {
      const hits = await get<{ items: { title: string }[] }>(
        '/api/meetings/timeline',
        new HttpParams().set('q', 'haushaltsausschuss'),
      );
      expect(hits.items.map((m) => m.title)).toEqual([
        '12. Sitzung des Haushaltsausschusses',
        '11. Sitzung des Haushaltsausschusses',
      ]);
      const filtered = await get<{ items: { gremiumId: string }[] }>(
        '/api/meetings/timeline',
        new HttpParams()
          .set('direction', 'past')
          .set('gremiumId', 'g0000000-0000-0000-0000-000000000002'),
      );
      expect(filtered.items.length).toBe(1);
    });

    it('GET /meetings/gremien → the filter Gremien', async () => {
      const gs = await get<{ name: string }[]>('/api/meetings/gremien');
      expect(gs.map((g) => g.name)).toEqual(['Studierendenparlament', 'Haushaltsausschuss']);
    });

    it('GET /gremien/{id}/meeting-members → members, one without protocol.write', async () => {
      const ms = await get<{ canKeepProtocol: boolean }[]>('/api/gremien/g1/meeting-members');
      expect(ms.length).toBe(9);
      expect(ms.filter((m) => !m.canKeepProtocol).length).toBe(4);
    });

    it('GET /meetings/{id}/protocol → protocol', async () => {
      const p = await get<{ status: string }>('/api/meetings/m1/protocol');
      expect(p.status).toBeTruthy();
    });

    it('GET /meetings → the live and a planned meeting, with the start-page fields', async () => {
      const list = await get<
        {
          status: string;
          startedAt?: string;
          currentAgendaItem?: { position: number };
          agendaItemCount?: number;
        }[]
      >('/api/meetings');
      expect(list.map((m) => m.status)).toEqual(['live', 'planned']);
      expect(list[0].startedAt).toBeTruthy();
      expect(list[0].currentAgendaItem?.position).toBe(3);
      expect(list[0].agendaItemCount).toBe(6);
    });

    it('GET /meetings?dateFrom&dateTo → the meetings of the calendar month, with the agenda count', async () => {
      const day = (offset: number): string => {
        const d = new Date();
        d.setDate(d.getDate() + offset);
        const pad = (n: number) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
      };
      const range = new HttpParams().set('dateFrom', day(-10)).set('dateTo', day(15));
      const rows = await get<{ title: string; status: string; date: string; agendaItemCount?: number }[]>(
        '/api/meetings',
        range,
      );
      expect(rows.map((m) => m.title).sort()).toEqual([
        '12. Sitzung des Haushaltsausschusses',
        '33. Sitzung des Studierendenparlaments',
        '35. Sitzung des Studierendenparlaments',
        'STUPA-Sitzung 12.06.',
      ]);
      // The live meeting runs today.
      expect(rows.find((m) => m.status === 'live')?.date).toBe(day(0));
      expect(rows.find((m) => m.title.startsWith('33.'))?.agendaItemCount).toBe(9);
      const ha = await get<{ title: string }[]>(
        '/api/meetings',
        range.set('gremiumId', 'g0000000-0000-0000-0000-000000000002'),
      );
      expect(ha.map((m) => m.title)).toEqual(['12. Sitzung des Haushaltsausschusses']);
    });

    it('GET /delegations → the own delegations, filtered by meetingId', async () => {
      const all = await get<{ meetingId: string; direction: string | null }[]>('/api/delegations');
      // The own one and three rows that the admin overview shows.
      expect(all.map((d) => d.direction)).toEqual(['incoming', null, null, null]);
      const none = await get<unknown[]>(
        '/api/delegations',
        new HttpParams().set('meetingId', 'other'),
      );
      expect(none).toEqual([]);
    });

    it('/delegations/substitutes → the pool of a gremium: list, add, duplicate, remove', async () => {
      type Row = { id: string; memberId: string | null; substituteId: string };
      const stupa = new HttpParams().set('gremiumId', 'g0000000-0000-0000-0000-000000000001');
      const before = await get<Row[]>('/api/delegations/substitutes', stupa);
      expect(before.map((r) => r.substituteId)).toEqual(['p-12', 'p-3']);
      expect(await get<Row[]>('/api/delegations/substitutes', new HttpParams().set('gremiumId', 'g-x'))).toEqual([]);
      const body = { gremiumId: 'g0000000-0000-0000-0000-000000000001', substituteId: 'p-5' };
      const added = await firstValueFrom(http.post<Row>('/api/delegations/substitutes', body));
      expect(added).toMatchObject({ memberId: null, substituteId: 'p-5' });
      await expect(firstValueFrom(http.post('/api/delegations/substitutes', body))).rejects.toMatchObject({
        status: 409,
      });
      const forOne = await firstValueFrom(
        http.post<Row>('/api/delegations/substitutes', { ...body, memberId: 'p-8' }),
      );
      expect(forOne.memberId).toBe('p-8');
      await firstValueFrom(http.delete(`/api/delegations/substitutes/${added.id}`));
      await firstValueFrom(http.delete(`/api/delegations/substitutes/${forOne.id}`));
      expect((await get<Row[]>('/api/delegations/substitutes', stupa)).length).toBe(before.length);
    });

    it('GET …/attendance → roster', async () => {
      const roster = await get<unknown[]>('/api/meetings/m1/attendance');
      expect(roster.length).toBe(9);
    });

    it('GET …/agenda/assignable → filtered list (both seeded applications are taken)', async () => {
      const a = await get<unknown[]>('/api/meetings/m1/agenda/assignable');
      expect(a.length).toBe(0);
    });

    it('GET …/agenda → the seeded agenda of the live meeting', async () => {
      const a = await get<{ id: string }[]>('/api/meetings/m1/agenda');
      expect(a.map((x) => x.id)).toContain('ag-s3');
    });

    it('GET /meetings/{id} → single meeting', async () => {
      const m = await get<{ id: string; title: string }>('/api/meetings/m1');
      expect(m.title).toContain('STUPA');
    });

    it('GET the planned meeting and its agenda by id', async () => {
      const id = 'd0000000-0000-0000-0000-000000000002';
      const m = await get<{ status: string; protokollantId: string | null }>(`/api/meetings/${id}`);
      expect(m.status).toBe('planned');
      expect(m.protokollantId).toBeNull();
      const a = await get<unknown[]>(`/api/meetings/${id}/agenda`);
      expect(a.length).toBe(3);
    });

    it('GET /applications/{id}/form → effective form', async () => {
      const form = await get<{ sections: unknown[] }>('/api/applications/x/form');
      expect(form.sections.length).toBeGreaterThan(0);
    });

    it('GET /applications/{id} → single application', async () => {
      const app = await get<{ id: string }>('/api/applications/some-id');
      expect(app.id).toBeTruthy();
    });

    it('PUT …/agenda/order reorders the in-memory agenda', async () => {
      const after1 = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP A' }),
      );
      const after2 = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP B' }),
      );
      expect(after2.length).toBe(after1.length + 1);
      const ids = after2.map((a) => a.id).reverse();
      const reordered = await firstValueFrom(
        http.put<{ id: string; position: number }[]>('/api/meetings/m1/agenda/order', {
          itemIds: ids,
        }),
      );
      expect(reordered.map((r) => r.id)).toEqual(ids);
      expect(reordered[0].position).toBe(0);
    });

    it('PUT …/agenda/order with no itemIds yields an empty agenda', async () => {
      const res = await firstValueFrom(
        http.put<unknown[]>('/api/meetings/m1/agenda/order', {}),
      );
      expect(res).toEqual([]);
    });

    it('PUT …/attendance/me sets own attendance to self-source', async () => {
      const res = await firstValueFrom(
        http.put<{ isSelf: boolean; status: string | null; source: string | null }[]>(
          '/api/meetings/m1/attendance/me',
          { status: 'present' },
        ),
      );
      const self = res.find((r) => r.isSelf);
      expect(self?.status).toBe('present');
      expect(self?.source).toBe('self');
    });

    it('PUT …/attendance/{principalId} sets a member with lead-source and default status', async () => {
      const res = await firstValueFrom(
        http.put<{ principalId: string; status: string | null; source: string | null }[]>(
          '/api/meetings/m1/attendance/p-2',
          {},
        ),
      );
      const member = res.find((r) => r.principalId === 'p-2');
      expect(member?.status).toBe('present');
      expect(member?.source).toBe('lead');
    });

    it('PUT …/attendance/{principalId} keeps the reason of an excuse unless a note is given', async () => {
      type Row = { principalId: string; status: string | null; note: string | null };
      const kept = await firstValueFrom(
        http.put<Row[]>('/api/meetings/m1/attendance/p-3', { status: 'excused' }),
      );
      expect(kept.find((r) => r.principalId === 'p-3')?.note).toBe('Prüfung');
      const changed = await firstValueFrom(
        http.put<Row[]>('/api/meetings/m1/attendance/p-3', { status: 'excused', note: 'Reise' }),
      );
      expect(changed.find((r) => r.principalId === 'p-3')?.note).toBe('Reise');
      const present = await firstValueFrom(
        http.put<Row[]>('/api/meetings/m1/attendance/p-3', { status: 'present' }),
      );
      expect(present.find((r) => r.principalId === 'p-3')?.note).toBeNull();
    });

    it('PUT …/attendance/{principalId} without a body sets present', async () => {
      const res = await firstValueFrom(
        http.put<{ principalId: string; status: string | null }[]>(
          '/api/meetings/m1/attendance/p-2',
          null,
        ),
      );
      expect(res.find((r) => r.principalId === 'p-2')?.status).toBe('present');
    });

    it('DELETE …/attendance/{principalId} resets the member to open', async () => {
      const res = await firstValueFrom(
        http.delete<{ principalId: string; status: string | null; source: string | null }[]>(
          '/api/meetings/m1/attendance/p-2',
        ),
      );
      const member = res.find((r) => r.principalId === 'p-2');
      expect(member?.status).toBeNull();
      expect(member?.source).toBeNull();
    });

    it('POST /auth/logout → logout out', async () => {
      const res = await firstValueFrom(http.post<{ logout_url: null }>('/api/auth/logout', {}));
      expect(res.logout_url).toBeNull();
    });

    it('POST …/meetings/{id}/votes appends a vote with its question', async () => {
      const m = await firstValueFrom(
        http.post<{ votes: { question?: string | null; applicationId: string }[] }>(
          '/api/meetings/m1/votes',
          { applicationId: 'app-z', question: 'Annehmen?' },
        ),
      );
      const last = m.votes[m.votes.length - 1];
      expect(last.question).toBe('Annehmen?');
      expect(last.applicationId).toBe('app-z');
    });

    it('POST …/meetings/{id}/votes defaults applicationId/question to empty/null', async () => {
      const m = await firstValueFrom(
        http.post<{ votes: { question?: string | null; applicationId: string }[] }>(
          '/api/meetings/m1/votes',
          {},
        ),
      );
      const last = m.votes[m.votes.length - 1];
      expect(last.applicationId).toBe('');
      expect(last.question).toBeNull();
    });

    it('POST …/agenda with freetext title adds a freetext TOP', async () => {
      const a = await firstValueFrom(
        http.post<{ applicationId: string | null; title: string | null }[]>(
          '/api/meetings/m1/agenda',
          { title: 'Freitext-TOP' },
        ),
      );
      const last = a[a.length - 1];
      expect(last.applicationId).toBeNull();
      expect(last.title).toBe('Freitext-TOP');
    });

    it('POST …/agenda keeps the nonPublic flag of a new item', async () => {
      const a = await firstValueFrom(
        http.post<{ nonPublic?: boolean }[]>('/api/meetings/m1/agenda', {
          title: 'Personal',
          nonPublic: true,
        }),
      );
      expect(a[a.length - 1].nonPublic).toBe(true);
    });

    it('POST …/agenda with a known applicationId adds it once (idempotent)', async () => {
      const appId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
      const first = await firstValueFrom(
        http.post<{ applicationId: string | null }[]>('/api/meetings/m1/agenda', {
          applicationId: appId,
        }),
      );
      const countAfterFirst = first.filter((a) => a.applicationId === appId).length;
      expect(countAfterFirst).toBe(1);
      const second = await firstValueFrom(
        http.post<{ applicationId: string | null }[]>('/api/meetings/m1/agenda', {
          applicationId: appId,
        }),
      );
      expect(second.filter((a) => a.applicationId === appId).length).toBe(1);
    });

    it('POST …/agenda with an unknown applicationId still adds (title null)', async () => {
      const res = await firstValueFrom(
        http.post<{ applicationId: string | null; title: string | null }[]>(
          '/api/meetings/m1/agenda',
          { applicationId: 'unknown-app' },
        ),
      );
      const added = res.find((a) => a.applicationId === 'unknown-app');
      expect(added).toBeTruthy();
      expect(added?.title).toBeNull();
    });

    it('POST …/agenda with no body adds nothing', async () => {
      const before = await get<unknown[]>('/api/meetings/m1/agenda');
      const after = await firstValueFrom(
        http.post<unknown[]>('/api/meetings/m1/agenda', {}),
      );
      expect(after.length).toBe(before.length);
    });

    it('POST /comments with explicit internal visibility', async () => {
      const c = await firstValueFrom(
        http.post<{ body: string; visibility: string; authorKind: string }>(
          '/api/applications/x/comments',
          { body: 'intern', visibility: 'internal' },
        ),
      );
      expect(c.body).toBe('intern');
      expect(c.visibility).toBe('internal');
      expect(c.authorKind).toBe('applicant');
    });

    it('POST /comments defaults body/visibility', async () => {
      const c = await firstValueFrom(
        http.post<{ body: string; visibility: string }>('/api/applications/x/comments', {}),
      );
      expect(c.body).toBe('');
      expect(c.visibility).toBe('public');
    });

    it('POST /attachments → created attachment (scanned=false)', async () => {
      const a = await firstValueFrom(
        http.post<{ scanned: boolean; filename: string }>(
          '/api/applications/x/attachments',
          new FormData(),
        ),
      );
      expect(a.scanned).toBe(false);
      expect(a.filename).toBe('mock-upload.pdf');
    });

    it('POST …/transition with a known transitionId', async () => {
      const res = await firstValueFrom(
        http.post<{ newStateId: string }>('/api/applications/x/transition', {
          transitionId: '77777777-7777-7777-7777-777777777772',
        }),
      );
      expect(res.newStateId).toBe('66666666-6666-6666-6666-666666666664');
    });

    it('POST …/transition with an unknown transitionId falls back to the first', async () => {
      const res = await firstValueFrom(
        http.post<{ newStateId: string }>('/api/applications/x/transition', {
          transitionId: 'nope',
        }),
      );
      expect(res.newStateId).toBe('66666666-6666-6666-6666-666666666662');
    });

    it('POST …/transition with no body defaults to the first transition', async () => {
      const res = await firstValueFrom(
        http.post<{ newStateId: string }>('/api/applications/x/transition', {}),
      );
      expect(res.newStateId).toBe('66666666-6666-6666-6666-666666666662');
    });

    it('POST /applications → created applicationId', async () => {
      const res = await firstValueFrom(
        http.post<{ applicationId: string }>('/api/applications', {}),
      );
      expect(res.applicationId).toBeTruthy();
    });

    it('POST /votes/{id}/ballot → cast', async () => {
      const res = await firstValueFrom(
        http.post<{ status: string }>('/api/votes/v1/ballot', { choice: 'yes' }),
      );
      expect(res.status).toBe('cast');
    });

    it('POST …/finalize → final protocol', async () => {
      const p = await firstValueFrom(
        http.post<{ status: string; pdfUrl: string }>('/api/protocols/p1/finalize', {}),
      );
      expect(p.status).toBe('final');
      expect(p.pdfUrl).toContain('pdf');
    });

    it('POST /protocols/{id}/votes → protocol', async () => {
      const p = await firstValueFrom(
        http.post<{ id: string }>('/api/protocols/p1/votes', { voteIds: ['v1'] }),
      );
      expect(p.id).toBeTruthy();
    });

    it('POST /votes/{id}/open → 204', async () => {
      const res = await firstValueFrom(http.post('/api/votes/a0000000-0000-0000-0000-0000000000a1/open', {}));
      expect(res).toBeNull();
    });

    it('POST /votes/{id}/close → 204 (sets a result)', async () => {
      const res = await firstValueFrom(http.post('/api/votes/a0000000-0000-0000-0000-0000000000a1/close', {}));
      expect(res).toBeNull();
      const m = await get<{ votes: { id: string; result: string | null }[] }>('/api/meetings/m1');
      const v = m.votes.find((x) => x.id === 'a0000000-0000-0000-0000-0000000000a1');
      expect(v?.result).toBeTruthy();
    });

    it('POST /votes/{id}/close on a vote without leading falls back to "accepted"', async () => {
      // a2 has leading=null, so the result must become 'accepted'.
      await firstValueFrom(http.post('/api/votes/a0000000-0000-0000-0000-0000000000a2/close', {}));
      const m = await get<{ votes: { id: string; result: string | null }[] }>('/api/meetings/m1');
      const v = m.votes.find((x) => x.id === 'a0000000-0000-0000-0000-0000000000a2');
      expect(v?.result).toBe('accepted');
    });

    it('POST /votes/{id}/open on a vote keeps its existing result (status branch)', async () => {
      // The open branch keeps `v.result` because the new status is not 'closed'.
      const res = await firstValueFrom(http.post('/api/votes/a0000000-0000-0000-0000-0000000000a2/open', {}));
      expect(res).toBeNull();
    });

    it('POST /meetings/{id}/protocol → protocol', async () => {
      const p = await firstValueFrom(http.post<{ id: string }>('/api/meetings/m1/protocol', {}));
      expect(p.id).toBeTruthy();
    });

    it('POST /meetings with a title → planned meeting', async () => {
      const m = await firstValueFrom(
        http.post<{ status: string; title: string; date: string | null }>('/api/meetings', {
          title: '  Neue Sitzung  ',
          date: '2026-07-01',
          startTime: '18:00',
        }),
      );
      expect(m.status).toBe('planned');
      expect(m.title).toBe('Neue Sitzung');
      expect(m.date).toBe('2026-07-01');
    });

    it('POST /meetings with a blank title keeps the existing title', async () => {
      const m = await firstValueFrom(
        http.post<{ title: string }>('/api/meetings', { title: '   ' }),
      );
      expect(m.title).toBeTruthy();
    });

    it('POST /meetings with no body keeps existing title and null date', async () => {
      const m = await firstValueFrom(
        http.post<{ title: string; date: string | null }>('/api/meetings', {}),
      );
      expect(m.title).toBeTruthy();
      expect(m.date).toBeNull();
    });

    it('POST /meetings with a null body falls back to {} (nullish branch)', async () => {
      const m = await firstValueFrom(
        http.post<{ title: string; status: string }>('/api/meetings', null),
      );
      expect(m.title).toBeTruthy();
      expect(m.status).toBe('planned');
    });

    it('POST /auth/magic-link/verify → scope edit', async () => {
      const res = await firstValueFrom(
        http.post<{ scope: string }>('/api/auth/magic-link/verify', { token: 't' }),
      );
      expect(res.scope).toBe('edit');
    });

    it('PATCH /applications/{id} → echoes the data', async () => {
      const app = await firstValueFrom(
        http.patch<{ data: Record<string, unknown> }>('/api/applications/x', {
          data: { title: 'Z' },
        }),
      );
      expect(app.data).toEqual({ title: 'Z' });
    });

    it('PATCH /applications/{id} with no data → {}', async () => {
      const app = await firstValueFrom(
        http.patch<{ data: Record<string, unknown> }>('/api/applications/x', {}),
      );
      expect(app.data).toEqual({});
    });

    it('PATCH /applications/{id} with a null body → {} (nullish branch)', async () => {
      const app = await firstValueFrom(
        http.patch<{ data: Record<string, unknown> }>('/api/applications/x', null),
      );
      expect(app.data).toEqual({});
    });

    it('PATCH /meetings/{id} sets status and activeApplicationId', async () => {
      const m = await firstValueFrom(
        http.patch<{ status: string; activeApplicationId: string | null }>('/api/meetings/m1', {
          status: 'closed',
          activeApplicationId: 'app-9',
        }),
      );
      expect(m.status).toBe('closed');
      expect(m.activeApplicationId).toBe('app-9');
    });

    it('PATCH /meetings/{id} sets date and startTime (defined-branch)', async () => {
      const m = await firstValueFrom(
        http.patch<{ date: string | null; startTime: string | null }>('/api/meetings/m1', {
          date: '2026-08-01',
          startTime: '19:30',
        }),
      );
      expect(m.date).toBe('2026-08-01');
      expect(m.startTime).toBe('19:30');
    });

    it('PATCH /meetings/{id} sets the end time and the minute-taker', async () => {
      const m = await firstValueFrom(
        http.patch<{ endTime: string | null; protokollantId: string | null }>('/api/meetings/m1', {
          endTime: '21:00',
          protokollantId: 'p-2',
        }),
      );
      expect(m.endTime).toBe('21:00');
      expect(m.protokollantId).toBe('p-2');
    });

    it('PATCH /meetings/{id} with no body keeps the existing fields', async () => {
      const m = await firstValueFrom(
        http.patch<{ status: string; activeApplicationId: string | null }>('/api/meetings/m1', {}),
      );
      expect(m.status).toBeTruthy();
      // activeApplicationId keeps its previous value and never becomes undefined.
      expect(m.activeApplicationId !== undefined).toBe(true);
    });

    it('PATCH /meetings/{id} with a null body falls back to {} (nullish branch)', async () => {
      const m = await firstValueFrom(
        http.patch<{ status: string }>('/api/meetings/m1', null),
      );
      expect(m.status).toBeTruthy();
    });

    it('PATCH …/agenda/{itemId} sets the markdown body', async () => {
      const added = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP X' }),
      );
      const id = added[added.length - 1].id;
      const res = await firstValueFrom(
        http.patch<{ id: string; body?: string }[]>(`/api/meetings/m1/agenda/${id}`, {
          body: '## md',
        }),
      );
      expect(res.find((a) => a.id === id)?.body).toBe('## md');
    });

    it('PATCH …/agenda/{itemId} changes only the sent fields (title, NÖ)', async () => {
      const added = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP Y' }),
      );
      const id = added[added.length - 1].id;
      await firstValueFrom(http.patch(`/api/meetings/m1/agenda/${id}`, { body: 'Text' }));
      const res = await firstValueFrom(
        http.patch<{ id: string; title: string; body?: string; nonPublic?: boolean }[]>(
          `/api/meetings/m1/agenda/${id}`,
          { title: 'TOP Z', nonPublic: true },
        ),
      );
      const row = res.find((a) => a.id === id);
      expect(row?.title).toBe('TOP Z');
      expect(row?.nonPublic).toBe(true);
      expect(row?.body).toBe('Text');
      const same = await firstValueFrom(
        http.patch<{ id: string; title: string }[]>(`/api/meetings/m1/agenda/${id}`, null),
      );
      expect(same.find((a) => a.id === id)?.title).toBe('TOP Z');
    });

    it('PATCH /protocols/{id} sets the markdown', async () => {
      const p = await firstValueFrom(
        http.patch<{ markdown: string }>('/api/protocols/p1', { markdown: '# Neu' }),
      );
      expect(p.markdown).toBe('# Neu');
    });

    it('PATCH /protocols/{id} with no markdown keeps the existing markdown', async () => {
      const p = await firstValueFrom(
        http.patch<{ markdown: string }>('/api/protocols/p1', {}),
      );
      expect(p.markdown).toBeTruthy();
    });

    it('DELETE …/agenda/{itemId} removes the TOP', async () => {
      const added = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP del' }),
      );
      const id = added[added.length - 1].id;
      const after = await firstValueFrom(
        http.delete<{ id: string }[]>(`/api/meetings/m1/agenda/${id}`),
      );
      expect(after.some((a) => a.id === id)).toBe(false);
    });

    describe('FE9: the participant view and the delegation setup', () => {
      const MEMBER_LIVE = 'd0000000-0000-0000-0000-000000000003';
      const MEMBER_PLANNED = 'd0000000-0000-0000-0000-000000000105';
      type Ctx = {
        meetingStarted: boolean;
        deadline: string | null;
        myDelegation: { delegateId: string; viaPool: boolean } | null;
        incoming: { delegatorName: string }[];
        recipients: { principalId: string; viaPool: boolean }[];
      };

      it('serves the live meeting as a plain member sees it', async () => {
        // The status follows the live demo meeting, which other tests may have closed.
        const m = await get<{ id: string; canWrite: boolean; canVote: boolean; protokollantName: string }>(
          `/api/meetings/${MEMBER_LIVE}`,
        );
        expect(m).toMatchObject({ id: MEMBER_LIVE, canWrite: false, canVote: true, protokollantName: 'Max Mustermann' });
        const ctx = await get<Ctx>(`/api/delegations/meetings/${MEMBER_LIVE}/context`);
        expect(ctx.meetingStarted).toBe(true);
        expect(ctx.incoming.map((d) => d.delegatorName)).toEqual(['Erika Beispiel']);
      });

      it('serves a planned meeting with its agenda and the delegation setup', async () => {
        const m = await get<{ status: string; canManage: boolean }>(`/api/meetings/${MEMBER_PLANNED}`);
        expect(m).toMatchObject({ status: 'planned', canManage: false });
        const agenda = await get<unknown[]>(`/api/meetings/${MEMBER_PLANNED}/agenda`);
        expect(agenda).toHaveLength(5);
        const ctx = await get<Ctx>(`/api/delegations/meetings/${MEMBER_PLANNED}/context`);
        expect(ctx.meetingStarted).toBe(false);
        expect(ctx.deadline).toBeTruthy();
        expect(ctx.recipients.filter((r) => r.viaPool)).toHaveLength(2);
        const hits = await get<{ displayName: string }[]>(
          `/api/delegations/meetings/${MEMBER_PLANNED}/recipients`,
          new HttpParams().set('q', 'emma'),
        );
        expect(hits.map((r) => r.displayName)).toEqual(['Emma Vogel']);
        const all = await get<unknown[]>(`/api/delegations/meetings/${MEMBER_PLANNED}/recipients`);
        expect(all.length).toBeGreaterThan(2);
      });

      it('creates an own delegation, which the context then names', async () => {
        const made = await firstValueFrom(
          http.post<{ delegateName: string; viaPool: boolean; direction: string }>('/api/delegations', {
            meetingId: MEMBER_PLANNED,
            delegateId: 'p-10',
            delegateVoting: true,
          }),
        );
        expect(made).toMatchObject({ delegateName: 'Emma Vogel', viaPool: true, direction: 'outgoing' });
        const member = await firstValueFrom(
          http.post<{ delegateName: string; viaPool: boolean }>('/api/delegations', {
            meetingId: 'd0000000-0000-0000-0000-000000000002',
            delegateId: 'p-2',
          }),
        );
        expect(member).toMatchObject({ delegateName: 'Max Mustermann', viaPool: false });
        const nobody = await firstValueFrom(http.post<{ delegateName: string | null }>('/api/delegations', null));
        expect(nobody.delegateName).toBeNull();
        const ctx = await get<Ctx>(`/api/delegations/meetings/${MEMBER_PLANNED}/context`);
        expect(ctx.myDelegation).toMatchObject({ delegateId: 'p-10' });
        // The planned demo meeting of the lead has not started either.
        const lead = await get<Ctx>('/api/delegations/meetings/d0000000-0000-0000-0000-000000000002/context');
        expect(lead.meetingStarted).toBe(false);
      });
    });

    describe('FE7: keepers, attendance with delegations, closed meetings', () => {
      const LIVE = 'd0000000-0000-0000-0000-000000000001';
      const DEMO = '00000000-0000-0000-0000-000000000001';
      type M = {
        protokollantId: string | null;
        plannedHandover: { principalId: string; fromPosition: number | null } | null;
        keeperPeriods: { principalId: string; toAt: string | null; toPosition: number | null }[];
      };
      const handover = (principalId: string, mode: string) =>
        firstValueFrom(http.post<M>(`/api/meetings/${LIVE}/protokollant-handover`, { principalId, mode }));

      // Other tests change the shared mock meeting: start from the demo keeper on TOP 3.
      beforeEach(async () => {
        await firstValueFrom(
          http.patch(`/api/meetings/${LIVE}`, { protokollantId: DEMO, currentAgendaItemId: 'ag-s3' }),
        );
      });

      it('refuses a handover to a member without protocol.write and to the keeper (O20)', async () => {
        await expect(handover('p-3', 'now')).rejects.toMatchObject({
          status: 422,
          error: { code: 'protokollant_needs_protocol_write' },
        });
        await expect(handover(DEMO, 'now')).rejects.toMatchObject({
          status: 409,
          error: { code: 'already_protokollant' },
        });
      });

      it('plans a handover, discards it, and starts a planned one on a forward move (Z3)', async () => {
        // Other tests change the agenda: take the items it has now.
        const agenda = await get<{ id: string }[]>(`/api/meetings/${LIVE}/agenda`);
        expect(agenda.length).toBeGreaterThan(1);
        await firstValueFrom(http.patch(`/api/meetings/${LIVE}`, { currentAgendaItemId: agenda[0].id }));
        const planned = await handover('p-4', 'next_item');
        expect(planned.plannedHandover).toMatchObject({ principalId: 'p-4', fromPosition: 2 });
        const discarded = await firstValueFrom(
          http.delete<M>(`/api/meetings/${LIVE}/protokollant-handover`),
        );
        expect(discarded.plannedHandover).toBeNull();
        await expect(
          firstValueFrom(http.delete(`/api/meetings/${LIVE}/protokollant-handover`)),
        ).rejects.toMatchObject({ status: 404 });
        await handover('p-4', 'next_item');
        const moved = await firstValueFrom(
          http.patch<M>(`/api/meetings/${LIVE}`, { currentAgendaItemId: agenda[1].id }),
        );
        expect(moved.protokollantId).toBe('p-4');
        expect(moved.plannedHandover).toBeNull();
        expect(moved.keeperPeriods.at(-1)?.principalId).toBe('p-4');
        // The last item has no next one.
        await firstValueFrom(
          http.patch(`/api/meetings/${LIVE}`, { currentAgendaItemId: agenda[agenda.length - 1].id }),
        );
        await expect(handover(DEMO, 'next_item')).rejects.toMatchObject({
          status: 409,
          error: { code: 'no_next_item' },
        });
        // Hand back now: one running period, the demo user's.
        const back = await handover(DEMO, 'now');
        expect(back.protokollantId).toBe(DEMO);
        expect(back.keeperPeriods.filter((k) => k.toAt === null)).toEqual([
          expect.objectContaining({ principalId: DEMO }),
        ]);
      });

      it('refuses "present" while the member has a delegation of the meeting, until it is revoked (O23)', async () => {
        await expect(
          firstValueFrom(http.put(`/api/meetings/${LIVE}/attendance/p-6`, { status: 'present' })),
        ).rejects.toMatchObject({ status: 409, error: { code: 'delegation_active' } });
        const listed = await get<{ id: string; delegatorId: string }[]>(
          '/api/delegations',
          new HttpParams().set('meetingId', LIVE),
        );
        expect(listed.map((d) => d.delegatorId)).toEqual(['p-6']);
        await firstValueFrom(http.delete(`/api/delegations/${listed[0].id}`));
        const rows = await firstValueFrom(
          http.put<{ principalId: string; status: string }[]>(`/api/meetings/${LIVE}/attendance/p-6`, { status: 'present' }),
        );
        expect(rows.find((r) => r.principalId === 'p-6')?.status).toBe('present');
      });

      it('serves the closed meetings: draft, edit of the text, finalize, and a final one', async () => {
        const draft = 'd0000000-0000-0000-0000-000000000101';
        const m = await get<{ status: string; keeperPeriods: unknown[]; votes: { status: string }[] }>(`/api/meetings/${draft}`);
        expect(m.status).toBe('closed');
        expect(m.keeperPeriods).toHaveLength(2);
        expect(m.votes[0].status).toBe('closed');
        const agenda = await get<{ id: string; body: string }[]>(`/api/meetings/${draft}/agenda`);
        expect(agenda[2].body).toContain('> [!abstimmung]');
        const edited = await firstValueFrom(
          http.patch<{ id: string; body: string }[]>(`/api/meetings/${draft}/agenda/${agenda[0].id}`, { body: 'Neu.' }),
        );
        expect(edited[0].body).toBe('Neu.');
        const protocol = await get<{ id: string; status: string }>(`/api/meetings/${draft}/protocol`);
        expect(protocol.status).toBe('draft');
        await firstValueFrom(http.patch(`/api/protocols/${protocol.id}`, { markdown: '# A' }));
        const final = await firstValueFrom(
          http.post<{ status: string; publicPdfUrl: string | null }>(`/api/protocols/${protocol.id}/finalize`, null),
        );
        expect(final.status).toBe('final');
        expect(final.publicPdfUrl).toBeTruthy();
        // Anything else on a closed meeting is refused.
        await expect(
          firstValueFrom(http.delete(`/api/meetings/${draft}/agenda/${agenda[0].id}`)),
        ).rejects.toMatchObject({ status: 409 });
        const other = await get<{ status: string; pdfUrl: string }>(
          '/api/meetings/d0000000-0000-0000-0000-000000000102/protocol',
        );
        expect(other.status).toBe('final');
        expect(other.pdfUrl).toBeTruthy();
        // The roster of a closed meeting is the roster of the gremium.
        const roster = await get<unknown[]>(`/api/meetings/${draft}/attendance`);
        expect(roster.length).toBe(9);
      });
    });

    it('DELETE on an unmatched /api path falls through to next()', () => {
      http.delete('/api/applications/x').subscribe();
      // No agenda regex matches → the request falls through to the testing backend.
      ctrl.expectOne('/api/applications/x').flush(null);
    });
  });

  it('answers the global search with the mock records whose title matches', async () => {
    const { api } = setup(true);
    const apps = await firstValueFrom(api.search('förderung'));
    expect(apps.hits.map((h) => h.kind)).toEqual(['application', 'application']);
    expect(apps.hits[0].url).toMatch(/^\/applications\//);
    expect(apps.hits[0].subtitle).toBeTruthy();

    // Other tests rename the mock meeting, so search for the title it has now.
    const [current] = await firstValueFrom(api.listMeetings());
    const meeting = await firstValueFrom(api.search(current.title));
    expect(meeting.hits).toContainEqual(expect.objectContaining({ kind: 'meeting', title: current.title }));

    const person = await firstValueFrom(api.search('demo'));
    expect(person.hits).toEqual([expect.objectContaining({ kind: 'principal', title: 'Demo Mitglied' })]);

    const none = await firstValueFrom(api.search('zzzz'));
    expect(none).toEqual({ hits: [], truncated: false, failed: [] });
  });
});
