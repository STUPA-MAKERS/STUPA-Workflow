import { computed, signal } from '@angular/core';
import { Router, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationType, EffectiveForm, ProblemDetail } from '@core/api/models';
import { BrandingService } from '@core/branding/branding.service';
import { provideFormly } from '@shared/formly/formly.providers';
import { ToastService } from '@stupa-makers/ui-kit';
import { DRAFT_LAST_TYPE, DRAFT_PREFIX, ApplyWizardComponent } from './apply-wizard.component';
import { DraftAttachmentsService, type DraftFile } from './draft-attachments.service';
import { FormlyDraftFilesType } from './draft-files/formly-draft-files.type';

const TYPES: ApplicationType[] = [
  { id: 't1', name: 'Förderantrag', active: true, hasBudget: true, activeFormVersionId: 'v1', key: null, gremiumId: null },
  { id: 't2', name: 'Alt', active: false, hasBudget: false, activeFormVersionId: 'v2', key: null, gremiumId: null },
];

/** A form with a PII section (IBAN plus its display text) and a file field. */
const EFF: EffectiveForm = {
  applicationTypeId: 't1',
  formVersionId: 'v1',
  hasBudget: true,
  sections: [
    {
      key: 'plan',
      label: { de: 'Vorhaben' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
        { key: 'needs', type: 'checkbox', label: { de: 'Details nötig' } },
        {
          key: 'detail',
          type: 'textarea',
          label: { de: 'Details' },
          required: true,
          visibleIf: { '==': [{ var: 'needs' }, true] },
        },
        { key: 'receipt', type: 'file', label: { de: 'Beleg' } },
      ],
    },
    {
      key: 'costs',
      label: { de: 'Kosten' },
      fields: [{ key: 'amount', type: 'currency', label: { de: 'Betrag' } }],
    },
    {
      key: 'contact',
      label: { de: 'Kontakt' },
      fields: [
        { key: 'note', type: 'markdown', label: { de: 'Hinweis' }, help: { de: 'Auszahlung' } },
        { key: 'iban', type: 'iban', label: { de: 'IBAN' }, isPII: true, required: true },
      ],
    },
  ],
};

/** A form without PII and without files. */
const PLAIN: EffectiveForm = {
  applicationTypeId: 't1',
  formVersionId: 'v1',
  hasBudget: false,
  sections: [
    { key: 'main', label: { de: 'Antrag' }, fields: [{ key: 'title', type: 'text', label: { de: 'Titel' }, required: true }] },
  ],
};

const PRINCIPAL = {
  sub: 'u-7',
  email: 'user@example.org',
  display_name: 'Userin',
  roles: [],
  permissions: [],
  groups: [],
};

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
    markFailed: jest.fn((p: ProblemDetail | null) => {
      const ids = (p?.errors ?? [])
        .map((e) => /^attachmentIds\.(.+)$/.exec(e.field)?.[1])
        .filter((x): x is string => !!x);
      list.update((l) => l.map((f) => (ids.includes(f.id) ? { ...f, failed: true } : f)));
      return ids;
    }),
    clear: jest.fn(),
    discard: jest.fn(async () => undefined),
    scopeToFields: jest.fn(async () => undefined),
    upload: jest.fn(),
    remove: jest.fn(),
  };
}

function draft(id: string, fieldKey: string | null = null): DraftFile {
  return {
    id,
    filename: `${id}.pdf`,
    mime: 'application/pdf',
    size: 1,
    scanned: false,
    isComparisonOffer: false,
    scanState: 'scanning',
    fieldKey,
  };
}

interface SetupOpts {
  form?: EffectiveForm;
  loggedIn?: boolean;
  create?: jest.Mock;
  drafts?: ReturnType<typeof fakeDrafts>;
  types?: () => ReturnType<ApiClient['applicationTypes']>;
  effectiveForm?: () => ReturnType<ApiClient['effectiveForm']>;
  freetexts?: Record<string, Record<string, string>>;
}

