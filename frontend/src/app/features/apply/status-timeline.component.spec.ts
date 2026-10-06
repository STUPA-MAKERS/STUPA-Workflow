import { signal } from '@angular/core';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { BrandingService } from '@core/branding/branding.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type {
  Application,
  ApplicationComment,
  ApplicationVersion,
  EffectiveForm,
  TimelineEntry,
  Transition,
} from '@core/api/models';
import { provideFormly } from '@shared/formly/formly.providers';
import { StatusTimelineComponent } from './status-timeline.component';

const ID = '3f9a2c71-1111-2222-3333-444444444444';

function app(editAllowed: boolean, data: Record<string, unknown> = { title: 'Sommerfest' }): Application {
  return {
    id: ID,
    typeId: 't1',
    state: { id: 's1', key: 'agenda', label: 'Auf Tagesordnung', color: '#72a384', editAllowed },
    gremiumId: null,
    budgetPotId: null,
    amount: null,
    currency: null,
    data,
    version: 2,
    lang: 'de',
    createdAt: '2026-09-26T10:00:00Z',
    updatedAt: '2026-09-27T10:00:00Z',
    stateSince: '2026-09-28T14:20:00Z',
    applicant: null,
    hiddenKeys: [],
  } as Application;
}

const EFF: EffectiveForm = {
  applicationTypeId: 't1',
  formVersionId: 'v1',
  hasBudget: false,
  sections: [
    {
      key: 'main',
      label: { de: 'Vorhaben' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
        { key: 'participants', type: 'number', label: { de: 'Erwartete Teilnehmende' } },
        { key: 'receipt', type: 'file', label: { de: 'Beleg' } },
      ],
    },
  ],
};

const TIMELINE: TimelineEntry[] = [
  { toStateId: 's0', toState: null, label: 'Eingereicht', actor: 'applicant', at: '2026-09-26T12:12:00Z', note: null },
  {
    toStateId: 's1',
    toState: { id: 's1', key: 'agenda', label: 'Auf Tagesordnung', color: '#72a384', editAllowed: false },
    label: 'Auf Tagesordnung',
    transitionLabel: 'Auf Tagesordnung setzen',
    actor: 'Studierendenparlament',
    at: '2026-09-28T14:20:00Z',
    note: 'vote:tie',
  },
];

const VERSIONS: ApplicationVersion[] = [
  { version: 1, data: {}, diff: null, changedKeys: [], changedBy: 'applicant', at: '2026-09-26T12:12:00Z' },
  {
    version: 2,
    data: {},
    diff: null,
    changedKeys: ['participants', 'unknown_key'],
    changedBy: 'applicant',
    at: '2026-09-27T19:05:00Z',
  },
  { version: 3, data: {}, diff: null, changedKeys: [], changedBy: 'Studierendenparlament', at: '2026-09-27T20:05:00Z' },
];

