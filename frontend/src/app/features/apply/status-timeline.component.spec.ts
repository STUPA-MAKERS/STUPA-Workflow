import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { ToastService } from '@stupa-makers/ui-kit';
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
  getApplication?: Partial<ApiClient>['getApplication'];
  update?: jest.Mock;
  addComment?: jest.Mock;
  applicantTransitions?: Partial<ApiClient>['applicantTransitions'];
  fireApplicant?: jest.Mock;
  timeline?: Partial<ApiClient>['timeline'];
  comments?: Partial<ApiClient>['comments'];
  effectiveForm?: Partial<ApiClient>['effectiveForm'];
  requestErasure?: jest.Mock;
}

function fakeApi(o: ApiOverrides = {}): Partial<ApiClient> {
  return {
    verifyMagicLink: o.verify ?? (() => of({ application_id: 'app-1', scope: 'edit' as const })),
    getApplication: o.getApplication ?? (() => of(o.application ?? app(true))),
    timeline: o.timeline ?? (() => of(TIMELINE)),
    comments: o.comments ?? (() => of(COMMENTS)),
    listAttachments: () => of([]),
    applicantTransitions: (o.applicantTransitions ?? (() => of([]))) as ApiClient['applicantTransitions'],
    fireApplicantTransition: (o.fireApplicant ??
      jest.fn(() =>
        of({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] }),
      )) as unknown as ApiClient['fireApplicantTransition'],
    effectiveForm: (o.effectiveForm ?? (() => of(EFF))) as ApiClient['effectiveForm'],
    updateApplication: (o.update ?? jest.fn(() => of(app(true)))) as unknown as ApiClient['updateApplication'],
    addComment: (o.addComment ?? jest.fn(() => of(COMMENTS[0]))) as unknown as ApiClient['addComment'],
    requestErasure: (o.requestErasure ?? jest.fn(() => of(undefined))) as unknown as ApiClient['requestErasure'],
  };
}

interface RouteOpts {
  pathParams?: Record<string, string>;
  fragment?: string | null;
  toast?: Partial<ToastService>;
}

