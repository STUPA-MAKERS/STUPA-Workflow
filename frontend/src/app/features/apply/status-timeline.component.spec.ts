import { signal } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { NEVER, of, throwError, type Observable } from 'rxjs';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/angular';
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
import { MY_APPLICATIONS_PAGE } from './my-applications-page';
import { StatusTimelineComponent } from './status-timeline.component';

const ID = '3f9a2c71-1111-2222-3333-444444444444';

function app(editAllowed: boolean, data: Record<string, unknown> = { title: 'Sommerfest' }): Application {
  return {
    id: ID,
    typeId: 't1',
    state: { id: 's1', key: 'agenda', label: 'Auf Tagesordnung', color: '#72a384', editAllowed, kind: 'normal' },
    gremiumId: null,
    budgetId: null,
    fiscalYearId: null,
    amount: null,
    currency: null,
    data,
    version: 2,
    lang: 'de',
    createdAt: '2026-09-26T10:00:00Z',
    updatedAt: '2026-09-27T10:00:00Z',
    stateSince: '2026-09-28T14:20:00Z',
    applicant: null,
    canEdit: editAllowed,
    canEditLocked: false,
    isOwner: true,
    archivedAt: null,
    hiddenKeys: [],
  };
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
  {
    toStateId: 's0',
    toState: null,
    label: 'Eingereicht',
    actor: 'applicant',
    at: '2026-09-26T12:12:00Z',
    note: null,
    voteId: null,
    voteDeleted: false,
  },
  {
    toStateId: 's1',
    toState: { id: 's1', key: 'agenda', label: 'Auf Tagesordnung', color: '#72a384', editAllowed: false, kind: 'normal' },
    label: 'Auf Tagesordnung',
    transitionLabel: 'Auf Tagesordnung setzen',
    actor: 'Studierendenparlament',
    at: '2026-09-28T14:20:00Z',
    note: 'vote:tie',
    voteId: null,
    voteDeleted: false,
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
    attachments: [],
    mentions: [],
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
    attachments: [],
    mentions: [],
  },
];

interface ApiOverrides {
  verify?: Partial<ApiClient>['verifyMagicLink'];
  application?: Application;
  getApplication?: Partial<ApiClient>['getApplication'];
  update?: jest.Mock;
  addComment?: jest.Mock;
  updateComment?: jest.Mock;
  deleteComment?: jest.Mock;
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
          { id: 'f1', filename: 'Angebot.pdf', mime: 'application/pdf', size: 1000, scanned: true, scanState: 'clean' as const },
        ])),
    applicantTransitions: (o.applicantTransitions ?? (() => of([]))) as ApiClient['applicantTransitions'],
    fireApplicantTransition: (o.fireApplicant ??
      jest.fn(() => of({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] }))) as unknown as ApiClient['fireApplicantTransition'],
    effectiveForm: (o.effectiveForm ?? (() => of(EFF))) as ApiClient['effectiveForm'],
    updateApplication: (o.update ?? jest.fn(() => of({ ...app(true), version: 3 }))) as unknown as ApiClient['updateApplication'],
    addComment: (o.addComment ?? jest.fn(() => of(COMMENTS[0]))) as unknown as ApiClient['addComment'],
    updateComment: (o.updateComment ?? jest.fn()) as unknown as ApiClient['updateComment'],
    deleteComment: (o.deleteComment ?? jest.fn()) as unknown as ApiClient['deleteComment'],
    requestErasure: (o.requestErasure ?? jest.fn(() => of(undefined))) as unknown as ApiClient['requestErasure'],
    attachmentUrl: jest.fn(),
    applicationTypes: (() => of([{ id: 't1', name: 'Finanzantrag' }])) as unknown as ApiClient['applicationTypes'],
  };
}