async function setup(opts: SetupOpts = {}) {
  const create = opts.create ?? jest.fn(() => of({ applicationId: 'app-1' }));
  const drafts = opts.drafts ?? fakeDrafts();
  const toast = { error: jest.fn(), success: jest.fn(), show: jest.fn() };
  const api: Partial<ApiClient> = {
    applicationTypes: opts.types ?? (() => of(TYPES)),
    effectiveForm: opts.effectiveForm ?? (() => of(opts.form ?? EFF)),
    createApplication: create as unknown as ApiClient['createApplication'],
    me: (() => (opts.loggedIn ? of(PRINCIPAL) : throwError(() => ({ status: 401 })))) as unknown as ApiClient['me'],
    altchaChallenge: () => of(null),
  };
  const branding = {
    freetexts: signal(opts.freetexts ?? {}),
    attachmentLimits: signal({ maxFileBytes: 10, maxDraftFiles: 20, maxDraftBytes: 50 }),
  };
  const view = await render(ApplyWizardComponent, {
    providers: [
      provideRouter([]),
      provideFormly(),
      { provide: ApiClient, useValue: api },
      { provide: BrandingService, useValue: branding },
      { provide: ToastService, useValue: toast },
    ],
    componentProviders: [{ provide: DraftAttachmentsService, useValue: drafts }],
  });
  const router = view.fixture.debugElement.injector.get(Router);
  const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
  const comp = view.fixture.componentInstance;
  return { ...view, comp, create, drafts, toast, navigate };
}

type Setup = Awaited<ReturnType<typeof setup>>;

async function pickType(s: Setup) {
  await userEvent.click(screen.getByRole('radio', { name: 'Förderantrag' }));
  s.fixture.detectChanges();
  await s.fixture.whenStable();
}

