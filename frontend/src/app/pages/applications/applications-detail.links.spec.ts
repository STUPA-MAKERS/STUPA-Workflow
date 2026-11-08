/**
 * The Folgeanträge of the application detail page: the Vorgänger and the Folgeanträge in
 * the Details card, the dialog that links or removes the Vorgänger, and the link entries
 * of the history.
 *
 * Its own spec file, like the comments: the base spec of the component is already large.
 */
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { fireEvent, render, screen } from '@testing-library/angular';
import { BehaviorSubject } from 'rxjs';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { ApplicationsPageService } from './applications-page.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import type {
  ApplicationLinksWire,
  ApplicationListItem,
  ApplicationOutWire,
  StateOutWire,
} from '@core/api/models';
import { NO_LINKED_TODOS } from '../../../testing/todo-fixtures';

const SUBMITTED: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};

function appWire(canEdit: boolean): ApplicationOutWire {
  return {
    id: 'app-1',
    typeId: 't1',
    state: SUBMITTED,
    gremiumId: null,
    budgetId: null,
    amount: '250.00',
    currency: 'EUR',
    data: { title: 'Förderung Fest' },
    version: 1,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T11:00:00Z',
    canEdit,
    applicant: { email: 'a@stupa', name: 'Mia', anonymized: false },
  };
}

const LINKS: ApplicationLinksWire = {
  predecessor: { id: 'p-1', title: 'Sommerfest 2025', state: SUBMITTED, createdAt: '2025-05-12T10:00:00Z' },
  successors: [{ id: 's-1', title: null, createdAt: '2026-11-01T10:00:00Z' }],
  events: [
    {
      action: 'set',
      at: '2026-06-06T10:00:00Z',
      actorInfo: { kind: 'principal', displayName: 'Mara Keller', principalId: 'p-9' },
      predecessor: { id: 'p-1', title: 'Sommerfest 2025', createdAt: '2025-05-12T10:00:00Z' },
    },
    { action: 'removed', at: '2026-06-07T10:00:00Z', predecessor: null },
    {
      action: 'set',
      at: '2026-06-08T10:00:00Z',
      predecessor: { id: 'p-2', title: null, createdAt: '2025-05-12T10:00:00Z' },
    },
  ],
};

const EMPTY: ApplicationLinksWire = { predecessor: null, successors: [], events: [] };

const PICK: ApplicationListItem = {
  id: 'p-3',
  typeId: 't1',
  title: 'Sommerfest 2024',
  state: null,
  gremiumId: null,
  amount: null,
  currency: null,
  createdAt: '2024-05-12T10:00:00Z',
  updatedAt: '2024-05-12T10:00:00Z',
  archivedAt: null,
};

function fakeAuth(permissions: string[]): Partial<AuthService> {
  return {
    can: (p: string) => permissions.includes(p),
    roles: (() => []) as unknown as AuthService['roles'],
    isAuthenticated: (() => true) as unknown as AuthService['isAuthenticated'],
  };
}

function splitPage(): ApplicationsPageService {
  const page = new ApplicationsPageService();
  page.split.set(true);
  return page;
}

const url = (suffix: string) => (r: { url: string }) => r.url === `/api/applications/app-1${suffix}`;

/** Load the page and answer every request of the load; `/links` answers with `links`. */
async function loaded(links: ApplicationLinksWire, canEdit = true) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      NO_LINKED_TODOS,
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(['application.read']) },
      { provide: RailStatusService, useValue: { refresh: jest.fn() } },
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
          fragment: new BehaviorSubject<string | null>(null),
          snapshot: { fragment: null },
        },
      },
      { provide: ApplicationsPageService, useFactory: splitPage },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const cmp = view.fixture.componentInstance;
  const rest = () => {
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/application-types')) {
      req.flush({ items: [], total: 0, limit: 20, offset: 0 });
    }
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) req.flush([]);
    for (const req of http.match((r) => r.method === 'GET' && /\/(attachments|timeline|mentionable|versions|comments)$/.test(r.url))) {
      req.flush([]);
    }
    for (const req of http.match(url('/form'))) req.flush({ applicationTypeId: 't1', formVersionId: 'fv1', sections: [] });
  };
  rest();
  http.expectOne(url('')).flush(appWire(canEdit));
  rest();
  view.detectChanges();
  rest();
  for (const req of http.match(url('/links'))) req.flush(links);
  view.detectChanges();
  rest();
  view.detectChanges();
  return { ...view, http, toast, cmp };
}