interface RouteOpts {
  pathParams?: Record<string, string>;
  fragment?: string | null;
  linkTtlDays?: number | null;
  /** The public config loaded (default true). */
  loaded?: boolean;
  /** More providers, for example the list of `/my-applications`. */
  providers?: unknown[];
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
      ...((opts.providers ?? []) as never[]),
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

  it('verifies the token and shows title, status, type and the comments', async () => {
    const verify = jest.fn(() => of({ application_id: ID, scope: 'edit' as const }));
    await setup(fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }), { t: 'tok', app: ID });
    expect(await screen.findByRole('heading', { level: 1, name: 'Sommerfest' })).toBeInTheDocument();
    expect(verify).toHaveBeenCalledWith('tok');
    expect(screen.queryByText(ID)).toBeNull();
    expect(screen.getAllByText('Auf Tagesordnung')[0].tagName).toBe('APP-STATUS-TEXT');
    expect(screen.getByText('Finanzantrag')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Kommentare, 2' })).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole('tab', { name: 'Verlauf' }));
    expect(await screen.findByText('Version 2 gespeichert')).toBeInTheDocument();
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

  it('Notes the deviations of a decision, and nothing for a decision as requested', async () => {
    const { comp } = await setup(fakeApi({ timeline: () => of([]), versions: () => of([]) }));
    await screen.findByRole('heading', { level: 1 });
    const base = { toStateId: 's9', toState: null, label: 'Bewilligt', actor: null, at: '2026-06-05T10:00:00Z', note: null, voteId: null, voteDeleted: false };
    comp.timeline.set([
      { ...base, decision: { requestedAmount: '820.00', approvedAmount: '700.00', amountDeviates: true, conditionCount: 2 } },
      { ...base, decision: { requestedAmount: '820.00', approvedAmount: null, amountDeviates: false, conditionCount: 0 } },
    ]);
    const [deviates, plain] = comp.historyEntries();
    expect(deviates.body).toMatch(/^Mit Abweichungen: 700,00\s€ statt 820,00\s€.*2 Auflagen/);
    expect(plain.body).toBeNull();
  });

  it('translates vote notes and keeps other notes', async () => {
    const { comp } = await setup(fakeApi());
    expect(comp.noteText('vote:passed')).toBe('Abstimmungsergebnis: Angenommen');
    expect(comp.noteText('vote:rejected')).toBe('Abstimmungsergebnis: Abgelehnt');
    expect(comp.noteText('Bitte nachreichen')).toBe('Bitte nachreichen');
    expect(comp.noteText('vote:repeat')).toBe('Erneute Abstimmung');
  });

  it('offers no edit in a locked status and says why', async () => {
    await setup(fakeApi({ application: app(false) }));
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByRole('button', { name: 'Angaben bearbeiten' })).toBeNull();
    expect(screen.getByText('Im aktuellen Status gesperrt')).toBeInTheDocument();
  });

