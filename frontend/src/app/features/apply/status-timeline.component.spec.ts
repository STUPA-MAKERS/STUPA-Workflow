import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import type {
  Application,
  ApplicationComment,
  EffectiveForm,
  TimelineEntry,
} from '@core/api/models';
import { provideFormly } from '@shared/formly/formly.providers';
import { StatusTimelineComponent } from './status-timeline.component';

function app(editAllowed: boolean, data: Record<string, unknown> = { title: 'Sommerfest' }): Application {
  return {
    id: 'app-1',
    typeId: 't1',
    state: {
      id: 's1',
      key: 'submitted',
      label: editAllowed ? 'Eingereicht' : 'Beschlossen',
      color: '#4a90d9',
      editAllowed,
    },
    gremiumId: null,
    budgetPotId: null,
    amount: null,
    currency: null,
    data,
    version: 1,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T10:00:00Z',
    applicant: null,
  };
}

const EFF: EffectiveForm = {
  applicationTypeId: 't1',
  formVersionId: 'v1',
  sections: [
    {
      key: 'main',
      label: { de: 'Antrag' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
        {
          key: 'category',
          type: 'select',
          label: { de: 'Kategorie' },
          options: [{ value: 'event', label: { de: 'Veranstaltung' } }],
        },
        { key: 'consent', type: 'checkbox', label: { de: 'Zustimmung' } },
        {
          key: 'tags',
          type: 'multiselect',
          label: { de: 'Tags' },
          options: [{ value: 'a', label: { de: 'Alpha' } }],
        },
        { key: 'info', type: 'markdown', label: { de: 'Info' }, help: { de: 'Hinweis' } },
      ],
    },
  ],
};

const TIMELINE: TimelineEntry[] = [
  { toStateId: 's1', toState: null, label: 'Eingereicht', actor: null, at: '2026-06-05T10:00:00Z', note: null },
];

const COMMENTS: ApplicationComment[] = [
  {
    id: 'c1',
    author: 'Referat',
    authorKind: 'principal',
    body: 'Bitte ergänzen.',
    visibility: 'public',
    isPublic: true,
    at: '2026-06-05T13:00:00Z',
  },
];

interface ApiOverrides {
  verify?: Partial<ApiClient>['verifyMagicLink'];
  application?: Application;
  update?: jest.Mock;
  addComment?: jest.Mock;
  applicantTransitions?: Partial<ApiClient>['applicantTransitions'];
  fireApplicant?: jest.Mock;
}

function fakeApi(o: ApiOverrides = {}): Partial<ApiClient> {
  return {
    verifyMagicLink: o.verify ?? (() => of({ application_id: 'app-1', scope: 'edit' as const })),
    getApplication: () => of(o.application ?? app(true)),
    timeline: () => of(TIMELINE),
    comments: () => of(COMMENTS),
    listAttachments: () => of([]),
    applicantTransitions: (o.applicantTransitions ?? (() => of([]))) as ApiClient['applicantTransitions'],
    fireApplicantTransition: (o.fireApplicant ??
      jest.fn(() =>
        of({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] }),
      )) as unknown as ApiClient['fireApplicantTransition'],
    effectiveForm: () => of(EFF),
    updateApplication: (o.update ?? jest.fn(() => of(app(true)))) as unknown as ApiClient['updateApplication'],
    addComment: (o.addComment ?? jest.fn(() => of(COMMENTS[0]))) as unknown as ApiClient['addComment'],
  };
}

async function setup(api: Partial<ApiClient>, params: Record<string, string>) {
  return render(StatusTimelineComponent, {
    providers: [
      provideRouter([]),
      provideFormly(),
      { provide: ApiClient, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            queryParamMap: convertToParamMap(params),
            paramMap: convertToParamMap({}),
            fragment: null,
          },
        },
      },
    ],
  });
}