describe('ApplicationsDetailComponent — Folgeanträge', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('shows the Vorgänger, the Folgeanträge and the link entries of the history', async () => {
    const { cmp } = await loaded(LINKS);
    expect(screen.getByRole('link', { name: 'Sommerfest 2025' })).toBeInTheDocument();
    expect(screen.getByTestId('ad-predecessor')).toHaveTextContent('Ändern');
    expect(screen.getByText('Folgeanträge')).toBeInTheDocument();
    const links = cmp.historyEntries().filter((e) => e.icon === 'link');
    expect(links.map((e) => [e.title, e.body, e.actor ?? null])).toEqual([
      ['Vorgänger verknüpft', 'Sommerfest 2025', 'Mara Keller'],
      ['Vorgänger entfernt', 'Ein Antrag, den du nicht öffnen kannst', null],
      ['Vorgänger verknüpft', 'Ohne Titel', null],
    ]);
    expect(links[0].link?.route).toEqual(['/applications', 'p-1']);
    expect(links[1].link).toBeNull();
  });

  it('offers "Verknüpfen" without a Vorgänger', async () => {
    await loaded(EMPTY);
    expect(screen.getByTestId('ad-predecessor')).toHaveTextContent('Verknüpfen');
    expect(screen.getByText('Keiner')).toBeInTheDocument();
    expect(screen.queryByText('Folgeanträge')).toBeNull();
  });

  it('hides the Vorgänger row without the edit right and without a Vorgänger', async () => {
    await loaded(EMPTY, false);
    expect(screen.queryByTestId('ad-predecessor')).toBeNull();
    expect(screen.queryByText('Keiner')).toBeNull();
  });

  it('links a Vorgänger from the dialog and ignores a second click while it runs', async () => {
    const { cmp, http, toast, detectChanges } = await loaded(EMPTY);
    const success = jest.spyOn(toast, 'success');
    fireEvent.click(screen.getByTestId('ad-predecessor'));
    detectChanges();
    expect(cmp.predecessorOpen()).toBe(true);
    cmp.setPredecessor(PICK);
    cmp.setPredecessor(PICK);
    const req = http.expectOne(url('/predecessor'));
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ predecessorId: 'p-3' });
    req.flush(LINKS);
    detectChanges();
    expect(cmp.predecessorOpen()).toBe(false);
    expect(cmp.links()?.predecessor?.id).toBe('p-1');
    expect(success).toHaveBeenCalledWith('Vorgänger verknüpft');
  });

  it('names the reason when the link is refused', async () => {
    const { cmp, http, toast } = await loaded(EMPTY);
    const error = jest.spyOn(toast, 'error');
    cmp.setPredecessor(PICK);
    http
      .expectOne(url('/predecessor'))
      .flush({ code: 'predecessor_cycle' }, { status: 422, statusText: 'Unprocessable Entity' });
    expect(error).toHaveBeenCalledWith('Dieser Antrag ist schon ein Vorgänger des gewählten Antrags.');
    expect(cmp.linking()).toBe(false);
  });

  it('removes the Vorgänger and reads the links again', async () => {
    const { cmp, http, toast, detectChanges } = await loaded(LINKS);
    const success = jest.spyOn(toast, 'success');
    cmp.predecessorOpen.set(true);
    detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Vorgänger entfernen' }));
    cmp.removePredecessor();
    const del = http.expectOne(url('/predecessor'));
    expect(del.request.method).toBe('DELETE');
    del.flush(null);
    expect(success).toHaveBeenCalledWith('Vorgänger entfernt');
    http.expectOne(url('/links')).flush(EMPTY);
    detectChanges();
    expect(cmp.links()?.predecessor).toBeNull();
    expect(cmp.linking()).toBe(false);
  });

  it('a failed reload after the removal and a refused removal free the dialog', async () => {
    const { cmp, http, toast } = await loaded(LINKS);
    const error = jest.spyOn(toast, 'error');
    cmp.removePredecessor();
    http.expectOne(url('/predecessor')).flush(null);
    http.expectOne(url('/links')).flush(null, { status: 500, statusText: 'Error' });
    expect(cmp.linking()).toBe(false);
    cmp.removePredecessor();
    http.expectOne(url('/predecessor')).flush(null, { status: 403, statusText: 'Forbidden' });
    expect(error).toHaveBeenCalledWith('Du brauchst Bearbeitungsrechte auf beiden Anträgen.');
    expect(cmp.linking()).toBe(false);
  });
});