const COMMENTS: ApplicationComment[] = [
  {
    id: 'c1',
    author: 'Studierendenparlament',
    authorKind: 'principal',
    body: 'Bitte ergänzen.',
    visibility: 'public',
    isPublic: true,
    isOwn: false,
    at: '2026-09-28T13:00:00Z',
  },
  {
    id: 'c2',
    author: 'Erika',
    authorKind: 'applicant',
    body: 'Erledigt.',
    visibility: 'public',
    isPublic: true,
    isOwn: true,
    at: '2026-09-28T14:00:00Z',
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
  versions?: Partial<ApiClient>['versions'];
  comments?: Partial<ApiClient>['comments'];
  listAttachments?: Partial<ApiClient>['listAttachments'];
  effectiveForm?: Partial<ApiClient>['effectiveForm'];
  requestErasure?: jest.Mock;
}

function fakeApi(o: ApiOverrides = {}): Partial<ApiClient> {
  return {
    verifyMagicLink: o.verify ?? (() => of({ application_id: ID, scope: 'edit' as const })),
    getApplication: o.getApplication ?? (() => of(o.application ?? app(true))),
    timeline: o.timeline ?? (() => of(TIMELINE)),
    versions: o.versions ?? (() => of(VERSIONS)),
    comments: o.comments ?? (() => of(COMMENTS)),
    listAttachments:
      o.listAttachments ??
      (() =>
        of([
          { id: 'f1', filename: 'Angebot.pdf', mime: 'application/pdf', size: 1000, scanned: true, isComparisonOffer: false, scanState: 'clean' as const },
        ])),
    applicantTransitions: (o.applicantTransitions ?? (() => of([]))) as ApiClient['applicantTransitions'],
    fireApplicantTransition: (o.fireApplicant ??
      jest.fn(() => of({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] }))) as unknown as ApiClient['fireApplicantTransition'],
    effectiveForm: (o.effectiveForm ?? (() => of(EFF))) as ApiClient['effectiveForm'],
    updateApplication: (o.update ?? jest.fn(() => of({ ...app(true), version: 3 }))) as unknown as ApiClient['updateApplication'],
    addComment: (o.addComment ?? jest.fn(() => of(COMMENTS[0]))) as unknown as ApiClient['addComment'],
    requestErasure: (o.requestErasure ?? jest.fn(() => of(undefined))) as unknown as ApiClient['requestErasure'],
    attachmentUrl: jest.fn(),
  };
}

interface RouteOpts {
  pathParams?: Record<string, string>;
  fragment?: string | null;
  linkTtlDays?: number | null;
  /** The public config loaded (default true). */
  loaded?: boolean;
}

async function setup(api: Partial<ApiClient>, params: Record<string, string> = { app: ID }, opts: RouteOpts = {}) {
  const toast = { error: jest.fn(), success: jest.fn(), show: jest.fn() };
  const view = await render(StatusTimelineComponent, {
    providers: [
      provideRouter([]),
      provideFormly(),
      { provide: ApiClient, useValue: api },
      { provide: ToastService, useValue: toast },
      {
        provide: BrandingService,
        useValue: {
          linkTtlDays: signal(opts.linkTtlDays === undefined ? null : opts.linkTtlDays),
          loaded: signal(opts.loaded ?? true),
        },
      },
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
    ],
  });
  return { ...view, comp: view.fixture.componentInstance, toast };
}

