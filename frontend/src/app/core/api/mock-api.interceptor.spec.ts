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
      // mapper applied to the wire Page → view shape with hasBudget
      expect(typeof types[0].hasBudget).toBe('boolean');
      done();
    });
    http.expectNone('/api/application-types'); // handled by the mock, never hits the backend
  });

  it('passes through when the mock is disabled', () => {
    const { api, http } = setup(false);
    api.applicationTypes().subscribe();
    http.expectOne('/api/application-types').flush({ items: [], total: 0, limit: 20, offset: 0 });
    http.verify();
  });

  it('passes through requests that are not /api/ (mock enabled)', () => {
    const { http } = setup(true);
    const client = TestBed.inject(HttpClient);
    client.get('/assets/logo.svg', { responseType: 'text' }).subscribe();
    // Not an /api/ path → reaches the testing backend.
    http.expectOne('/assets/logo.svg').flush('<svg/>');
    http.verify();
  });

  it('passes through unmatched /api/ methods/paths (final next)', () => {
    const { http } = setup(true);
    const client = TestBed.inject(HttpClient);
    // OPTIONS is never matched by any branch → falls through to next().
    client.request('OPTIONS', '/api/unknown').subscribe();
    http.expectOne('/api/unknown').flush(null);
    http.verify();
  });

  it('serves the effective form (with sections) for the apply wizard', (done) => {
    const { api, http } = setup(true);
    api.effectiveForm('11111111-1111-1111-1111-111111111111').subscribe((form) => {
      expect(form.sections.length).toBeGreaterThan(0);
      expect(form.budgetPotId).toBeTruthy();
      done();
    });
    http.expectNone((r) => r.url.includes('/form'));
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
      // i18n label resolved by the mapper (de default)
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

  // ----- raw-HttpClient branch coverage of the mock router ------------------
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
      expect(events.length).toBe(2);
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

    it('GET …/expenses → empty page', async () => {
      const page = await get<{ items: unknown[]; total: number }>('/api/budgets/x/expenses');
      expect(page.items).toEqual([]);
      expect(page.total).toBe(0);
    });

    it('GET /applications/tasks → task list', async () => {
      const tasks = await get<unknown[]>('/api/applications/tasks');
      expect(tasks.length).toBe(2);
    });

    it('GET /applications → page', async () => {
      const page = await get<{ items: unknown[]; total: number }>('/api/applications');
      expect(page.total).toBe(2);
    });

    it('GET /votes/{id} → vote', async () => {
      const v = await get<{ id: string; status: string }>('/api/votes/vote-x');
      expect(v.status).toBe('open');
    });

    it('GET /meetings/timeline?direction=upcoming → one meeting', async () => {
      const page = await get<{ items: unknown[] }>(
        '/api/meetings/timeline',
        new HttpParams().set('direction', 'upcoming'),
      );
      expect(page.items.length).toBe(1);
    });

    it('GET /meetings/timeline?direction=past → empty', async () => {
      const page = await get<{ items: unknown[] }>(
        '/api/meetings/timeline',
        new HttpParams().set('direction', 'past'),
      );
      expect(page.items).toEqual([]);
    });

    it('GET /meetings/timeline with no direction defaults to upcoming', async () => {
      const page = await get<{ items: unknown[] }>('/api/meetings/timeline');
      expect(page.items.length).toBe(1);
    });

    it('GET /meetings → list', async () => {
      const list = await get<unknown[]>('/api/meetings');
      expect(list.length).toBe(1);
    });

    it('GET …/attendance → roster', async () => {
      const roster = await get<unknown[]>('/api/meetings/m1/attendance');
      expect(roster.length).toBe(3);
    });

    it('GET …/agenda/assignable → filtered list (none taken initially)', async () => {
      const a = await get<unknown[]>('/api/meetings/m1/agenda/assignable');
      expect(a.length).toBe(2);
    });

    it('GET …/agenda → agenda list', async () => {
      const a = await get<unknown[]>('/api/meetings/m1/agenda');
      expect(Array.isArray(a)).toBe(true);
    });

    it('GET /meetings/{id} → single meeting', async () => {
      const m = await get<{ id: string; title: string }>('/api/meetings/m1');
      expect(m.title).toContain('STUPA');
    });

    it('GET /applications/{id}/form → effective form', async () => {
      const form = await get<{ sections: unknown[] }>('/api/applications/x/form');
      expect(form.sections.length).toBeGreaterThan(0);
    });

    it('GET /applications/{id} → single application', async () => {
      const app = await get<{ id: string }>('/api/applications/some-id');
      expect(app.id).toBeTruthy();
    });

    // ----- PUT branches -----
    it('PUT …/agenda/order reorders the in-memory agenda', async () => {
      // First add two freetext TOPs, then reorder.
      const after1 = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP A' }),
      );
      const after2 = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP B' }),
      );
      expect(after2.length).toBe(2);
      const ids = after2.map((a) => a.id).reverse();
      const reordered = await firstValueFrom(
        http.put<{ id: string; position: number }[]>('/api/meetings/m1/agenda/order', {
          itemIds: ids,
        }),
      );
      expect(reordered.map((r) => r.id)).toEqual(ids);
      expect(reordered[0].position).toBe(0);
      void after1;
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
      expect(member?.status).toBe('present'); // default when body has no status
      expect(member?.source).toBe('lead');
    });

    // ----- POST branches -----
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

    it('POST …/agenda with a known applicationId adds it once (idempotent)', async () => {
      const appId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
      const first = await firstValueFrom(
        http.post<{ applicationId: string | null }[]>('/api/meetings/m1/agenda', {
          applicationId: appId,
        }),
      );
      const countAfterFirst = first.filter((a) => a.applicationId === appId).length;
      expect(countAfterFirst).toBe(1);
      // Adding the same appId again must not duplicate it.
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
      // a2 has leading=null → result should become 'accepted'.
      await firstValueFrom(http.post('/api/votes/a0000000-0000-0000-0000-0000000000a2/close', {}));
      const m = await get<{ votes: { id: string; result: string | null }[] }>('/api/meetings/m1');
      const v = m.votes.find((x) => x.id === 'a0000000-0000-0000-0000-0000000000a2');
      expect(v?.result).toBe('accepted');
    });

    it('POST /votes/{id}/open on a vote keeps its existing result (status branch)', async () => {
      // open uses status === 'closed' ? ... : v.result → keeps result on open.
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
      expect(m.title).toBe('Neue Sitzung'); // trimmed
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

    // ----- PATCH branches -----
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

    it('PATCH /meetings/{id} with no body keeps the existing fields', async () => {
      const m = await firstValueFrom(
        http.patch<{ status: string; activeApplicationId: string | null }>('/api/meetings/m1', {}),
      );
      expect(m.status).toBeTruthy();
      // activeApplicationId stays whatever it was (not undefined).
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

    it('PATCH …/agenda/{itemId} with no body defaults to empty string', async () => {
      const added = await firstValueFrom(
        http.post<{ id: string }[]>('/api/meetings/m1/agenda', { title: 'TOP Y' }),
      );
      const id = added[added.length - 1].id;
      const res = await firstValueFrom(
        http.patch<{ id: string; body?: string }[]>(`/api/meetings/m1/agenda/${id}`, {}),
      );
      expect(res.find((a) => a.id === id)?.body).toBe('');
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

    // ----- DELETE branches -----
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

    it('DELETE on an unmatched /api path falls through to next()', () => {
      http.delete('/api/applications/x').subscribe();
      // No agenda regex match → falls through to the testing backend.
      ctrl.expectOne('/api/applications/x').flush(null);
    });
  });
});
