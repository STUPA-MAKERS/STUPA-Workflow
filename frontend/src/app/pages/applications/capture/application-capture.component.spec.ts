import { computed, signal } from '@angular/core';
import { Subject, of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import type {
  ApplicantCandidate,
  ApplicationType,
  EffectiveForm,
  OnBehalfApplication,
  ProblemDetail,
} from '@core/api/models';
import { BrandingService } from '@core/branding/branding.service';
import { provideFormly } from '@shared/formly/formly.providers';
import { ToastService } from '@stupa-makers/ui-kit';
import { DraftAttachmentsService, type DraftFile } from '../../../features/apply/draft-attachments.service';
import { FormlyDraftFilesType } from '../../../features/apply/draft-files/formly-draft-files.type';
import { runAxe } from '../../../../testing/a11y';
import {
  APPLICANT_SEARCH_DELAY_MS,
  ApplicationCaptureComponent,
  candidateLabel,
  localToday,
} from './application-capture.component';

const TYPES: ApplicationType[] = [
  { id: 't1', name: 'Förderantrag', active: true, hasBudget: true, activeFormVersionId: 'v1', key: null, gremiumId: null },
  { id: 't2', name: 'Alt', active: false, hasBudget: false, activeFormVersionId: 'v2', key: null, gremiumId: null },
];

const EFF: EffectiveForm = {
  applicationTypeId: 't1',
  formVersionId: 'v1',
  hasBudget: true,
  sections: [
    {
      key: 'main',
      label: { de: 'Antrag' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
        { key: 'receipt', type: 'file', label: { de: 'Beleg' } },
      ],
    },
  ],
};

const ANNA: ApplicantCandidate = { id: 'p1', displayName: 'Anna Antrag', email: 'anna@example.org' };

function fakeDrafts(files: DraftFile[] = []) {
  const list = signal<DraftFile[]>(files);
  const usable = computed(() => list().filter((f) => !f.failed));
  return {
    files: list,
    pending: signal([]),
    busy: signal(false),
    hasFailed: computed(() => list().some((f) => f.failed)),
    usable,
    limits: signal({ maxFileBytes: 10, maxDraftFiles: 20, maxDraftBytes: 50 }),
    count: computed(() => usable().length),
    bytes: computed(() => 0),
    filesOf: (k: string | null) => list().filter((f) => f.fieldKey === k),
    token: jest.fn(() => (list().length ? 'tok' : null)),
    attachmentIds: jest.fn(() => usable().map((f) => f.id)),
    markFailed: jest.fn(() => []),
    clear: jest.fn(),
    discard: jest.fn(async () => undefined),
    scopeToFields: jest.fn(async () => undefined),
    upload: jest.fn(),
    remove: jest.fn(),
  };
}

interface Opts {
  search?: jest.Mock;
  create?: jest.Mock;
  effectiveForm?: jest.Mock;
  drafts?: ReturnType<typeof fakeDrafts>;
  layout?: 'pane' | 'page' | 'sheet';
}

async function setup(opts: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  const search = opts.search ?? jest.fn(() => of([ANNA]));
  const create = opts.create ?? jest.fn(() => of({ applicationId: 'new-1' }));
  const effectiveForm = opts.effectiveForm ?? jest.fn(() => of(EFF));
  const drafts = opts.drafts ?? fakeDrafts();
  const toast = { error: jest.fn(), success: jest.fn(), show: jest.fn() };
  const api: Partial<ApiClient> = {
    searchOnBehalfApplicants: search as unknown as ApiClient['searchOnBehalfApplicants'],
    createApplicationOnBehalf: create as unknown as ApiClient['createApplicationOnBehalf'],
    effectiveForm: effectiveForm as unknown as ApiClient['effectiveForm'],
  };
  const created = jest.fn();
  const closed = jest.fn();
  const view = await render(ApplicationCaptureComponent, {
    providers: [
      provideFormly(),
      { provide: ApiClient, useValue: api },
      { provide: ToastService, useValue: toast },
      {
        provide: BrandingService,
        useValue: { attachmentLimits: signal({ maxFileBytes: 10, maxDraftFiles: 20, maxDraftBytes: 50 }) },
      },
    ],
    componentProviders: [{ provide: DraftAttachmentsService, useValue: drafts }],
    componentInputs: { types: TYPES, layout: opts.layout ?? 'pane' },
    on: { created, closed },
  });
  const comp = view.fixture.componentInstance;
  const flush = () => {
    view.fixture.detectChanges();
  };
  return { ...view, comp, search, create, effectiveForm, drafts, toast, created, closed, flush };
}

type Setup = Awaited<ReturnType<typeof setup>>;

/** Fill a complete capture for Anna: the account, the type and the title. */
async function fillAccount(s: Setup) {
  s.comp.pick(ANNA);
  s.comp.selectType('t1');
  s.flush();
  await s.fixture.whenStable();
  s.comp.model['title'] = 'Papierantrag';
  s.comp.form.get('title')?.setValue('Papierantrag');
  s.flush();
}

describe('ApplicationCaptureComponent', () => {
  afterEach(() => jest.useRealTimers());

  it('shows the head, the sections and offers only the active types', async () => {
    const s = await setup();
    expect(screen.getByRole('heading', { name: 'Antrag erfassen' })).toBeTruthy();
    expect(screen.getByText('Für eine andere Person · geht direkt in den Ablauf')).toBeTruthy();
    expect(screen.getByRole('option', { name: 'Förderantrag' })).toBeTruthy();
    expect(screen.queryByRole('option', { name: 'Alt' })).toBeNull();
    expect(screen.getByText('Wähle eine Antragsart, dann erscheinen die Felder.')).toBeTruthy();
    expect(s.comp.receivedOn()).toBe(localToday());
    expect((screen.getByTestId('cap-submit').querySelector('button') as HTMLButtonElement).disabled).toBe(true);
    expect(await runAxe(s.container)).toHaveNoViolations();
  });

  it('the sheet layout leaves out the head and uses the short submit label', async () => {
    await setup({ layout: 'sheet' });
    expect(screen.queryByRole('heading', { name: 'Antrag erfassen' })).toBeNull();
    expect(screen.getByText('Erfassen')).toBeTruthy();
  });

  it('searches accounts after a pause and picks one', async () => {
    jest.useFakeTimers();
    const s = await setup();
    s.comp.onSearch('a');
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    expect(s.search).not.toHaveBeenCalled();
    s.comp.onSearch('an');
    s.comp.onSearch('ann');
    expect(s.comp.searching()).toBe(true);
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    expect(s.search).toHaveBeenCalledTimes(1);
    expect(s.search).toHaveBeenCalledWith('ann');
    s.flush();
    expect(screen.getByRole('option', { name: /Anna Antrag/ })).toBeTruthy();
    expect(screen.getByText('anna@example.org')).toBeTruthy();
    screen.getByRole('option', { name: /Anna Antrag/ }).click();
    s.flush();
    expect(screen.getByTestId('cap-picked').textContent).toContain('Anna Antrag · anna@example.org');
    expect(screen.getByText('Für Anna Antrag · anna@example.org · geht direkt in den Ablauf')).toBeTruthy();
    s.comp.clearPick();
    s.flush();
    expect(s.comp.picked()).toBeNull();
    expect(s.comp.query()).toBe('');
  });

  it('drops a late answer and a failed search', async () => {
    jest.useFakeTimers();
    const first = new Subject<ApplicantCandidate[]>();
    const search = jest
      .fn()
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(throwError(() => new Error('down')))
      .mockReturnValueOnce(of([]));
    const s = await setup({ search });
    s.comp.onSearch('an');
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    s.comp.onSearch('ann');
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    // The failed second search clears the hits; the late first answer changes nothing.
    first.next([ANNA]);
    expect(s.comp.candidates()).toEqual([]);
    expect(s.comp.searching()).toBe(false);
    // A short text cancels the running search.
    s.comp.onSearch('x');
    expect(s.comp.searching()).toBe(false);
    s.comp.onSearch('zz');
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    s.flush();
    expect(screen.getByText('Kein Konto gefunden.')).toBeTruthy();
    // A failed search with a later stale answer: the error of an old search is ignored.
    const late = new Subject<ApplicantCandidate[]>();
    search.mockReturnValueOnce(late).mockReturnValueOnce(of([ANNA]));
    s.comp.onSearch('aa');
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    s.comp.onSearch('ann');
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    late.error(new Error('late'));
    expect(s.comp.candidates()).toEqual([ANNA]);
  });

  it('turns the search text into a new person', async () => {
    const s = await setup();
    s.comp.query.set('neu@example.org');
    s.comp.useAsGuest();
    expect(s.comp.mode()).toBe('guest');
    expect(s.comp.guestEmail()).toBe('neu@example.org');
    s.comp.setMode('account');
    s.comp.query.set('Gisela Gast');
    s.comp.useAsGuest();
    expect(s.comp.guestName()).toBe('Gisela Gast');
    s.flush();
    expect(screen.getByLabelText(/^Name/)).toBeTruthy();
    expect(screen.getByText(/persönlichen Link/)).toBeTruthy();
  });

  it('checks the e-mail of a new person', async () => {
    const s = await setup();
    s.comp.setMode('guest');
    s.comp.guestEmail.set('kaputt');
    s.flush();
    expect(screen.getByText('Bitte eine gültige E-Mail-Adresse eingeben.')).toBeTruthy();
    s.comp.guestEmail.set('');
    s.flush();
    expect(screen.queryByText('Bitte eine gültige E-Mail-Adresse eingeben.')).toBeNull();
  });

  it('loads the form of a type and turns a file field into draft files', async () => {
    const s = await setup();
    s.comp.selectType('');
    s.comp.selectType('t1');
    s.comp.selectType('t1');
    expect(s.effectiveForm).toHaveBeenCalledTimes(1);
    s.flush();
    expect(s.drafts.scopeToFields).toHaveBeenCalledWith(new Set(['receipt']));
    const group = s.comp.fields()[0].fieldGroup ?? [];
    expect(group.find((f) => f.key === 'receipt')?.type).toBe(FormlyDraftFilesType);
    expect(group.find((f) => f.key === 'title')?.type).not.toBe(FormlyDraftFilesType);
    expect(screen.getByText('Angaben')).toBeTruthy();
  });

  it('reports a form that fails to load', async () => {
    const s = await setup({ effectiveForm: jest.fn(() => throwError(() => new Error('x'))) });
    s.comp.selectType('t1');
    expect(s.comp.effForm()).toBeNull();
    expect(s.comp.loadingForm()).toBe(false);
    expect(s.toast.error).toHaveBeenCalled();
  });

  it('captures for an account and emits the new id', async () => {
    const s = await setup();
    await fillAccount(s);
    s.comp.intake.set('  per PDF ');
    expect(s.comp.canSubmit()).toBe(true);
    s.comp.submit(new Event('submit'));
    const body = s.create.mock.calls[0][0] as OnBehalfApplication;
    expect(body).toMatchObject({
      typeId: 't1',
      data: { title: 'Papierantrag' },
      applicantPrincipalId: 'p1',
      applicantName: null,
      applicantEmail: null,
      receivedOn: localToday(),
      intake: 'per PDF',
      lang: 'de',
      attachmentIds: [],
      draftToken: null,
    });
    expect(s.created).toHaveBeenCalledWith('new-1');
    expect(s.drafts.clear).toHaveBeenCalled();
    expect(s.toast.success).toHaveBeenCalled();
  });

  it('captures for a new person with draft files', async () => {
    const file: DraftFile = {
      id: 'd1',
      filename: 'antrag.pdf',
      mime: 'application/pdf',
      size: 1,
      scanned: false,
      isComparisonOffer: false,
      scanState: 'scanning',
      fieldKey: null,
    };
    const s = await setup({ drafts: fakeDrafts([file]) });
    s.comp.setMode('guest');
    s.comp.guestName.set(' Gisela ');
    s.comp.guestEmail.set('g@example.org');
    s.comp.selectType('t1');
    s.flush();
    s.comp.model['title'] = 'X';
    s.comp.form.get('title')?.setValue('X');
    s.comp.submit();
    expect(s.create.mock.calls[0][0]).toMatchObject({
      applicantPrincipalId: null,
      applicantName: 'Gisela',
      applicantEmail: 'g@example.org',
      intake: null,
      attachmentIds: ['d1'],
      draftToken: 'tok',
    });
  });

  it('refuses an incomplete form and a date in the future', async () => {
    const s = await setup();
    s.comp.submit();
    expect(s.create).not.toHaveBeenCalled();
    expect(s.toast.error).toHaveBeenCalledWith('Bitte alle Pflichtangaben ausfüllen.');
    await fillAccount(s);
    s.comp.receivedOn.set('2999-01-01');
    s.flush();
    expect(s.comp.canSubmit()).toBe(false);
    expect(screen.getByText('Das Datum darf nicht in der Zukunft liegen.')).toBeTruthy();
    s.comp.receivedOn.set('');
    expect(s.comp.canSubmit()).toBe(false);
  });

  it('ignores a second submit while one runs', async () => {
    const pending = new Subject<{ applicationId: string }>();
    const s = await setup({ create: jest.fn(() => pending) });
    await fillAccount(s);
    s.comp.submit();
    s.comp.submit();
    expect(s.create).toHaveBeenCalledTimes(1);
  });

  it('puts a 422 onto the fields it names', async () => {
    const problem: ProblemDetail = {
      type: 'about:blank',
      title: 'Unprocessable',
      status: 422,
      detail: 'Invalid application data.',
      errors: [{ field: 'title', msg: 'required' }],
    };
    const s = await setup({ create: jest.fn(() => throwError(() => ({ status: 422, error: problem }))) });
    await fillAccount(s);
    s.comp.submit();
    expect(s.drafts.markFailed).toHaveBeenCalledWith(problem);
    expect(s.toast.error).toHaveBeenCalledWith('Bitte prüfe die markierten Felder.');
    expect(s.created).not.toHaveBeenCalled();
  });

  it('shows the detail of another refusal, or a fallback', async () => {
    const refusal: ProblemDetail = {
      type: 'about:blank',
      title: 'Unprocessable',
      status: 422,
      detail: 'The applicant account is unknown.',
      errors: [{ field: 'applicantPrincipalId', msg: 'unknown' }],
    };
    const create = jest
      .fn()
      .mockReturnValueOnce(throwError(() => ({ status: 422, error: refusal })))
      .mockReturnValueOnce(throwError(() => ({ status: 500 })))
      .mockReturnValueOnce(throwError(() => ({ status: 422, error: { ...refusal, errors: undefined } })));
    const s = await setup({ create });
    await fillAccount(s);
    s.comp.submit();
    expect(s.toast.error).toHaveBeenLastCalledWith('The applicant account is unknown.');
    s.comp.submit();
    expect(s.toast.error).toHaveBeenLastCalledWith('Der Antrag konnte nicht erfasst werden.');
    s.comp.submit();
    expect(s.toast.error).toHaveBeenLastCalledWith('The applicant account is unknown.');
  });

  it('close discards the draft files and emits closed', async () => {
    const s = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(s.drafts.discard).toHaveBeenCalled();
    expect(s.closed).toHaveBeenCalled();
  });

  it('clears a pending search when it is destroyed', async () => {
    jest.useFakeTimers();
    const s = await setup();
    s.comp.onSearch('anna');
    s.fixture.destroy();
    jest.advanceTimersByTime(APPLICANT_SEARCH_DELAY_MS);
    expect(s.search).not.toHaveBeenCalled();
  });

  it('labels a candidate and formats today', () => {
    expect(candidateLabel(ANNA)).toBe('Anna Antrag · anna@example.org');
    expect(candidateLabel({ id: 'x', displayName: null, email: 'x@example.org' })).toBe('x@example.org');
    expect(localToday(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});