describe('StatusTimelineComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    window.scrollTo = jest.fn();
  });
  afterEach(() => localStorage.clear());

  it('verifies the token and shows reference, title, status and since', async () => {
    const verify = jest.fn(() => of({ application_id: ID, scope: 'edit' as const }));
    await setup(fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }), { t: 'tok', app: ID });
    expect(await screen.findByRole('heading', { level: 1, name: 'Sommerfest' })).toBeInTheDocument();
    expect(verify).toHaveBeenCalledWith('tok');
    expect(screen.getByText('Vorgang 3F9A2C71')).toBeInTheDocument();
    expect(screen.queryByText(ID)).toBeNull();
    expect(screen.getAllByText('Auf Tagesordnung')[0].tagName).toBe('APP-STATUS-TEXT');
    expect(screen.getByText(/^seit /)).toBeInTheDocument();
    expect(screen.getByText('1 Datei')).toBeInTheDocument();
    expect(screen.getByText('2 Kommentare')).toBeInTheDocument();
    expect(screen.getByText('Dein Link ist unbegrenzt gültig.')).toBeInTheDocument();
  });

  it('builds the history: status changes with the transition and versions as metadata', async () => {
    const { comp } = await setup(fakeApi());
    await screen.findByRole('heading', { level: 1 });
    const entries = comp.historyEntries();
    expect(entries.map((e) => [e.title, e.actor, e.body])).toEqual([
      ['Eingereicht', 'Du', null],
      ['Auf Tagesordnung', 'Studierendenparlament', 'Übergang „Auf Tagesordnung setzen“\nAbstimmungsergebnis: Abgelehnt'],
      ['Version 2 gespeichert', 'Du', 'Geändert: Erwartete Teilnehmende, unknown_key'],
      ['Version 3 gespeichert', 'Studierendenparlament', null],
    ]);
    expect(entries[0].icon).toBe('send');
    expect(entries[1].kind).toBe('accent');
    const history = document.querySelector('.sp__history') as HTMLElement;
    expect(within(history).getByText('Version 2 gespeichert')).toBeInTheDocument();
  });

  it('keeps version 1 when the timeline is empty, and shows an empty history', async () => {
    const { comp } = await setup(fakeApi({ timeline: () => of([]), versions: () => of([]) }));
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByText('Noch keine Ereignisse.')).toBeInTheDocument();
    comp.versions.set([VERSIONS[0]]);
    expect(comp.historyEntries().map((e) => e.title)).toEqual(['Version 1 gespeichert']);
  });

  it('names a vote that went with its meeting', async () => {
    const { comp } = await setup(fakeApi({ timeline: () => of([]), versions: () => of([]) }));
    await screen.findByRole('heading', { level: 1 });
    comp.timeline.set([
      {
        toStateId: 's9',
        toState: null,
        label: 'Genehmigt',
        actor: null,
        at: '2026-06-05T10:00:00Z',
        note: 'vote:passed',
        voteId: null,
        voteDeleted: true,
      },
    ]);
    expect(comp.historyEntries()[0].body).toBe(
      'Abstimmungsergebnis: Angenommen\nAbstimmung gelöscht (mit Sitzung)',
    );
  });

  it('translates vote notes and keeps other notes', async () => {
    const { comp } = await setup(fakeApi());
    expect(comp.noteText('vote:passed')).toBe('Abstimmungsergebnis: Angenommen');
    expect(comp.noteText('vote:rejected')).toBe('Abstimmungsergebnis: Abgelehnt');
    expect(comp.noteText('Bitte nachreichen')).toBe('Bitte nachreichen');
  });

  it('locks the edit row in a locked status and says why', async () => {
    await setup(fakeApi({ application: app(false) }));
    const row = (await screen.findByText('Angaben bearbeiten')).closest('button') as HTMLButtonElement;
    expect(row).toBeDisabled();
    expect(screen.getByText('Im aktuellen Status gesperrt')).toBeInTheDocument();
    expect(row).toHaveAttribute('aria-describedby', 'sp-locked');
  });

  it('edits the answers and saves a new version', async () => {
    const update = jest.fn(() => of({ ...app(true, { title: 'Neu' }), version: 3 }));
    const { comp, toast, fixture } = await setup(fakeApi({ update }));
    await userEvent.click(await screen.findByRole('button', { name: /Angaben bearbeiten/ }));
    // The separator keeps its space before the hint.
    expect(screen.getByText(/Speichern legt Version 3 an/).textContent).toMatch(/^ · Speichern/);
    // The focus moves to the title of the edit bar.
    await waitFor(() => expect(document.activeElement?.id).toBe('sp-edit-title'));
    // File fields stay out of the edit form.
    expect(comp.editFields()[0].fieldGroup?.some((f) => f.key === 'receipt')).toBe(false);
    const input = screen.getByLabelText(/Titel/) as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, 'Neu');
    await userEvent.click(screen.getByRole('button', { name: /Speichern/ }));
    expect(update).toHaveBeenCalledWith(ID, expect.objectContaining({ title: 'Neu' }));
    expect(toast.success).toHaveBeenCalledWith('Änderungen gespeichert.');
    expect(comp.editing()).toBe(false);
    fixture.detectChanges();
    expect(screen.getByRole('heading', { level: 1, name: 'Neu' })).toBeInTheDocument();
    // The focus goes back to the row.
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole('button', { name: /Angaben bearbeiten/ })),
    );
  });

  it('cancels the edit and does not edit without a form or the right', async () => {
    const { comp, fixture } = await setup(fakeApi());
    await screen.findByRole('heading', { level: 1 });
    comp.startEdit();
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(comp.editing()).toBe(false);
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole('button', { name: /Angaben bearbeiten/ })),
    );
    comp.effForm.set(null);
    comp.startEdit();
    expect(comp.editing()).toBe(false);
  });

  it('shows the errors of an invalid edit and sends nothing', async () => {
    const update = jest.fn();
    const { comp, toast } = await setup(fakeApi({ update }));
    await screen.findByRole('heading', { level: 1 });
    comp.startEdit();
    comp.editModel['title'] = '';
    comp.editForm.setErrors({ invalid: true });
    comp.save();
    expect(update).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('Bitte prüfe die markierten Felder.');
  });

  it('handles a 409, a 422 on a field and other failures of a save', async () => {
    const update = jest
      .fn()
      .mockReturnValueOnce(throwError(() => ({ status: 409 })))
      .mockReturnValueOnce(throwError(() => ({ status: 422, error: { errors: [{ field: 'title', msg: 'too long' }] } })))
      .mockReturnValueOnce(throwError(() => ({ status: 422, error: { errors: [{ field: 'nope', msg: 'x' }] } })))
      .mockReturnValueOnce(throwError(() => ({ status: 500, error: { detail: 'Kaputt.' } })));
    const getApplication = jest.fn(() => of(app(true)));
    const { comp, toast, fixture } = await setup(fakeApi({ update, getApplication }));
    await screen.findByRole('heading', { level: 1 });
    comp.startEdit();
    comp.save();
    expect(toast.error).toHaveBeenLastCalledWith(
      'Antrag ist gesperrt und kann nicht mehr bearbeitet werden.',
    );
    expect(comp.editing()).toBe(false);
    fixture.detectChanges();
    // The row may go off, so the focus goes to the title of the page.
    await waitFor(() => expect(document.activeElement?.id).toBe('sp-title'));
    expect(getApplication).toHaveBeenCalledTimes(2);
    comp.startEdit();
    fixture.detectChanges();
    comp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Bitte prüfe die markierten Felder.');
    // The field error blocks the next save; a new edit starts clean.
    comp.startEdit();
    fixture.detectChanges();
    comp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Speichern fehlgeschlagen.');
    comp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Kaputt.');
  });

  it('does not save twice or without the right', async () => {
    const update = jest.fn(() => of(app(true)));
    const { comp } = await setup(fakeApi({ update }));
    await screen.findByRole('heading', { level: 1 });
    comp.saving.set(true);
    comp.save();
    comp.saving.set(false);
    comp.application.set(app(false));
    comp.save();
    expect(update).not.toHaveBeenCalled();
  });

  it('opens the attachments in a sheet with the panel', async () => {
    const { comp, fixture } = await setup(fakeApi());
    await userEvent.click(await screen.findByRole('button', { name: /Anhänge/ }));
    expect(comp.filesOpen()).toBe(true);
    fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: 'Anhänge' });
    expect(await within(dialog).findByText('Angebot.pdf')).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Schließen' }));
    expect(comp.filesOpen()).toBe(false);
  });

  it('hides the count when the attachments cannot be listed', async () => {
    await setup(fakeApi({ listAttachments: () => throwError(() => new Error('x')) }));
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByText(/Datei/)).toBeNull();
  });

  it('opens the comments, names own ones "Du" and posts a public comment', async () => {
    const addComment = jest.fn(() => of(COMMENTS[0]));
    const { comp, fixture } = await setup(fakeApi({ addComment }));
    await userEvent.click(await screen.findByRole('button', { name: /Kommentare/ }));
    fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: 'Kommentare' });
    expect(within(dialog).getByText('Bitte ergänzen.')).toBeInTheDocument();
    expect(within(dialog).getByText('Du')).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Öffentlicher Kommentar' }), 'Frage');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Kommentar senden' }));
    expect(addComment).toHaveBeenCalledWith(ID, 'Frage');
    expect(comp.commentBody.value).toBe('');
    // Enter sends as well; Shift+Enter makes a line break.
    const box = within(dialog).getByRole('textbox', { name: 'Öffentlicher Kommentar' });
    await userEvent.type(box, 'Zeile 1{Shift>}{Enter}{/Shift}Zeile 2');
    expect(addComment).toHaveBeenCalledTimes(1);
    expect(comp.commentBody.value).toBe('Zeile 1\nZeile 2');
    await userEvent.type(box, '{Enter}');
    expect(addComment).toHaveBeenLastCalledWith(ID, 'Zeile 1\nZeile 2');
  });

  it('names an author by kind without a name, and shows an empty comment list', async () => {
    const { comp, fixture } = await setup(fakeApi({ comments: () => of([]) }));
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByText('0 Kommentare')).toBeInTheDocument();
    comp.commentsOpen.set(true);
    fixture.detectChanges();
    expect(await screen.findByText('Noch keine öffentlichen Kommentare.')).toBeInTheDocument();
    expect(comp.authorName({ ...COMMENTS[0], author: null })).toBe('Gremium');
    expect(comp.authorName({ ...COMMENTS[0], author: null, authorKind: 'applicant' })).toBe('Antragsteller:in');
    comp.comments.set([COMMENTS[0]]);
    expect(comp.commentsSub()).toBe('1 Kommentar');
  });

  it('toasts a failed comment and ignores an empty one', async () => {
    const addComment = jest.fn(() => throwError(() => new Error('x')));
    const { comp, toast } = await setup(fakeApi({ addComment }));
    await screen.findByRole('heading', { level: 1 });
    comp.commentBody.setValue('   ');
    comp.addComment();
    expect(addComment).not.toHaveBeenCalled();
    comp.commentBody.setValue('Hallo');
    comp.addComment();
    expect(toast.error).toHaveBeenCalledWith('Kommentar konnte nicht gespeichert werden.');
    comp.postingComment.set(true);
    comp.addComment();
    expect(addComment).toHaveBeenCalledTimes(1);
  });

  it('fires an applicant transition and reloads', async () => {
    const actions: Transition[] = [
      { id: 'tr1', label: 'Zurückziehen', color: '#c0392b', toStateId: 's9' } as Transition,
      { id: 'tr2', label: '', color: null, toStateId: 's8' } as Transition,
    ];
    const fire = jest.fn(() => of({ newStateId: 's9', statusEventId: 'e1', dispatchedActions: [] }));
    const getApplication = jest.fn(() => of(app(true)));
    const { comp } = await setup(
      fakeApi({ applicantTransitions: () => of(actions), fireApplicant: fire, getApplication }),
    );
    expect(await screen.findByRole('button', { name: 'Zurückziehen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aktion ausführen' })).toBeInTheDocument();
    expect(comp.looks().get('tr1')).toBe('danger');
    await userEvent.click(screen.getByRole('button', { name: 'Zurückziehen' }));
    expect(fire).toHaveBeenCalledWith(ID, { transitionId: 'tr1' });
    expect(getApplication).toHaveBeenCalledTimes(2);
  });

  it('offers no action when the server refuses the applicant transitions (403)', async () => {
    // A staff member who is not the creator gets 403 from the list route.
    const fire = jest.fn();
    const { comp } = await setup(
      fakeApi({
        applicantTransitions: () => throwError(() => ({ status: 403 })),
        fireApplicant: fire,
      }),
    );
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(comp.actions()).toEqual([]);
    expect(screen.queryByRole('button', { name: 'Aktion ausführen' })).not.toBeInTheDocument();
    expect(fire).not.toHaveBeenCalled();
  });

  it('toasts a failed transition and ignores a second fire', async () => {
    const fire = jest.fn(() => throwError(() => new Error('x')));
    const t = { id: 'tr1', label: 'Los', color: null, toStateId: 's9' } as Transition;
    const { comp, toast } = await setup(fakeApi({ applicantTransitions: () => of([t]), fireApplicant: fire }));
    await screen.findByRole('heading', { level: 1 });
    comp.fireAction(t);
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    comp.firing.set('other');
    comp.fireAction(t);
    expect(fire).toHaveBeenCalledTimes(1);
  });

  it('requests the anonymization from the menu after a confirmation', async () => {
    const requestErasure = jest.fn(() => of(undefined));
    const { comp, toast, fixture } = await setup(fakeApi({ requestErasure }));
    await screen.findByRole('heading', { level: 1 });
    comp.onMenu({ id: 'other', label: 'x' });
    expect(comp.confirmErase()).toBe(false);
    comp.onMenu(comp.menu()[0].items[0]);
    fixture.detectChanges();
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Anonymisierung beantragen' }));
    expect(requestErasure).toHaveBeenCalledWith(ID);
    expect(toast.success).toHaveBeenCalled();
    expect(comp.confirmErase()).toBe(false);
  });

  it('toasts a failed anonymization request and ignores a second one', async () => {
    const requestErasure = jest.fn(() => throwError(() => new Error('x')));
    const { comp, toast } = await setup(fakeApi({ requestErasure }));
    await screen.findByRole('heading', { level: 1 });
    comp.doRequestErasure();
    expect(toast.error).toHaveBeenCalled();
    comp.requestingErasure.set(true);
    comp.doRequestErasure();
    expect(requestErasure).toHaveBeenCalledTimes(1);
  });

  it('hides the link line when links have a lifetime', async () => {
    await setup(fakeApi(), { app: ID }, { linkTtlDays: 30 });
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByText(/unbegrenzt/)).toBeNull();
  });

  it('hides the link line until the config loaded', async () => {
    await setup(fakeApi(), { app: ID }, { loaded: false });
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByText(/unbegrenzt/)).toBeNull();
  });

  it('counts several files and names the changed keys without a form', async () => {
    const two = [0, 1].map((i) => ({
      id: `f${i}`,
      filename: `f${i}.pdf`,
      mime: 'application/pdf',
      size: 1,
      scanned: true,
      isComparisonOffer: false,
      scanState: 'clean' as const,
    }));
    const { comp } = await setup(
      fakeApi({
        listAttachments: () => of(two),
        effectiveForm: () => throwError(() => new Error('x')),
        versions: () =>
          of([
            { ...VERSIONS[1], changedKeys: ['participants'] },
            { ...VERSIONS[2], changedKeys: undefined },
          ]),
        application: { ...app(true), hiddenKeys: undefined } as unknown as Application,
      }),
    );
    expect(await screen.findByText('2 Dateien')).toBeInTheDocument();
    expect(comp.historyEntries().map((e) => e.body)).toContain('Geändert: participants');
    // Without the form there is nothing to edit.
    comp.startEdit();
    expect(comp.editing()).toBe(false);
    comp.effForm.set(EFF);
    comp.startEdit();
    expect(comp.editing()).toBe(true);
  });

  it('becomes ready without the optional parts', async () => {
    await setup(
      fakeApi({
        applicantTransitions: () => throwError(() => new Error('x')),
        versions: () => throwError(() => new Error('x')),
        effectiveForm: () => throwError(() => new Error('x')),
      }),
    );
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Angaben bearbeiten/ })).toBeDisabled();
  });

  it('shows the end states: expired link, error, no link', async () => {
    await setup(fakeApi({ verify: () => throwError(() => ({ status: 410 })) }), { t: 'tok' });
    expect(await screen.findByRole('heading', { name: 'Link abgelaufen' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zur Startseite' })).toHaveAttribute('href', '/');
  });

  it('shows the error state on another verify failure', async () => {
    await setup(fakeApi({ verify: () => throwError(() => ({ status: 500 })) }), { t: 'tok' });
    expect(await screen.findByRole('heading', { name: 'Antrag nicht gefunden' })).toBeInTheDocument();
  });

  it('shows the error state without a token and an id', async () => {
    await setup(fakeApi(), {});
    expect(await screen.findByRole('heading', { name: 'Antrag nicht gefunden' })).toBeInTheDocument();
  });

  it('shows the expired state when the load fails with 410, else the error state', async () => {
    await setup(fakeApi({ getApplication: () => throwError(() => ({ status: 410 })) }));
    expect(await screen.findByRole('heading', { name: 'Link abgelaufen' })).toBeInTheDocument();
  });

  it('shows the error state when the load fails otherwise', async () => {
    await setup(fakeApi({ getApplication: () => throwError(() => ({ status: 500 })) }));
    expect(await screen.findByRole('heading', { name: 'Antrag nicht gefunden' })).toBeInTheDocument();
  });

  it('errors when verify gives no id and none can be derived', async () => {
    const verify = jest.fn(() => of({ application_id: null, scope: 'edit' as const }));
    const { comp } = await setup(fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }), { t: 'tok' });
    expect(await screen.findByRole('heading', { name: 'Antrag nicht gefunden' })).toBeInTheDocument();
    expect(comp.phase()).toBe('error');
  });

  it('locks the edit for an old view link', async () => {
    const verify = jest.fn(() => of({ application_id: ID, scope: 'view' as const }));
    const { comp } = await setup(fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }), { t: 'tok', app: ID });
    await screen.findByRole('heading', { level: 1 });
    expect(comp.canEdit()).toBe(false);
    expect(comp.canUploadAttachments()).toBe(false);
    // The reason is the link, not the status.
    expect(screen.getByText('Mit diesem Link nicht möglich')).toBeInTheDocument();
    expect(screen.queryByText('Im aktuellen Status gesperrt')).toBeNull();
  });

  it('localizes the page in English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup(fakeApi());
    expect(await screen.findByText('Case 3F9A2C71')).toBeInTheDocument();
    expect(screen.getByText('Edit details')).toBeInTheDocument();
    expect(screen.getByText('History')).toBeInTheDocument();
  });

  it('strips a query token from the URL and keeps the id for a reload', async () => {
    history.replaceState(null, '', '/status?t=secret-token');
    await setup(fakeApi(), { t: 'secret-token' });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.href).not.toContain('secret-token');
    expect(window.location.search).toContain(`app=${ID}`);
  });

  it('strips a fragment token and keeps the other fragment params', async () => {
    history.replaceState(null, '', `/antrag/${ID}#t=frag-token&foo=bar`);
    await setup(fakeApi(), {}, { pathParams: { id: ID }, fragment: 't=frag-token&foo=bar' });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.hash).not.toContain('frag-token');
    expect(window.location.hash).toContain('foo=bar');
    expect(window.location.search).not.toContain('app=');
  });

  it('strips only the token of a fragment that holds nothing else', async () => {
    history.replaceState(null, '', `/antrag/${ID}#t=frag-token`);
    await setup(fakeApi(), {}, { pathParams: { id: ID }, fragment: 't=frag-token' });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.hash).toBe('');
  });

  it('leaves a URL without a token alone', async () => {
    history.replaceState(null, '', `/antrag/${ID}`);
    await setup(fakeApi(), { t: 'tok' }, { pathParams: { id: ID } });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.pathname).toBe(`/antrag/${ID}`);
  });

  it('loads with the cookie session when only an id is there', async () => {
    const verify = jest.fn();
    await setup(fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }), {}, { pathParams: { id: ID } });
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(verify).not.toHaveBeenCalled();
  });

  it('falls back to a title when the answers have none', async () => {
    const { comp } = await setup(fakeApi({ application: app(true, {}) }));
    await waitFor(() => expect(comp.phase()).toBe('ready'));
    expect(comp.title()).toBe('Ohne Titel');
  });
});