async function setup(
  api: Partial<ApiClient>,
  params: Record<string, string>,
  opts: RouteOpts = {},
) {
  const providers: Parameters<typeof render>[1]['providers'] = [
    provideRouter([]),
    provideFormly(),
    { provide: ApiClient, useValue: api },
    {
      provide: ActivatedRoute,
      useValue: {
        snapshot: {
          queryParamMap: convertToParamMap(params),
          paramMap: convertToParamMap(opts.pathParams ?? {}),
          fragment: opts.fragment ?? null,
        },
      },
    },
  ];
  if (opts.toast) providers.push({ provide: ToastService, useValue: opts.toast });
  return render(StatusTimelineComponent, { providers });
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

  it('renders cost positions as a compact sum instead of [object Object]', async () => {
    const eff: EffectiveForm = {
      ...EFF,
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [
            { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
            { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } },
          ],
        },
      ],
    };
    const locked = app(false, {
      title: 'Sommerfest',
      kosten: [
        { label: 'Zelt', offers: [{ value: 120, preferred: true }, { value: 150 }] },
        { label: 'Musik', offers: [{ value: 80, preferred: true }] },
      ],
    });
    await setup(fakeApi({ application: locked, effectiveForm: () => of(eff) }), { t: 'tok', app: 'app-1' });
    expect(await screen.findByText('Kostenaufstellung')).toBeInTheDocument();
    expect(screen.getByText(/2 ×.*200/)).toBeInTheDocument();
    expect(screen.queryByText(/\[object Object\]/)).not.toBeInTheDocument();
  });

  it('translates machine vote notes in the timeline', async () => {
    const timeline: TimelineEntry[] = [
      ...TIMELINE,
      { toStateId: 's2', toState: null, label: 'Genehmigt', actor: null, at: '2026-06-11T10:37:00Z', note: 'vote:passed' },
    ];
    await setup(fakeApi({ timeline: () => of(timeline) }), { t: 'tok', app: 'app-1' });
    expect(await screen.findByText('Abstimmungsergebnis: Angenommen')).toBeInTheDocument();
    expect(screen.queryByText('vote:passed')).not.toBeInTheDocument();
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

  it('loads via existing cookie session when only an app id is present (no token)', async () => {
    const verify = jest.fn(() => of({ application_id: 'app-1', scope: 'edit' as const }));
    // No token, only app id → goes straight to load(), never verifies.
    await setup(fakeApi({ verify }), { app: 'app-1' });
    expect(await screen.findByText('Bitte ergänzen.')).toBeInTheDocument();
    expect(verify).not.toHaveBeenCalled();
  });

  it('errors when neither token nor app id can be resolved', async () => {
    await setup(fakeApi(), {});
    expect(await screen.findByText(/Antrag nicht gefunden/)).toBeInTheDocument();
  });

  it('shows an expired notice when the application load fails with 410', async () => {
    await setup(
      fakeApi({ getApplication: () => throwError(() => ({ status: 410 })) }),
      { app: 'app-1' },
    );
    expect(await screen.findByText(/Link abgelaufen/)).toBeInTheDocument();
  });

  it('shows a generic error when the application load fails (non-410)', async () => {
    await setup(
      fakeApi({ getApplication: () => throwError(() => ({ status: 500 })) }),
      { app: 'app-1' },
    );
    expect(await screen.findByText(/Antrag nicht gefunden/)).toBeInTheDocument();
  });

  it('still becomes ready when the applicant transitions fail (catchError → [])', async () => {
    await setup(
      fakeApi({ applicantTransitions: () => throwError(() => ({ status: 500 })) }),
      { t: 'tok', app: 'app-1' },
    );
    // Page renders despite the failed (optional) transitions call.
    expect(await screen.findByText('Bitte ergänzen.')).toBeInTheDocument();
  });

  it('still becomes ready when the effective form fails to load', async () => {
    const { fixture } = await setup(
      fakeApi({ effectiveForm: () => throwError(() => ({ status: 404 })) }),
      { t: 'tok', app: 'app-1' },
    );
    await screen.findByText('Bitte ergänzen.');
    // No edit form / no readonly rows, but phase is ready.
    expect(fixture.componentInstance.phase()).toBe('ready');
    expect(fixture.componentInstance.editFields().length).toBe(0);
  });

  it('uses the kind-based author fallback when a comment has no explicit author', async () => {
    const comments: ApplicationComment[] = [
      { id: 'c2', author: null, authorKind: 'applicant', body: 'Hallo', visibility: 'public', isPublic: true, at: '2026-06-05T13:00:00Z' },
      { id: 'c3', author: null, authorKind: 'principal', body: 'Antwort', visibility: 'public', isPublic: true, at: '2026-06-05T14:00:00Z' },
    ];
    await setup(fakeApi({ comments: () => of(comments) }), { t: 'tok', app: 'app-1' });
    await screen.findByText('Hallo');
    // applicant fallback + committee fallback both rendered.
    expect(screen.getByText('Antragsteller:in')).toBeInTheDocument();
    expect(screen.getByText('Gremium')).toBeInTheDocument();
  });

  it('toasts when firing an applicant transition fails', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const fire = jest.fn(() => throwError(() => ({ status: 409 })));
    const tx = [{ id: 'tr-x', fromStateId: 's1', toStateId: 's2', label: 'Zurückziehen', color: null }];
    const { fixture } = await setup(
      fakeApi({ applicantTransitions: () => of(tx), fireApplicant: fire }),
      { t: 'tok', app: 'app-1' },
      { toast },
    );
    const btn = await screen.findByRole('button', { name: 'Zurückziehen' });
    await userEvent.click(btn);
    expect(fire).toHaveBeenCalledWith('app-1', { transitionId: 'tr-x' });
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    // firing flag is cleared again after the error.
    expect(fixture.componentInstance.firing()).toBeNull();
  });

  it('ignores a second fire while one transition is already firing', async () => {
    const fire = jest.fn(() => of({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] }));
    const tx = [{ id: 'tr-x', fromStateId: 's1', toStateId: 's2', label: 'Zurückziehen', color: null }];
    const { fixture } = await setup(
      fakeApi({ applicantTransitions: () => of(tx), fireApplicant: fire }),
      { t: 'tok', app: 'app-1' },
    );
    const comp = fixture.componentInstance;
    await screen.findByRole('button', { name: 'Zurückziehen' });
    comp.firing.set('busy'); // simulate a transition already in flight
    comp.fireAction(tx[0]);
    expect(fire).not.toHaveBeenCalled();
  });

  it('renders a non-vote timeline note verbatim', async () => {
    const timeline: TimelineEntry[] = [
      { toStateId: 's1', toState: null, label: 'Eingereicht', actor: 'applicant', at: '2026-06-05T10:00:00Z', note: 'Bitte schnell prüfen' },
    ];
    await setup(fakeApi({ timeline: () => of(timeline) }), { t: 'tok', app: 'app-1' });
    expect(await screen.findByText('Bitte schnell prüfen')).toBeInTheDocument();
  });

  it('does not save when the edit form is invalid (marks touched, no PATCH)', async () => {
    const update = jest.fn(() => of(app(true)));
    // Title required → empty data makes the formly form invalid.
    const blank = app(true, {});
    const { fixture } = await setup(
      fakeApi({ application: blank, update }),
      { t: 'tok', app: 'app-1' },
    );
    await screen.findByLabelText(/Titel/);
    const comp = fixture.componentInstance;
    comp.save();
    expect(update).not.toHaveBeenCalled();
    expect(comp.editForm.touched).toBe(true);
  });

  it('does not save while a save is already in flight or when not editable', async () => {
    const update = jest.fn(() => of(app(true)));
    const { fixture } = await setup(fakeApi({ update }), { t: 'tok', app: 'app-1' });
    await screen.findByLabelText(/Titel/);
    const comp = fixture.componentInstance;
    comp.saving.set(true);
    comp.save();
    expect(update).not.toHaveBeenCalled();
  });

  it('handles a 409 on save by re-fetching the application and toasting locked', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const getApp = jest
      .fn()
      .mockReturnValueOnce(of(app(true))) // initial load
      .mockReturnValue(of(app(false))); // re-fetch after 409
    const update = jest.fn(() => throwError(() => ({ status: 409 })));
    const { fixture } = await setup(
      fakeApi({ getApplication: getApp as unknown as ApiClient['getApplication'], update }),
      { t: 'tok', app: 'app-1' },
      { toast },
    );
    await screen.findByLabelText(/Titel/);
    fixture.componentInstance.save();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Antrag ist gesperrt und kann nicht mehr bearbeitet werden.'));
    expect(update).toHaveBeenCalled();
    // re-fetch happened (initial + reload).
    expect(getApp.mock.calls.length).toBeGreaterThan(1);
  });

  it('toasts the problem detail on a non-409 save failure', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const update = jest.fn(() => throwError(() => ({ status: 422, error: { detail: 'Pflichtfeld fehlt' } })));
    const { fixture } = await setup(fakeApi({ update }), { t: 'tok', app: 'app-1' }, { toast });
    await screen.findByLabelText(/Titel/);
    fixture.componentInstance.save();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Pflichtfeld fehlt'));
  });

  it('falls back to a generic save-failed toast without a problem detail', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const update = jest.fn(() => throwError(() => ({ status: 500 })));
    const { fixture } = await setup(fakeApi({ update }), { t: 'tok', app: 'app-1' }, { toast });
    await screen.findByLabelText(/Titel/);
    fixture.componentInstance.save();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.'));
  });

  it('requests erasure and toasts success', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const requestErasure = jest.fn(() => of(undefined));
    const { fixture } = await setup(
      fakeApi({ requestErasure }),
      { t: 'tok', app: 'app-1' },
      { toast },
    );
    await screen.findByLabelText(/Titel/);
    const comp = fixture.componentInstance;
    comp.confirmErase.set(true);
    comp.doRequestErasure();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Löschantrag eingegangen.'));
    expect(requestErasure).toHaveBeenCalledWith('app-1');
    expect(comp.confirmErase()).toBe(false);
    expect(comp.requestingErasure()).toBe(false);
  });

  it('toasts a failure when the erasure request fails', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const requestErasure = jest.fn(() => throwError(() => ({ status: 500 })));
    const { fixture } = await setup(
      fakeApi({ requestErasure }),
      { t: 'tok', app: 'app-1' },
      { toast },
    );
    await screen.findByLabelText(/Titel/);
    const comp = fixture.componentInstance;
    comp.doRequestErasure();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Löschantrag fehlgeschlagen.'));
    expect(comp.requestingErasure()).toBe(false);
  });

  it('ignores a second erasure request while one is already in flight', async () => {
    const requestErasure = jest.fn(() => of(undefined));
    const { fixture } = await setup(fakeApi({ requestErasure }), { t: 'tok', app: 'app-1' });
    await screen.findByLabelText(/Titel/);
    const comp = fixture.componentInstance;
    comp.requestingErasure.set(true);
    comp.doRequestErasure();
    expect(requestErasure).not.toHaveBeenCalled();
  });

  it('toasts when posting a comment fails', async () => {
    const toast = { error: jest.fn(), success: jest.fn() };
    const addComment = jest.fn(() => throwError(() => ({ status: 500 })));
    const { fixture } = await setup(
      fakeApi({ addComment }),
      { t: 'tok', app: 'app-1' },
      { toast },
    );
    await screen.findByLabelText(/Öffentlicher Kommentar/);
    await userEvent.type(screen.getByLabelText(/Öffentlicher Kommentar/), 'Hi');
    fixture.componentInstance.addComment();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Kommentar konnte nicht gespeichert werden.'));
    expect(fixture.componentInstance.postingComment()).toBe(false);
  });

  it('does not post an empty/whitespace comment', async () => {
    const addComment = jest.fn(() => of(COMMENTS[0]));
    const { fixture } = await setup(fakeApi({ addComment }), { t: 'tok', app: 'app-1' });
    await screen.findByLabelText(/Öffentlicher Kommentar/);
    const comp = fixture.componentInstance;
    // commentBody invalid (required) when empty → guarded.
    comp.addComment();
    expect(addComment).not.toHaveBeenCalled();
    // Whitespace-only also bails after the trim().
    comp.commentBody.setValue('   ');
    comp.addComment();
    expect(addComment).not.toHaveBeenCalled();
  });

  it('builds initials from a name and handles edge cases', async () => {
    const { fixture } = await setup(fakeApi(), { t: 'tok', app: 'app-1' });
    await screen.findByText('Bitte ergänzen.');
    const comp = fixture.componentInstance;
    expect(comp.initial('Max Mustermann')).toBe('MM');
    expect(comp.initial('Cher')).toBe('C');
    expect(comp.initial('   ')).toBe('?');
    expect(comp.initial('a b c')).toBe('AC');
  });

  it('strips the magic-link token from the URL after verifying', async () => {
    history.replaceState(null, '', '/antrag/app-1?t=secret-token');
    await setup(fakeApi(), { t: 'secret-token', app: 'app-1' });
    await screen.findByText('Bitte ergänzen.');
    expect(window.location.href).not.toContain('secret-token');
    expect(window.location.search).not.toContain('t=');
  });

  it('strips a fragment-form token and keeps the app id in the path', async () => {
    history.replaceState(null, '', '/antrag/app-1#t=frag-token');
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
              fragment: 't=frag-token',
            },
          },
        },
      ],
    });
    await screen.findByText('Bitte ergänzen.');
    expect(window.location.hash).not.toContain('frag-token');
  });

  it('keeps other fragment params while stripping the magic-link token', async () => {
    // Fragment carries both a token and another param → after deleting `t`,
    // the remaining fragment must be preserved (the non-empty hash branch).
    history.replaceState(null, '', '/antrag/app-1#t=frag-token&foo=bar');
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
              fragment: 't=frag-token&foo=bar',
            },
          },
        },
      ],
    });
    await screen.findByText('Bitte ergänzen.');
    expect(window.location.hash).not.toContain('frag-token');
    expect(window.location.hash).toContain('foo=bar');
  });

  it('renders locked read-only edge cases: hidden field, false boolean, empty positions', async () => {
    const eff: EffectiveForm = {
      ...EFF,
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [
            { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
            { key: 'consent', type: 'checkbox', label: { de: 'Zustimmung' } },
            {
              key: 'hidden',
              type: 'text',
              label: { de: 'Versteckt' },
              visibleIf: { '==': [{ var: 'consent' }, true] },
            },
            { key: 'kosten', type: 'positions', label: { de: 'Kosten' } },
            { key: 'leer', type: 'positions', label: { de: 'Leer' } },
          ],
        },
      ],
    };
    const locked = app(false, {
      title: 'Sommerfest',
      consent: false, // boolean false → "Nein"; also hides the `hidden` field
      hidden: 'darf nicht erscheinen',
      kosten: [{ label: 'Ohne Angebote' }, { label: 'Leeres Angebot', offers: [{ preferred: true }] }],
      leer: 'kein-array', // non-array positions → '' → row dropped
    });
    await setup(fakeApi({ application: locked, effectiveForm: () => of(eff) }), { t: 'tok', app: 'app-1' });
    expect(await screen.findByText('Gesperrt')).toBeInTheDocument();
    expect(screen.getByText('Nein')).toBeInTheDocument(); // false boolean
    // Hidden field (visibleIf false) is not rendered.
    expect(screen.queryByText('darf nicht erscheinen')).not.toBeInTheDocument();
    // Positions with missing/empty offers sum to 0.
    expect(screen.getByText(/2 ×.*0/)).toBeInTheDocument();
    // Non-array positions value dropped its row.
    expect(screen.queryByText('Leer')).not.toBeInTheDocument();
  });

  it('errors when verify returns no application id and none can be derived', async () => {
    // verify succeeds but yields no application_id and there is no fallback id
    // in the path/query → load('') hits the empty-id guard → error phase.
    const verify = jest.fn(() => of({ application_id: null, scope: 'edit' as const }));
    const { fixture } = await setup(
      fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }),
      { t: 'tok' },
    );
    expect(await screen.findByText(/Antrag nicht gefunden/)).toBeInTheDocument();
    expect(fixture.componentInstance.phase()).toBe('error');
  });

  it('adds ?app= when the verified id is not already in the path', async () => {
    // URL has the token in the query but the path does NOT contain the app id,
    // so stripTokenFromUrl must add ?app= for a later reload.
    history.replaceState(null, '', '/status?t=tok-here');
    await setup(fakeApi(), { t: 'tok-here' });
    await screen.findByText('Bitte ergänzen.');
    expect(window.location.search).toContain('app=app-1');
    expect(window.location.search).not.toContain('t=');
  });
});