describe('StatusTimelineComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('verifies the magic-link token and shows status, timeline and comments', async () => {
    await setup(fakeApi(), { t: 'tok', app: 'app-1' });
    expect(await screen.findByText('Bitte ergänzen.')).toBeInTheDocument();
    // Author from the mapped comment (author, not author_name).
    expect(screen.getByText(/Referat/)).toBeInTheDocument();
    // Status-Badge + Timeline tragen beide das Label.
    expect(screen.getAllByText('Eingereicht').length).toBeGreaterThan(1);
    // editierbar → Bearbeitungs-Formular sichtbar
    expect(screen.getByLabelText(/Titel/)).toBeInTheDocument();
  });

  it('renders applicant actions and fires the chosen transition', async () => {
    const fire = jest.fn(() => of({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] }));
    const tx = [
      { id: 'tr-x', fromStateId: 's1', toStateId: 's2', label: 'Zurückziehen', color: null },
    ];
    await setup(
      fakeApi({ applicantTransitions: () => of(tx), fireApplicant: fire }),
      { t: 'tok', app: 'app-1' },
    );
    const btn = await screen.findByRole('button', { name: 'Zurückziehen' });
    await userEvent.click(btn);
    expect(fire).toHaveBeenCalledWith('app-1', { transitionId: 'tr-x' });
  });

  it('reads the token from the fragment and the id from the path (/antrag/:id#t=)', async () => {
    await render(StatusTimelineComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ApiClient, useValue: fakeApi() },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({}),
              paramMap: convertToParamMap({ id: 'app-1' }),
              fragment: 't=tok',
            },
          },
        },
      ],
    });
    // Token aus dem Fragment → Verify → Status sichtbar (kein 404, keine Query nötig).
    expect(await screen.findByText('Bitte ergänzen.')).toBeInTheDocument();
  });

  it('renders formatted read-only data and a lock badge when the status is not editable', async () => {
    const locked = app(false, { title: 'Sommerfest', category: 'event', consent: true, tags: ['a'] });
    await setup(fakeApi({ application: locked }), { t: 'tok', app: 'app-1' });
    expect(await screen.findByText('Gesperrt')).toBeInTheDocument();
    expect(screen.getByText('Sommerfest')).toBeInTheDocument();
    expect(screen.getByText('Veranstaltung')).toBeInTheDocument(); // select → Option-Label
    expect(screen.getByText('Ja')).toBeInTheDocument(); // checkbox → boolean
    expect(screen.getByText('Alpha')).toBeInTheDocument(); // multiselect → Array
    expect(screen.queryByRole('button', { name: /Änderungen speichern/ })).not.toBeInTheDocument();
  });

  it('saves edited data via PATCH', async () => {
    const update = jest.fn(() => of(app(true)));
    await setup(fakeApi({ update }), { t: 'tok', app: 'app-1' });
    await screen.findByLabelText(/Titel/);
    await userEvent.click(screen.getByRole('button', { name: /Änderungen speichern/ }));
    expect(update).toHaveBeenCalledWith('app-1', expect.objectContaining({ title: 'Sommerfest' }));
  });

  it('posts a public comment', async () => {
    const addComment = jest.fn(() => of(COMMENTS[0]));
    await setup(fakeApi({ addComment }), { t: 'tok', app: 'app-1' });
    await screen.findByLabelText(/Öffentlicher Kommentar/);
    await userEvent.type(screen.getByLabelText(/Öffentlicher Kommentar/), 'Danke!');
    await userEvent.click(screen.getByRole('button', { name: /Kommentar senden/ }));
    expect(addComment).toHaveBeenCalledWith('app-1', 'Danke!');
  });

  it('shows an expired notice when the token is gone (410)', async () => {
    await setup(fakeApi({ verify: () => throwError(() => ({ status: 410 })) }), { t: 'old' });
    expect(await screen.findByText(/Link abgelaufen/)).toBeInTheDocument();
  });

  it('shows a generic error notice on a non-410 verify failure', async () => {
    await setup(fakeApi({ verify: () => throwError(() => ({ status: 500 })) }), { t: 'x' });
    expect(await screen.findByText(/Antrag nicht gefunden/)).toBeInTheDocument();
  });

  it('shows an error notice when no link is provided', async () => {
    await setup(fakeApi(), {});
    expect(await screen.findByText(/Antrag nicht gefunden/)).toBeInTheDocument();
  });

  it('renders the status page in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup(fakeApi(), { t: 'tok', app: 'app-1' });
    expect(await screen.findByRole('heading', { name: 'Application status' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save changes/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/Public comment/)).toBeInTheDocument();
    expect(screen.queryByText('Antragsstatus')).not.toBeInTheDocument();
  });

  it('localizes the expired notice in English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup(fakeApi({ verify: () => throwError(() => ({ status: 410 })) }), { t: 'old' });
    expect(await screen.findByText(/Link expired/)).toBeInTheDocument();
  });
});