  /**
   * The focus moves to the title of the edit bar and, after the save, back to the row. File fields
   * stay out of the edit form.
   */
  it('edits the answers and saves a new version', async () => {
    const update = jest.fn(() => of({ ...app(true, { title: 'Neu' }), version: 3 }));
    const { comp, toast, fixture } = await setup(fakeApi({ update }));
    await userEvent.click(await screen.findByRole('button', { name: /Angaben bearbeiten/ }));
    await waitFor(() => expect(document.activeElement?.id).toBe('sp-edit-title'));
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

  /**
   * The row may go off, so the focus goes to the title of the page. The field error blocks the next
   * save; a new edit starts clean.
   */
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
    await waitFor(() => expect(document.activeElement?.id).toBe('sp-title'));
    expect(getApplication).toHaveBeenCalledTimes(2);
    comp.startEdit();
    fixture.detectChanges();
    comp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Bitte prüfe die markierten Felder.');
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

  it('shows the attachments in their tab', async () => {
    const { comp } = await setup(fakeApi());
    await screen.findByRole('heading', { level: 1 });
    await userEvent.click(screen.getByRole('tab', { name: 'Anhänge' }));
    expect(comp.tab()).toBe('files');
    expect(await screen.findByText('Angebot.pdf')).toBeInTheDocument();
  });

  /** The open sheet takes its own drop. */
  it('opens the attachments tab with a file dropped anywhere on the page and uploads it', async () => {
    const uploadAttachment = jest.fn(() =>
      of({ id: 'f2', filename: 'Beleg.pdf', mime: 'application/pdf', size: 10, scanned: false, scanState: 'scanning' as const }),
    );
    const { comp, fixture, container } = await setup({
      ...fakeApi(),
      uploadAttachment: uploadAttachment as unknown as ApiClient['uploadAttachment'],
    });
    await screen.findByRole('heading', { level: 1 });
    const page = container.querySelector('article.ad') as HTMLElement;
    fireEvent.dragEnter(page, { dataTransfer: { types: ['Files'] } });
    fixture.detectChanges();
    expect(container.querySelector('app-drop-overlay')).toHaveTextContent('Dateien zum Hochladen ablegen');

    const pdf = new File(['x'], 'Beleg.pdf', { type: 'application/pdf' });
    fireEvent.drop(page, { dataTransfer: { types: ['Files'], files: [pdf] } });
    expect(comp.tab()).toBe('files');
    fixture.detectChanges();
    expect(await screen.findByText('Beleg.pdf')).toBeInTheDocument();
    expect(uploadAttachment).toHaveBeenCalledWith(ID, pdf);
    expect(container.querySelector('app-drop-overlay')).toBeNull();
  });


  /** The Gremium is named; an own comment stands right without a name. */
  it('opens the comments in the chat and posts a public comment at once', async () => {
    const created = { ...COMMENTS[1], id: 'c3', body: 'Frage' };
    const addComment = jest.fn(() => of(created));
    const { fixture } = await setup(fakeApi({ addComment }));
    await userEvent.click(await screen.findByRole('button', { name: /Kommentare/ }));
    fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: 'Kommentare' });
    expect(within(dialog).getByRole('log')).toBeInTheDocument();
    expect(within(dialog).getByText('Bitte ergänzen.')).toBeInTheDocument();
    expect(within(dialog).getByText('Studierendenparlament')).toBeInTheDocument();
    expect(within(dialog).queryByText('Du')).not.toBeInTheDocument();
    const box = within(dialog).getByRole('textbox', { name: 'Nachricht an das Gremium …' });
    fireEvent.input(box, { target: { value: 'Frage' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    fixture.detectChanges();
    expect(addComment).toHaveBeenCalledWith(ID, 'Frage', 'public', { body: 'Frage' });
    expect(within(dialog).getByText('Frage')).toBeInTheDocument();
  });

  it('names an author by kind without a name, and shows an empty comment list', async () => {
    const { comp, fixture } = await setup(fakeApi({ comments: () => of([]) }));
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByRole('button', { name: 'Kommentare, 0' })).toBeInTheDocument();
    comp.commentsOpen.set(true);
    fixture.detectChanges();
    expect(await screen.findByText('Noch keine Nachrichten.')).toBeInTheDocument();
    expect(comp.authorName({ ...COMMENTS[0], author: null })).toBe('Gremium');
    expect(comp.authorName({ ...COMMENTS[0], author: null, authorKind: 'applicant' })).toBe('Antragsteller:in');
    expect(comp.authorName(COMMENTS[1])).toBe('Du');
  });

  /**
   * Only the scan state comes from the read; the text on screen stays. An answer for another
   * application is dropped.
   */
  it('reads the comments again when the chat asks, quietly, and keeps them on a failure', async () => {
    const file = { id: 'f1', filename: 'a.pdf', mime: 'application/pdf', size: 1 };
    let answer: Observable<ApplicationComment[]> = of([
      { ...COMMENTS[0], body: 'Neu', attachments: [{ ...file, scanState: 'scanning' }] },
    ]);
    const comments = jest.fn((): Observable<ApplicationComment[]> => answer);
    const { comp, fixture } = await setup(fakeApi({ comments: comments as ApiClient['comments'] }));
    await screen.findByRole('heading', { level: 1 });
    comp.commentsOpen.set(true);
    fixture.detectChanges();
    await screen.findByRole('log');
    answer = of([{ ...COMMENTS[0], body: 'Alt', attachments: [{ ...file, scanState: 'clean' }] }]);
    fixture.debugElement.query((d) => d.name === 'app-chat').triggerEventHandler('refresh');
    expect(comments).toHaveBeenLastCalledWith(ID, { quiet: true });
    expect(comp.comments().map((c) => c.body)).toEqual(['Neu']);
    expect(comp.comments()[0].attachments?.[0].scanState).toBe('clean');
    answer = throwError(() => new Error('x'));
    (comp as unknown as { refreshComments(id: string): void }).refreshComments(ID);
    expect(comp.comments().map((c) => c.body)).toEqual(['Neu']);
    answer = of([]);
    (comp as unknown as { refreshComments(id: string): void }).refreshComments('other');
    expect(comp.comments()).toHaveLength(1);
  });

  it('offers no paperclip on an anonymized application', async () => {
    const { comp, fixture } = await setup(fakeApi());
    await screen.findByRole('heading', { level: 1 });
    comp.commentsOpen.set(true);
    fixture.detectChanges();
    await screen.findByRole('log');
    expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeInTheDocument();
    comp.application.update((a) => a && { ...a, applicant: { email: null, name: null, anonymized: true } });
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();
  });

  it('keeps a failed comment and sends it again', async () => {
    let fail = true;
    const addComment = jest.fn(() => (fail ? throwError(() => new Error('x')) : of({ ...COMMENTS[1], id: 'c4', body: 'Hallo' })));
    const { comp, toast } = await setup(fakeApi({ addComment }));
    await screen.findByRole('heading', { level: 1 });
    comp.sendComment({ body: 'Hallo', visibility: 'internal' });
    expect(comp.chatMessages().at(-1)).toMatchObject({ body: 'Hallo', state: 'failed', visibility: null });
    expect(toast.error).toHaveBeenCalledWith('Kommentar konnte nicht gespeichert werden.');
    fail = false;
    comp.retryComment({ id: comp.chatMessages().at(-1)!.id });
    expect(addComment).toHaveBeenCalledTimes(2);
    expect(comp.comments().at(-1)?.id).toBe('c4');
    expect(comp.chatMessages().some((m) => m.state === 'failed')).toBe(false);
  });

  it('sends the files of a public comment and shows the files of the comments', async () => {
    const addComment = jest.fn(() => throwError(() => new Error('x')));
    const deleteDraftAttachment = jest.fn(() => of(undefined));
    const api = {
      ...fakeApi({
        addComment,
        comments: () =>
          of([{ ...COMMENTS[0], attachments: [{ id: 'f9', filename: 'a.pdf', mime: 'application/pdf', size: 1, scanState: 'clean' as const }] }]),
      }),
      deleteDraftAttachment: deleteDraftAttachment as unknown as ApiClient['deleteDraftAttachment'],
    };
    const { comp } = await setup(api);
    await screen.findByRole('heading', { level: 1 });
    expect(comp.chatMessages()[0].attachments).toEqual([
      { id: 'f9', filename: 'a.pdf', mime: 'application/pdf', size: 1, scanState: 'clean', url: '/api/attachments/f9/download' },
    ]);
    comp.sendComment({ body: '', visibility: 'internal', attachmentIds: ['d1'], draftToken: 'tok' });
    expect(addComment).toHaveBeenCalledWith(ID, '', 'public', { body: '', attachmentIds: ['d1'], draftToken: 'tok' });
    comp.discardComment({ id: comp.chatMessages().at(-1)!.id });
    expect(deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
  });

  it('names a refused send and discards the failed comment', async () => {
    const addComment = jest.fn(() => throwError(() => ({ status: 403 })));
    const { comp, toast } = await setup(fakeApi({ addComment }));
    await screen.findByRole('heading', { level: 1 });
    comp.sendComment({ body: 'Hallo' });
    expect(toast.error).toHaveBeenCalledWith('Du darfst hier nicht schreiben.');
    comp.discardComment({ id: comp.chatMessages().at(-1)!.id });
    expect(comp.chatMessages().some((m) => m.state === 'failed')).toBe(false);
  });

  it('edits and deletes an own comment', async () => {
    const updateComment = jest.fn(() => of({ ...COMMENTS[1], body: 'Neu' }));
    const deleteComment = jest.fn(() => of(undefined));
    const { comp } = await setup(fakeApi({ updateComment, deleteComment }));
    await screen.findByRole('heading', { level: 1 });
    comp.editComment({ id: 'c2', body: 'Neu' });
    expect(updateComment).toHaveBeenCalledWith(ID, 'c2', 'Neu');
    expect(comp.comments()[1].body).toBe('Neu');
    comp.deleteComment({ id: 'c2' });
    expect(deleteComment).toHaveBeenCalledWith(ID, 'c2');
    expect(comp.comments().map((c) => c.id)).toEqual(['c1']);
  });

  it.each([
    [403, 'Nur die verfassende Person oder eine Antragsverwaltung darf diesen Kommentar ändern.'],
    [404, 'Dieser Kommentar existiert nicht mehr.'],
    [500, 'Kommentar konnte nicht gespeichert werden.'],
  ])('explains a %s on a comment change', async (status, message) => {
    const fail = jest.fn(() => throwError(() => ({ status })));
    const { comp, toast } = await setup(fakeApi({ updateComment: fail, deleteComment: fail }));
    await screen.findByRole('heading', { level: 1 });
    const restore = jest.fn();
    comp.editComment({ id: 'c2', body: 'Neu', restore });
    comp.deleteComment({ id: 'c2' });
    expect(restore).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenNthCalledWith(1, message);
    expect(toast.error).toHaveBeenNthCalledWith(2, message);
    expect(comp.comments()).toHaveLength(2);
  });

  /** The chat exists only with an application; a send without one names no id. */
  it('changes no comment before the application loaded', async () => {
    const updateComment = jest.fn();
    const { comp } = await setup(fakeApi({ updateComment, deleteComment: updateComment }));
    await screen.findByRole('heading', { level: 1 });
    comp.application.set(null);
    comp.editComment({ id: 'c2', body: 'Neu' });
    comp.deleteComment({ id: 'c2' });
    expect(updateComment).not.toHaveBeenCalled();
    comp.sendComment({ body: 'x' });
    expect(comp.chatMessages().length).toBeGreaterThan(0);
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

  /** A staff member who is not the creator gets 403 from the list route. */
  it('offers no action when the server refuses the applicant transitions (403)', async () => {
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

  it('shows an observer the Antrag read-only, with the name of the applicant', async () => {
    const observed: Application = { ...app(true), canEdit: false, isOwner: false, observer: true, submittedBy: 'Luis Meyer' };
    const fire = { id: 't9', label: 'Zurückziehen' } as never;
    const { comp, fixture } = await setup(
      fakeApi({ application: observed, applicantTransitions: () => of([fire]) }),
    );
    await screen.findByRole('heading', { level: 1 });
    fixture.detectChanges();
    expect(screen.getByText('Eingereicht von Luis Meyer')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).not.toBeInTheDocument();
    expect(comp.menu()).toEqual([]);
    expect(comp.actions()).toEqual([]);
    expect(comp.canEdit()).toBe(false);
    expect(comp.canUploadAttachments()).toBe(false);
    expect(comp.lockReason()).toBeNull();
    expect(comp.historyEntries()[0].actor).toBe('Luis Meyer');
    expect(comp.authorName({ ...COMMENTS[1], isOwn: false })).toBe('Luis Meyer');
  });

  it('opens the observers dialog from the menu of the applicant', async () => {
    const applicationObservers = jest.fn(() => of([]));
    const { comp, fixture } = await setup({ ...fakeApi(), applicationObservers } as Partial<ApiClient>);
    await screen.findByRole('heading', { level: 1 });
    const item = comp.menu()[0].items[0];
    expect(item.id).toBe('observers');
    comp.onMenu(item);
    fixture.detectChanges();
    expect(comp.observersOpen()).toBe(true);
    expect(await screen.findByRole('dialog', { name: 'Beobachter:innen' })).toBeInTheDocument();
    expect(applicationObservers).toHaveBeenCalledWith(ID);
  });

  it('requests the anonymization from the menu after a confirmation', async () => {
    const requestErasure = jest.fn(() => of(undefined));
    const { comp, toast, fixture } = await setup(fakeApi({ requestErasure }));
    await screen.findByRole('heading', { level: 1 });
    comp.onMenu({ id: 'other', label: 'x' });
    expect(comp.confirmErase()).toBe(false);
    const erase = comp.menu().flatMap((sec) => sec.items).find((i) => i.id === 'erase');
    comp.onMenu(erase!);
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



  /** Without the form there is nothing to edit. */
  it('names the changed keys without a form', async () => {
    const two = [0, 1].map((i) => ({
      id: `f${i}`,
      filename: `f${i}.pdf`,
      mime: 'application/pdf',
      size: 1,
      scanned: true,
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
    await screen.findByRole('heading', { level: 1 });
    expect(comp.historyEntries().map((e) => e.body)).toContain('Geändert: participants');
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
    expect(screen.queryByRole('button', { name: /Angaben bearbeiten/ })).toBeNull();
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

  /** The reason is the link, not the status. */
  it('locks the edit for an old view link', async () => {
    const verify = jest.fn(() => of({ application_id: ID, scope: 'view' as const }));
    const { comp } = await setup(fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }), { t: 'tok', app: ID });
    await screen.findByRole('heading', { level: 1 });
    expect(comp.canEdit()).toBe(false);
    expect(comp.canUploadAttachments()).toBe(false);
    expect(screen.getByText('Mit diesem Link nicht möglich')).toBeInTheDocument();
    expect(screen.queryByText('Im aktuellen Status gesperrt')).toBeNull();
  });

  /** F/applications/applications/000588: inside `/my-applications` an old link reloads the list. */
  it('reloads the list after an old link inside Meine Anträge and leaves the h1 to the list', async () => {
    const page = { split: signal(true), reload: jest.fn() };
    const { comp } = await setup(fakeApi(), { t: 'tok' }, { pathParams: { id: ID }, providers: [{ provide: MY_APPLICATIONS_PAGE, useValue: page }] });
    expect(await screen.findByRole('heading', { level: 2, name: 'Sommerfest' })).toBeInTheDocument();
    expect(page.reload).toHaveBeenCalled();
    const tab = comp.tab();
    comp.onFilesDropped([]);
    expect(comp.tab()).toBe(tab);
  });

  /** F/applications/applications/000588: an invalid link inside `/my-applications` opens `/login`. */
  it('sends an invalid link inside Meine Anträge to the login page', async () => {
    const page = { split: signal(false), reload: jest.fn() };
    const verify = jest.fn(() => throwError(() => ({ status: 410 })));
    const navigate = jest.spyOn(Router.prototype, 'navigate').mockResolvedValue(true);
    await setup(
      fakeApi({ verify: verify as unknown as ApiClient['verifyMagicLink'] }),
      { t: 'tok' },
      { pathParams: { id: ID }, providers: [{ provide: MY_APPLICATIONS_PAGE, useValue: page }] },
    );
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { link: 'invalid' }, replaceUrl: true }));
    expect(page.reload).not.toHaveBeenCalled();
    navigate.mockRestore();
  });

  it('shows the amount and a deviating approved amount, and nothing without an amount', async () => {
    const { comp } = await setup(fakeApi());
    await screen.findByRole('heading', { level: 1 });
    const base = { ...app(true), amount: '1250.00', currency: 'EUR' } as Application;
    expect(comp.amount({ ...base, amount: null })).toBe('');
    expect(comp.amount(base)).toMatch(/1\.250,00/);
    expect(comp.approvedAmount({ ...base, approvedAmount: null } as Application)).toBe('');
    expect(comp.approvedAmount({ ...base, approvedAmount: '1250' } as Application)).toBe('');
    expect(comp.approvedAmount({ ...base, approvedAmount: '1000.00' } as Application)).toMatch(/1\.000,00/);
    expect(comp.amount({ ...base, amount: 'k. A.' })).toBe('k. A.');
  });

  it('names no type before the Antrag has loaded', async () => {
    const { comp } = await setup({ ...fakeApi(), getApplication: () => NEVER });
    expect(comp.typeName()).toBeNull();
  });

  it('names no type when the types cannot load, and keeps a tab choice to the known tabs', async () => {
    const { comp } = await setup({ ...fakeApi(), applicationTypes: (() => throwError(() => new Error('x'))) as unknown as ApiClient['applicationTypes'] });
    await screen.findByRole('heading', { level: 1 });
    expect(comp.typeName()).toBeNull();
    comp.selectTab('nope');
    expect(comp.tab()).toBe('app');
    comp.selectTab('history');
    expect(comp.tab()).toBe('history');
  });

  /** F/applications/applications/000588: a lost session inside `/my-applications` opens `/login`. */
  it('sends a lost session inside Meine Anträge to the login page', async () => {
    const page = { split: signal(false), reload: jest.fn() };
    const navigate = jest.spyOn(Router.prototype, 'navigate').mockResolvedValue(true);
    await setup(
      fakeApi({ getApplication: () => throwError(() => ({ status: 401 })) }),
      {},
      { pathParams: { id: ID }, providers: [{ provide: MY_APPLICATIONS_PAGE, useValue: page }] },
    );
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(['/login'], { replaceUrl: true }));
    navigate.mockRestore();
  });

  it('localizes the page in English', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup(fakeApi());
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByRole('button', { name: 'Edit details' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'History' })).toBeInTheDocument();
  });

  it('strips a query token from the URL and keeps the id for a reload', async () => {
    history.replaceState(null, '', '/status?t=secret-token');
    await setup(fakeApi(), { t: 'secret-token' });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.href).not.toContain('secret-token');
    expect(window.location.search).toContain(`app=${ID}`);
  });

  it('strips a fragment token and keeps the other fragment params', async () => {
    history.replaceState(null, '', `/my-applications/${ID}#t=frag-token&foo=bar`);
    await setup(fakeApi(), {}, { pathParams: { id: ID }, fragment: 't=frag-token&foo=bar' });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.hash).not.toContain('frag-token');
    expect(window.location.hash).toContain('foo=bar');
    expect(window.location.search).not.toContain('app=');
  });

  it('strips only the token of a fragment that holds nothing else', async () => {
    history.replaceState(null, '', `/my-applications/${ID}#t=frag-token`);
    await setup(fakeApi(), {}, { pathParams: { id: ID }, fragment: 't=frag-token' });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.hash).toBe('');
  });

  it('leaves a URL without a token alone', async () => {
    history.replaceState(null, '', `/my-applications/${ID}`);
    await setup(fakeApi(), { t: 'tok' }, { pathParams: { id: ID } });
    await screen.findByRole('heading', { level: 1 });
    expect(window.location.pathname).toBe(`/my-applications/${ID}`);
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