/** The Formly input of a label in the visible step. */
function field(label: RegExp | string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

async function toReview(s: Setup) {
  await pickType(s);
  s.comp.next();
  s.fixture.detectChanges();
  await userEvent.type(field(/Titel/), 'Party');
  s.comp.next();
  s.fixture.detectChanges();
  await userEvent.type(screen.getByLabelText(/^E-Mail/), 'a@b.de');
  await userEvent.type(screen.getByLabelText(/Name \(optional\)/), 'Erika');
  await userEvent.type(field(/IBAN/), 'DE89370400440532013000');
  s.comp.next();
  s.fixture.detectChanges();
}

describe('ApplyWizardComponent', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('ap.locale', 'de');
    window.scrollTo = jest.fn();
  });
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    jest.restoreAllMocks();
  });

  it('shows the title, the guest lead and four steps before a type is chosen', async () => {
    const s = await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Antrag stellen' })).toBeInTheDocument();
    expect(screen.getByText(/Ohne Konto/)).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'Antrags-Fortschritt' });
    expect(steps.querySelectorAll('li')).toHaveLength(4);
    expect(screen.getByText('Schritt 1 von 4')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Antragsart wählen' })).toBeInTheDocument();
    // Only active types.
    expect(screen.getAllByRole('radio')).toHaveLength(1);
    // Next does nothing without a type.
    s.comp.next();
    expect(s.comp.activeIndex()).toBe(0);
  });

  it('names the type and the parts of each step once the form is in', async () => {
    const s = await setup();
    await pickType(s);
    expect(s.comp.steps().map((x) => x.hint)).toEqual([
      'Förderantrag',
      'Vorhaben und Kosten',
      'Name, E-Mail und IBAN',
      'Zusammenfassung',
    ]);
    s.comp.next();
    s.fixture.detectChanges();
    expect(screen.getByText('Schritt 2 von 4 · Förderantrag')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Angaben zum Vorhaben' })).toBeInTheDocument();
    // The PII field and its display text belong to "Kontakt", not to "Angaben".
    const details = s.comp.detailsFields()[0].fieldGroup ?? [];
    expect(details.map((f) => f.key).filter(Boolean)).toEqual(['title', 'needs', 'detail', 'receipt', 'amount']);
    expect(details.find((f) => f.key === 'receipt')?.type).toBe(FormlyDraftFilesType);
    expect(s.comp.piiFields()[0].fieldGroup?.map((f) => [f.key, f.className])).toEqual([
      ['note', 'fe-full'],
      ['iban', 'fe-half'],
    ]);
  });

  it('reveals a conditional field when its visibleIf becomes true', async () => {
    const s = await setup();
    await pickType(s);
    s.comp.next();
    s.fixture.detectChanges();
    expect(screen.queryByRole('textbox', { name: /^Details/ })).toBeNull();
    await userEvent.click(screen.getByLabelText('Details nötig'));
    s.fixture.detectChanges();
    expect(await screen.findByRole('textbox', { name: /^Details/ })).toBeInTheDocument();
  });

  it('blocks an invalid step with the errors and a toast', async () => {
    const s = await setup();
    await pickType(s);
    s.comp.next();
    s.comp.next();
    expect(s.comp.currentStep()).toBe('details');
    expect(s.toast.error).toHaveBeenCalledWith('Bitte prüfe die markierten Felder.');
    await userEvent.type(field(/Titel/), 'Party');
    s.comp.next();
    expect(s.comp.currentStep()).toBe('contact');
    // The contact step needs a valid e-mail.
    s.comp.next();
    expect(s.comp.currentStep()).toBe('contact');
    await userEvent.type(screen.getByLabelText(/^E-Mail/), 'a@b.de');
    // ... and the required IBAN.
    s.comp.next();
    expect(s.comp.currentStep()).toBe('contact');
  });

  it('waits for running uploads before it leaves the details', async () => {
    const drafts = fakeDrafts();
    drafts.busy.set(true);
    const s = await setup({ drafts });
    await pickType(s);
    s.comp.next();
    s.comp.next();
    expect(s.comp.currentStep()).toBe('details');
    expect(s.toast.show).toHaveBeenCalledWith('Bitte warte, bis alle Dateien hochgeladen sind.');
  });

  it('goes back by the button and by a done step, never forward by the stepper', async () => {
    const s = await setup();
    await pickType(s);
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: /Antragsart/ }));
    expect(s.comp.activeIndex()).toBe(0);
    s.comp.goToStep(2);
    expect(s.comp.activeIndex()).toBe(0);
    s.comp.next();
    s.comp.prev();
    s.comp.prev();
    expect(s.comp.activeIndex()).toBe(0);
  });

  it('reviews the answers, the applicant and the files, and submits with drafts and altcha', async () => {
    const drafts = fakeDrafts([draft('d1'), draft('d2', 'receipt')]);
    const s = await setup({ drafts });
    await toReview(s);
    expect(screen.getByRole('heading', { level: 2, name: 'Prüfen & absenden' })).toBeInTheDocument();
    expect(screen.getByText('Party')).toBeInTheDocument();
    expect(screen.getByText('Antragsteller:in')).toBeInTheDocument();
    expect(screen.getByText('a@b.de')).toBeInTheDocument();
    expect(screen.getByText('Erika')).toBeInTheDocument();
    const review = document.querySelector('.wz__review') as HTMLElement;
    expect(within(review).getByText('d1.pdf')).toBeInTheDocument();
    // The model holds the file ids of the field; one of them is lost before the submit.
    s.comp.model['receipt'] = ['d2', 'gone'];
    // "Weiter" has no step after the review.
    s.comp.next();
    expect(s.comp.currentStep()).toBe('review');
    const submit = screen.getByRole('button', { name: 'Antrag absenden' });
    expect(submit.closest('app-button')?.querySelector('button')).toBeDisabled();
    s.comp.onAltchaSolved('sol');
    s.fixture.detectChanges();
    s.comp.submit();
    expect(s.create).toHaveBeenCalledTimes(1);
    const payload = s.create.mock.calls[0][0];
    expect(payload).toMatchObject({
      typeId: 't1',
      applicantEmail: 'a@b.de',
      applicantName: 'Erika',
      lang: 'de',
      altcha: 'sol',
      attachmentIds: ['d1', 'd2'],
      draftToken: 'tok',
    });
    expect(payload.data).toMatchObject({ title: 'Party', iban: 'DE89370400440532013000', receipt: ['d2'] });
    expect(drafts.clear).toHaveBeenCalled();
    expect(s.navigate).toHaveBeenCalledWith(['/apply/confirmation'], { queryParams: { id: 'app-1' } });
    expect(sessionStorage.getItem(`${DRAFT_PREFIX}t1`)).toBeNull();
    expect(sessionStorage.getItem(DRAFT_LAST_TYPE)).toBeNull();
  });

  it('clears the autosave of every type on the submit', async () => {
    sessionStorage.setItem(`${DRAFT_PREFIX}t9`, JSON.stringify({ v: 1, model: { title: 'Alt' } }));
    sessionStorage.setItem('ap.other', 'keep');
    const s = await setup({ form: PLAIN, loggedIn: true });
    await waitFor(() => expect(s.comp.loggedIn()).toBe(true));
    await pickType(s);
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.type(field(/Titel/), 'X');
    s.comp.persistDraft();
    s.comp.next();
    s.comp.submit();
    expect(s.create).toHaveBeenCalled();
    expect(sessionStorage.getItem(`${DRAFT_PREFIX}t9`)).toBeNull();
    expect(sessionStorage.getItem(`${DRAFT_PREFIX}t1`)).toBeNull();
    expect(sessionStorage.getItem('ap.other')).toBe('keep');
  });

  it('gives a file field its draft files back after a reload, so a required field passes', async () => {
    const required: EffectiveForm = {
      ...PLAIN,
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [
            { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
            { key: 'receipt', type: 'file', label: { de: 'Beleg' }, required: true },
          ],
        },
      ],
    };
    // The tab reloaded: the autosave (without the file field) and the draft files are back.
    sessionStorage.setItem(DRAFT_LAST_TYPE, 't1');
    sessionStorage.setItem(`${DRAFT_PREFIX}t1`, JSON.stringify({ v: 1, model: { title: 'X' }, step: 'details' }));
    const lost = { ...draft('d3', 'receipt'), failed: true };
    const drafts = fakeDrafts([draft('d1'), draft('d2', 'receipt'), lost]);
    const s = await setup({ form: required, loggedIn: true, drafts });
    await waitFor(() => expect(s.comp.currentStep()).toBe('details'));
    s.fixture.detectChanges();
    expect(drafts.scopeToFields).toHaveBeenCalledWith(new Set(['receipt']));
    expect(s.comp.model['receipt']).toEqual(['d2']);
    expect(s.comp.detailsForm.get('receipt')?.value).toEqual(['d2']);
    s.comp.next();
    expect(s.comp.currentStep()).toBe('review');
  });

  it('submits without a solution when ALTCHA is off, and without drafts no token', async () => {
    const s = await setup({ form: PLAIN });
    await pickType(s);
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.type(field(/Titel/), 'X');
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.type(screen.getByLabelText(/^E-Mail/), 'a@b.de');
    s.comp.next();
    s.fixture.detectChanges();
    expect(s.comp.canSubmit()).toBe(false);
    s.comp.onAltchaUnavailable();
    s.comp.submit();
    expect(s.create.mock.calls[0][0]).toMatchObject({
      altcha: null,
      applicantName: null,
      attachmentIds: [],
      draftToken: null,
    });
  });

  it('skips the contact step for a signed-in user without PII fields', async () => {
    const s = await setup({ form: PLAIN, loggedIn: true });
    await waitFor(() => expect(s.comp.stepKeys()).toEqual(['type', 'details', 'review']));
    expect(screen.getByText(/mit deinem Konto/)).toBeInTheDocument();
    await pickType(s);
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.type(field(/Titel/), 'X');
    s.comp.next();
    s.fixture.detectChanges();
    expect(s.comp.currentStep()).toBe('review');
    expect(screen.queryByRole('button', { name: /kein Roboter/ })).toBeNull();
    expect(screen.getByText('user@example.org')).toBeInTheDocument();
    s.comp.submit();
    expect(s.create.mock.calls[0][0]).toMatchObject({ applicantEmail: null, applicantName: null, altcha: null });
  });

  it('shows the account and the PII fields in the contact step of a signed-in user', async () => {
    const s = await setup({ loggedIn: true });
    await waitFor(() => expect(s.comp.loggedIn()).toBe(true));
    await pickType(s);
    expect(s.comp.stepKeys()).toHaveLength(4);
    expect(s.comp.steps()[2].hint).toBe('IBAN');
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.type(field(/Titel/), 'X');
    s.comp.next();
    s.fixture.detectChanges();
    expect(screen.getByText('Dein Konto')).toBeInTheDocument();
    expect(screen.getAllByText('Userin').length).toBeGreaterThan(0);
    expect(screen.queryByLabelText(/^E-Mail/)).toBeNull();
  });

  it('falls back to the display name when the account has no e-mail', async () => {
    const s = await setup({ loggedIn: true });
    await waitFor(() => expect(s.comp.loggedIn()).toBe(true));
    const auth = s.fixture.debugElement.injector.get(
      (await import('@core/auth/auth.service')).AuthService,
    );
    (auth as unknown as { _principal: { set(v: unknown): void } })._principal.set({
      ...PRINCIPAL,
      email: null,
    });
    expect(s.comp.reviewEmail()).toBe('Userin');
  });

  it('sends lost files back to the details step', async () => {
    const drafts = fakeDrafts([draft('d1', 'receipt'), draft('d2')]);
    const problem = {
      code: 'draft_attachments_missing',
      errors: [{ field: 'attachmentIds.d1', msg: 'missing' }],
    };
    const create = jest.fn(() => throwError(() => ({ status: 422, error: problem })));
    const s = await setup({ drafts, create });
    await toReview(s);
    s.comp.model['receipt'] = ['d1'];
    s.comp.model['other'] = 'x';
    s.comp.onAltchaSolved('sol');
    s.comp.submit();
    expect(drafts.markFailed).toHaveBeenCalledWith(problem);
    expect(s.comp.currentStep()).toBe('details');
    expect(s.comp.model['receipt']).toBeNull();
    expect(s.toast.error).toHaveBeenCalledWith(
      'Einige Dateien sind nicht mehr vorhanden. Bitte lade sie neu hoch.',
    );
    // A new solution is needed for the next submit.
    expect(s.comp.altchaSolution()).toBeNull();
    expect(s.comp.altchaRound()).toBe(1);
  });

  it('puts a 422 on the PII field and opens the contact step', async () => {
    const problem = { code: 'validation_error', errors: [{ field: 'iban', msg: 'invalid IBAN' }] };
    const create = jest.fn(() => throwError(() => ({ status: 422, error: problem })));
    const s = await setup({ create });
    await toReview(s);
    s.comp.onAltchaSolved('sol');
    s.comp.submit();
    expect(s.comp.currentStep()).toBe('contact');
    expect(s.toast.error).toHaveBeenCalledWith('Bitte prüfe die markierten Felder.');
  });

  it('puts a 422 on a details field and opens the details step', async () => {
    const problem = { code: 'x', errors: [{ field: 'title', msg: 'too long' }] };
    const create = jest.fn(() => throwError(() => ({ status: 422, error: problem })));
    const s = await setup({ create });
    await toReview(s);
    s.comp.onAltchaSolved('sol');
    s.comp.submit();
    expect(s.comp.currentStep()).toBe('details');
  });

  it('toasts the problem of a 422 it cannot place, and other errors', async () => {
    const create = jest
      .fn()
      .mockReturnValueOnce(throwError(() => ({ status: 422, error: { code: 'x', detail: 'Nope.' } })))
      .mockReturnValueOnce(throwError(() => ({ status: 422, error: null })))
      .mockReturnValueOnce(throwError(() => ({ status: 500, error: { detail: 'Server kaputt.' } })))
      .mockReturnValueOnce(throwError(() => ({ status: 0 })));
    const s = await setup({ create });
    await toReview(s);
    for (let i = 0; i < 4; i++) {
      s.comp.onAltchaSolved(`sol${i}`);
      s.comp.submit();
    }
    expect(s.toast.error.mock.calls.map((c) => c[0])).toEqual([
      'Nope.',
      'Antrag konnte nicht gesendet werden.',
      'Server kaputt.',
      'Antrag konnte nicht gesendet werden.',
    ]);
    expect(s.comp.submitting()).toBe(false);
  });

  it('does not submit when it cannot or while it submits', async () => {
    const s = await setup();
    s.comp.submit();
    expect(s.create).not.toHaveBeenCalled();
    await toReview(s);
    s.comp.onAltchaSolved('sol');
    s.comp.submitting.set(true);
    s.comp.submit();
    expect(s.create).not.toHaveBeenCalled();
    s.comp.submitting.set(false);
    s.comp.typeId.set(null);
    s.comp.submit();
    expect(s.create).not.toHaveBeenCalled();
  });

  it('autosaves the answers without contact, PII and file fields', async () => {
    const s = await setup();
    await toReview(s);
    s.comp.model['receipt'] = ['d1'];
    s.comp.persistDraft();
    const stored = JSON.parse(sessionStorage.getItem(`${DRAFT_PREFIX}t1`) as string);
    expect(stored).toEqual({ v: 1, model: { title: 'Party' }, step: 'review' });
    expect(JSON.stringify(stored)).not.toContain('a@b.de');
    expect(JSON.stringify(stored)).not.toContain('Erika');
    expect(JSON.stringify(stored)).not.toContain('DE89');
    expect(sessionStorage.getItem(DRAFT_LAST_TYPE)).toBe('t1');
    expect(screen.getByText('Entwurf in diesem Tab gespeichert')).toBeInTheDocument();
    // Nothing of the draft goes into localStorage (only the language is there).
    expect(Object.keys(localStorage)).toEqual(['ap.locale']);
  });

  it('writes the autosave a short time after a change', async () => {
    jest.useFakeTimers();
    try {
      const s = await setup({ form: PLAIN });
      s.comp.selectType('t1');
      s.fixture.detectChanges();
      s.comp.model['title'] = 'Neu';
      s.comp.activeIndex.set(1);
      s.fixture.detectChanges();
      jest.advanceTimersByTime(500);
      expect(JSON.parse(sessionStorage.getItem(`${DRAFT_PREFIX}t1`) as string).model).toEqual({ title: 'Neu' });
    } finally {
      jest.useRealTimers();
    }
  });

  it('restores the autosave of the last type, but not past an empty contact step', async () => {
    sessionStorage.setItem(DRAFT_LAST_TYPE, 't1');
    sessionStorage.setItem(
      `${DRAFT_PREFIX}t1`,
      JSON.stringify({ v: 1, model: { title: 'Gespeichert', iban: 'leak', receipt: ['x'] }, step: 'review' }),
    );
    const s = await setup();
    await waitFor(() => expect(s.comp.typeId()).toBe('t1'));
    expect(s.comp.model['title']).toBe('Gespeichert');
    expect(s.comp.model['iban']).toBeUndefined();
    expect(s.comp.model['receipt']).toBeUndefined();
    expect(s.comp.currentStep()).toBe('contact');
    expect(s.comp.saved()).toBe(true);
  });

  it('restores the stored step of a signed-in user', async () => {
    sessionStorage.setItem(DRAFT_LAST_TYPE, 't1');
    sessionStorage.setItem(`${DRAFT_PREFIX}t1`, JSON.stringify({ v: 1, model: { title: 'X' }, step: 'review' }));
    const s = await setup({ form: PLAIN, loggedIn: true });
    await waitFor(() => expect(s.comp.currentStep()).toBe('review'));
  });

  it('ignores a broken autosave and an unknown last type', async () => {
    sessionStorage.setItem(DRAFT_LAST_TYPE, 'unknown');
    sessionStorage.setItem(`${DRAFT_PREFIX}t1`, '{broken');
    const s = await setup();
    expect(s.comp.typeId()).toBeNull();
    await pickType(s);
    expect(s.comp.activeIndex()).toBe(0);
  });

  it('ignores an autosave without answers and with an unknown step', async () => {
    sessionStorage.setItem(`${DRAFT_PREFIX}t1`, JSON.stringify({ v: 1, step: 'nowhere' }));
    const s = await setup();
    s.comp.selectType('t1');
    expect(s.comp.activeIndex()).toBe(0);
    expect(s.comp.saved()).toBe(false);
  });

  it('keeps working when the storage throws', async () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const s = await setup({ form: PLAIN, loggedIn: true });
    await waitFor(() => expect(s.comp.loggedIn()).toBe(true));
    await pickType(s);
    s.comp.next();
    s.comp.persistDraft();
    expect(s.comp.saved()).toBe(false);
    s.fixture.detectChanges();
    await userEvent.type(field(/Titel/), 'X');
    s.comp.next();
    s.comp.submit();
    expect(s.create).toHaveBeenCalled();
  });

  it('does not autosave without a type', async () => {
    const s = await setup();
    s.comp.persistDraft();
    expect(sessionStorage.getItem(DRAFT_LAST_TYPE)).toBeNull();
  });

  it('discards the draft after the confirmation', async () => {
    const drafts = fakeDrafts([draft('d1')]);
    const s = await setup({ drafts });
    await pickType(s);
    s.comp.next();
    s.fixture.detectChanges();
    await userEvent.type(field(/Titel/), 'Weg');
    s.comp.persistDraft();
    await userEvent.click(screen.getAllByRole('button', { name: 'Entwurf verwerfen' })[0]);
    expect(s.comp.confirmDiscard()).toBe(true);
    s.fixture.detectChanges();
    const dialogButtons = screen.getAllByRole('button', { name: 'Entwurf verwerfen' });
    await userEvent.click(dialogButtons[dialogButtons.length - 1]);
    await waitFor(() => expect(drafts.discard).toHaveBeenCalled());
    expect(s.comp.model).toEqual({});
    expect(s.comp.activeIndex()).toBe(0);
    expect(sessionStorage.getItem(`${DRAFT_PREFIX}t1`)).toBeNull();
    expect(sessionStorage.getItem(DRAFT_LAST_TYPE)).toBeNull();
  });

  it('keeps the draft when the confirmation is cancelled', async () => {
    const s = await setup();
    await pickType(s);
    s.comp.confirmDiscard.set(true);
    s.fixture.detectChanges();
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' })[0]);
    expect(s.comp.confirmDiscard()).toBe(false);
  });

  it('discards without a loaded form', async () => {
    const s = await setup();
    await s.comp.discardDraft();
    expect(s.comp.activeIndex()).toBe(0);
  });

  it('renders the configured apply info as Markdown', async () => {
    const s = await setup({ freetexts: { applyInfo: { de: '**Frist:** 1. Mai' } } });
    expect(s.comp.applyInfoHtml()).toContain('<strong>Frist:</strong>');
    expect(screen.getByText('Frist:')).toBeInTheDocument();
  });

  it('toasts when the types fail to load', async () => {
    const s = await setup({ types: () => throwError(() => new Error('x')) });
    expect(s.toast.error).toHaveBeenCalledWith('Antragsarten konnten nicht geladen werden.');
  });

  it('toasts when the form fails to load', async () => {
    const s = await setup({ effectiveForm: () => throwError(() => new Error('x')) });
    s.comp.selectType('t1');
    expect(s.toast.error).toHaveBeenCalledWith('Formular konnte nicht geladen werden.');
    expect(s.comp.loadingForm()).toBe(false);
  });

  it('ignores a second pick of the same type', async () => {
    const effectiveForm = jest.fn(() => of(PLAIN));
    const s = await setup({ effectiveForm });
    s.comp.selectType('t1');
    s.comp.selectType('t1');
    expect(effectiveForm).toHaveBeenCalledTimes(1);
  });

  it('names a single part without a list and a type without a name', async () => {
    const s = await setup({ form: PLAIN, loggedIn: true });
    await waitFor(() => expect(s.comp.loggedIn()).toBe(true));
    s.comp.selectType('t1');
    expect(s.comp.steps()[1].hint).toBe('Antrag');
    s.comp.types.set([]);
    expect(s.comp.steps()[0].hint).toBe('');
    s.comp.activeIndex.set(1);
    expect(s.comp.stepLine()).toBe('Schritt 2 von 3');
  });
});
