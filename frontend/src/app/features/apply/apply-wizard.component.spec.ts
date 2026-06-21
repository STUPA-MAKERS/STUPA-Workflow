import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { ApplicationType, EffectiveForm } from '@core/api/models';
import { provideFormly } from '@shared/formly/formly.providers';
import { ApplyWizardComponent } from './apply-wizard.component';

const TYPES: ApplicationType[] = [
  {
    id: 't1',
    name: 'Finanzantrag',
    active: true,
    hasBudget: true,
    activeFormVersionId: 'v1',
    key: null,
    gremiumId: null,
  },
];

const EFF: EffectiveForm = {
  applicationTypeId: 't1',
  formVersionId: 'v1',
  budgetPotId: 'pot1',
  sections: [
    {
      key: 'main',
      label: { de: 'Antrag' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
        { key: 'needs_detail', type: 'checkbox', label: { de: 'Details nötig' } },
        {
          key: 'detail',
          type: 'textarea',
          label: { de: 'Detailangaben' },
          required: true,
          visibleIf: { '==': [{ var: 'needs_detail' }, true] },
        },
        { key: 'amount', type: 'currency', label: { de: 'Betrag' }, required: true, validation: { min: 0 } },
        {
          key: 'category',
          type: 'select',
          label: { de: 'Kategorie' },
          options: [{ value: 'event', label: { de: 'Veranstaltung' } }],
        },
        {
          key: 'tags',
          type: 'multiselect',
          label: { de: 'Tags' },
          options: [{ value: 'a', label: { de: 'Alpha' } }],
        },
        { key: 'info', type: 'markdown', label: { de: 'Info' }, help: { de: 'Hinweis' } },
      ],
    },
    {
      key: 'budget',
      label: { de: 'Budget' },
      fields: [{ key: 'cofunding', type: 'currency', label: { de: 'Eigenanteil' } }],
    },
  ],
};

function fakeApi(create = jest.fn(() => of({ applicationId: 'app-1' }))): Partial<ApiClient> {
  return {
    applicationTypes: () => of(TYPES),
    effectiveForm: () => of(EFF),
    createApplication: create as unknown as ApiClient['createApplication'],
    // Anonyme Session (kein Principal) — Default-Pfad mit Kontakt-Schritt + Altcha (#24).
    me: (() => of(null)) as unknown as ApiClient['me'],
    // Branding-Info unter der Typ-Auswahl (#18) — leer im Test-Default.
    publicSiteConfig: () => of({ version: 1, branding: null }),
  };
}

async function setup(create?: jest.Mock) {
  const view = await render(ApplyWizardComponent, {
    providers: [
      provideRouter([]),
      provideFormly(),
      { provide: ApiClient, useValue: fakeApi(create) },
    ],
  });
  return view;
}

/** Wie {@link setup}, aber mit eingeloggter Session (Principal) für den #24-Pfad. */
async function setupLoggedIn(create = jest.fn(() => of({ applicationId: 'app-1' }))) {
  const api = {
    ...fakeApi(create),
    me: (() =>
      of({
        sub: 'u-7',
        email: 'user@example.org',
        display_name: 'Userin',
        roles: [],
        permissions: [],
        groups: [],
      })) as unknown as ApiClient['me'],
  };
  const view = await render(ApplyWizardComponent, {
    providers: [provideRouter([]), provideFormly(), { provide: ApiClient, useValue: api }],
  });
  return { ...view, create };
}

describe('ApplyWizardComponent', () => {
  beforeEach(() => {
    sessionStorage.clear();
    // Locale auf DE pinnen — die deutschen Assertions unten sollen unabhängig
    // von der jsdom-Navigator-Sprache (en-US) gelten.
    localStorage.setItem('ap.locale', 'de');
  });
  afterEach(() => localStorage.clear());

  it('renders the title and a single step before a type is chosen', async () => {
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: /Antrag stellen/ })).toBeInTheDocument();
    expect(screen.getByText('Finanzantrag')).toBeInTheDocument();
  });

  it('builds the full step path once a type with its effective form is selected', async () => {
    const { fixture } = await setup();
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    const comp = fixture.componentInstance;
    expect(comp.effForm()).not.toBeNull();
    // Antragsart + Kontakt + 2 Sektionen + Prüfen
    expect(comp.steps().length).toBe(5);
  });

  it('reveals a conditional field when its visibleIf becomes true', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → Kontakt
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → Sektion main

    expect(screen.queryByLabelText(/Detailangaben/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Details nötig/));
    expect(screen.getByLabelText(/Detailangaben/)).toBeInTheDocument();
  });

  it('walks through the wizard and submits with the collected data + altcha', async () => {
    const create = jest.fn(() => of({ applicationId: 'app-1' }));
    const { fixture } = await setup(create);
    const comp = fixture.componentInstance;
    const router = TestBed.inject(Router);
    const navSpy = jest.spyOn(router, 'navigate').mockResolvedValue(true);

    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.contactForm.setValue({ email: 'antrag@stupa.de', name: 'Max' });
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → Kontakt
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → main

    await userEvent.type(screen.getByLabelText(/Titel/), 'Sommerfest');
    await userEvent.type(screen.getByLabelText(/Betrag/), '500');
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → budget
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → review

    expect(screen.getByText('Sommerfest')).toBeInTheDocument();

    // Altcha-Widget separat getestet — Lösung hier direkt einspeisen.
    comp.onAltchaSolved('sol');
    fixture.detectChanges();
    expect(comp.canSubmit()).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: /Antrag absenden/ }));

    expect(create).toHaveBeenCalledTimes(1);
    const payload = create.mock.calls[0][0] as {
      typeId: string;
      data: Record<string, unknown>;
      applicantEmail: string;
      altcha: string;
    };
    expect(payload.typeId).toBe('t1');
    expect(payload.applicantEmail).toBe('antrag@stupa.de');
    expect(payload.data['title']).toBe('Sommerfest');
    expect(payload.altcha).toBe('sol');
    expect(navSpy).toHaveBeenCalledWith(['/apply/confirmation'], { queryParams: { id: 'app-1' } });
  });

  it('formats the review summary (boolean, option label, multiselect) and discards the draft', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.model = { title: 'Fest', needs_detail: true, category: 'event', tags: ['a'] };
    const rows = comp.summary();
    const byLabel = (label: string) => rows.find((r) => r.label === label)?.value;
    expect(byLabel('Titel')).toBe('Fest');
    expect(byLabel('Details nötig')).toBe('Ja');
    expect(byLabel('Kategorie')).toBe('Veranstaltung');
    expect(byLabel('Tags')).toBe('Alpha');

    comp.discardDraft();
    expect(comp.model).toEqual({});
    expect(comp.activeIndex()).toBe(0);
  });

  it('skips the contact step and Altcha for a logged-in user (#24)', async () => {
    const { fixture, create } = await setupLoggedIn();
    const comp = fixture.componentInstance;
    const router = TestBed.inject(Router);
    jest.spyOn(router, 'navigate').mockResolvedValue(true);

    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    expect(comp.loggedIn()).toBe(true);
    // Antragsart + 2 Sektionen + Prüfen — KEIN Kontakt-Schritt.
    expect(comp.steps().length).toBe(4);
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → main direkt

    await userEvent.type(screen.getByLabelText(/Titel/), 'Sommerfest');
    await userEvent.type(screen.getByLabelText(/Betrag/), '500');
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → budget
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → review

    // Kein Altcha-Widget, trotzdem absendbar.
    expect(comp.canSubmit()).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: /Antrag absenden/ }));

    expect(create).toHaveBeenCalledTimes(1);
    const payload = create.mock.calls[0][0] as { applicantEmail: string | null; altcha: string | null };
    // Identität/Altcha leitet das Backend ab → FE sendet null.
    expect(payload.applicantEmail).toBeNull();
    expect(payload.altcha).toBeNull();
  });

  it('blocks advancing past an invalid contact step', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → Kontakt
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // invalid email → bleibt
    expect(comp.currentStep()).toBe('contact');
  });

  it('toasts when the application types fail to load', async () => {
    const errSpy = jest.fn();
    await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ToastService, useValue: { error: errSpy, success: jest.fn() } },
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(),
            applicationTypes: () => throwError(() => new Error('boom')),
          },
        },
      ],
    });
    expect(errSpy).toHaveBeenCalledWith('Antragsarten konnten nicht geladen werden.');
  });

  it('renders the configured apply info as markdown HTML (#18)', async () => {
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(),
            publicSiteConfig: () =>
              of({
                version: 1,
                branding: { freetexts: { applyInfo: { de: '**Hallo** Welt' } } },
              }),
          },
        },
      ],
    });
    const html = fixture.componentInstance.applyInfoHtml();
    expect(html).toContain('<strong>Hallo</strong>');
  });

  it('yields empty apply-info HTML when no branding text is configured', async () => {
    const { fixture } = await setup();
    // Default fakeApi → branding: null → applyInfo signal stays null → empty html.
    expect(fixture.componentInstance.applyInfoHtml()).toBe('');
  });

  it('toasts when the effective form fails to load and clears the loading flag', async () => {
    const errSpy = jest.fn();
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ToastService, useValue: { error: errSpy, success: jest.fn() } },
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(),
            effectiveForm: () => throwError(() => new Error('nope')),
          },
        },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    expect(errSpy).toHaveBeenCalledWith('Formular konnte nicht geladen werden.');
    expect(comp.loadingForm()).toBe(false);
    expect(comp.effForm()).toBeNull();
  });

  it('ignores selecting the already-active type (no reload)', async () => {
    const eff = jest.fn(() => of(EFF));
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        {
          provide: ApiClient,
          useValue: { ...fakeApi(), effectiveForm: eff as unknown as ApiClient['effectiveForm'] },
        },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    expect(eff).toHaveBeenCalledTimes(1);
    comp.selectType('t1'); // same id → guarded
    expect(eff).toHaveBeenCalledTimes(1);
  });

  it('blocks advancing past an invalid form section', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → Kontakt
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → main section
    expect(comp.currentStep()).toBe('section');
    // Required Titel/Betrag empty → section invalid → stays.
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ }));
    expect(comp.currentStep()).toBe('section');
    expect(comp.activeIndex()).toBe(2);
  });

  it('navigates back with prev() and clamps at zero', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    await userEvent.click(screen.getByRole('button', { name: /Weiter/ })); // → Kontakt (idx 1)
    expect(comp.activeIndex()).toBe(1);
    comp.prev();
    expect(comp.activeIndex()).toBe(0);
    comp.prev(); // clamps
    expect(comp.activeIndex()).toBe(0);
  });

  it('prev() persists nothing when no type (draftKey null) is selected', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    // No type chosen → draftKey() null → persistDraft early-returns.
    expect(() => comp.prev()).not.toThrow();
    expect(sessionStorage.length).toBe(0);
  });

  it('does not advance from the type step without a chosen type', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.next(); // no type selected → guarded
    expect(comp.activeIndex()).toBe(0);
  });

  it('marks altcha as not required when the widget reports it unavailable', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    expect(comp.altchaRequired()).toBe(true);
    comp.onAltchaUnavailable();
    expect(comp.altchaRequired()).toBe(false);
  });

  it('toasts the backend problem detail when the submit fails', async () => {
    const errSpy = jest.fn();
    const create = jest.fn(() =>
      throwError(() => ({ error: { detail: 'Topf erschöpft' } })),
    );
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ToastService, useValue: { error: errSpy, success: jest.fn() } },
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(create),
            createApplication: create as unknown as ApiClient['createApplication'],
          },
        },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    comp.model = { title: 'X', amount: 5 };
    comp.onAltchaSolved('sol');
    comp.submit();
    expect(create).toHaveBeenCalledTimes(1);
    expect(errSpy).toHaveBeenCalledWith('Topf erschöpft');
    expect(comp.submitting()).toBe(false);
  });

  it('falls back to a generic submit-error toast without a problem detail', async () => {
    const errSpy = jest.fn();
    const create = jest.fn(() => throwError(() => ({})));
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ToastService, useValue: { error: errSpy, success: jest.fn() } },
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(create),
            createApplication: create as unknown as ApiClient['createApplication'],
          },
        },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    comp.onAltchaSolved('sol');
    comp.submit();
    expect(errSpy).toHaveBeenCalledWith('Antrag konnte nicht gesendet werden.');
  });

  it('does not submit when canSubmit is false or already submitting', async () => {
    const create = jest.fn(() => of({ applicationId: 'app-1' }));
    const { fixture } = await setup(create);
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    // canSubmit false: contact invalid + no altcha.
    expect(comp.canSubmit()).toBe(false);
    comp.submit();
    expect(create).not.toHaveBeenCalled();

    // submitting() guard: flip the flag and confirm submit() bails.
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    comp.model = { title: 'X' };
    comp.onAltchaSolved('sol');
    comp.submitting.set(true);
    comp.submit();
    expect(create).not.toHaveBeenCalled();
  });

  it('persists a draft to sessionStorage on navigation', async () => {
    const create = jest.fn(() => of({ applicationId: 'app-1' }));
    const { fixture } = await setup(create);
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.contactForm.setValue({ email: 'draft@b.de', name: 'Erika' });
    comp.model = { title: 'Entwurf' };
    comp.next(); // persistDraft → writes to sessionStorage

    const raw = sessionStorage.getItem('ap.draft.t1');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw as string);
    expect(parsed.model.title).toBe('Entwurf');
    expect(parsed.contact.email).toBe('draft@b.de');
  });

  it('restores a previously persisted draft when its type loads', async () => {
    sessionStorage.setItem(
      'ap.draft.t1',
      JSON.stringify({
        model: { title: 'Entwurf' },
        contact: { email: 'draft@b.de', name: 'Erika' },
        activeIndex: 1,
      }),
    );
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.selectType('t1'); // loadForm → restoreDraft
    expect(comp.model['title']).toBe('Entwurf');
    expect(comp.contactForm.controls.email.value).toBe('draft@b.de');
    expect(comp.contactForm.controls.name.value).toBe('Erika');
  });

  it('ignores a corrupt draft payload without throwing', async () => {
    sessionStorage.setItem('ap.draft.t1', '{not valid json');
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    expect(() => comp.selectType('t1')).not.toThrow();
    expect(comp.model).toEqual({});
  });

  it('restores a draft that contains no model or contact (partial payload)', async () => {
    sessionStorage.setItem('ap.draft.t1', JSON.stringify({ activeIndex: 1 }));
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    expect(comp.model).toEqual({});
    expect(comp.contactForm.controls.email.value).toBe('');
  });

  it('restores a contact-only draft and defaults the missing name to empty', async () => {
    sessionStorage.setItem(
      'ap.draft.t1',
      JSON.stringify({ contact: { email: 'only@mail.de' } }), // no name field
    );
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    expect(comp.contactForm.controls.email.value).toBe('only@mail.de');
    expect(comp.contactForm.controls.name.value).toBe('');
  });

  it('survives a sessionStorage.getItem that throws while restoring', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    const spy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => comp.selectType('t1')).not.toThrow();
    expect(comp.model).toEqual({});
    spy.mockRestore();
  });

  it('survives a sessionStorage.setItem that throws while persisting', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    expect(() => comp.next()).not.toThrow();
    spy.mockRestore();
  });

  it('tolerates a failing public site-config request (#18 best-effort)', async () => {
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(),
            publicSiteConfig: () => throwError(() => new Error('offline')),
          },
        },
      ],
    });
    // applyInfo never set → empty html, no crash.
    expect(fixture.componentInstance.applyInfoHtml()).toBe('');
  });

  it('summarises cost positions as count + preferred-offer sum', async () => {
    const eff: EffectiveForm = {
      ...EFF,
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [{ key: 'kosten', type: 'positions', label: { de: 'Kosten' } }],
        },
      ],
    };
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ApiClient, useValue: { ...fakeApi(), effectiveForm: () => of(eff) } },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    comp.model = {
      kosten: [
        { label: 'Zelt', offers: [{ value: 120, preferred: true }, { value: 150 }] },
        { label: 'Musik', offers: [{ value: 80, preferred: true }] },
        { label: 'Ohne', offers: [] },
        { label: 'KeineOffers' }, // offers undefined → `?? []` branch + preferred value `?? 0`
      ],
    };
    const rows = comp.summary();
    const kosten = rows.find((r) => r.label === 'Kosten')?.value ?? '';
    expect(kosten).toMatch(/4 ×/);
    expect(kosten).toMatch(/200/);
  });

  it('treats a non-array positions value as empty in the summary', async () => {
    const eff: EffectiveForm = {
      ...EFF,
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [{ key: 'kosten', type: 'positions', label: { de: 'Kosten' } }],
        },
      ],
    };
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        { provide: ApiClient, useValue: { ...fakeApi(), effectiveForm: () => of(eff) } },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    comp.model = { kosten: 'not-an-array' };
    // formatValue → formatPositions('not-an-array') → '' → row dropped.
    expect(comp.summary().some((r) => r.label === 'Kosten')).toBe(false);
  });

  it('renders unknown option values via their raw string in the summary', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    // category has option {event}; an unknown value falls back to String(value).
    comp.model = { category: 'unknown-value', tags: ['x', 'a'] };
    const rows = comp.summary();
    expect(rows.find((r) => r.label === 'Kategorie')?.value).toBe('unknown-value');
    // multiselect: 'x' unknown → raw, 'a' → 'Alpha'.
    expect(rows.find((r) => r.label === 'Tags')?.value).toBe('x, Alpha');
  });

  it('renders a false boolean as "Nein" in the summary', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.model = { needs_detail: false };
    expect(comp.summary().find((r) => r.label === 'Details nötig')?.value).toBe('Nein');
  });

  it('returns an empty summary before any form is loaded', async () => {
    const { fixture } = await setup();
    // No type selected → effForm null → buildSummary short-circuits.
    expect(fixture.componentInstance.summary()).toEqual([]);
  });

  it('currentSection is null when the active index points past the sections', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    await userEvent.click(screen.getByRole('radio', { name: /Finanzantrag/ }));
    comp.activeIndex.set(99); // beyond the section range
    expect(comp.currentSection()).toBeNull();
  });

  it('exposes the contact email as the review email for anonymous users', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.contactForm.controls.email.setValue('anon@mail.de');
    expect(comp.reviewEmail()).toBe('anon@mail.de');
  });

  it('exposes the account email as the review email when logged in', async () => {
    const { fixture } = await setupLoggedIn();
    expect(fixture.componentInstance.reviewEmail()).toBe('user@example.org');
  });

  it('falls back to the display name when the logged-in principal has no email', async () => {
    const api = {
      ...fakeApi(),
      me: (() =>
        of({
          sub: 'u-9',
          email: undefined, // nullish → ?? falls back to display name
          display_name: 'Namensträgerin',
          roles: [],
          permissions: [],
          groups: [],
        })) as unknown as ApiClient['me'],
    };
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [provideRouter([]), provideFormly(), { provide: ApiClient, useValue: api }],
    });
    expect(fixture.componentInstance.reviewEmail()).toBe('Namensträgerin');
  });

  it('does not submit a logged-in user when no type is chosen (typeId guard)', async () => {
    const create = jest.fn(() => of({ applicationId: 'app-1' }));
    const { fixture } = await setupLoggedIn(create);
    const comp = fixture.componentInstance;
    // Logged in + no sections + no contact/altcha → canSubmit true, but no typeId.
    expect(comp.canSubmit()).toBe(true);
    comp.submit();
    expect(create).not.toHaveBeenCalled();
  });

  it('sends a null budgetPotId when the effective form has no budget pot', async () => {
    const create = jest.fn(() => of({ applicationId: 'app-1' }));
    const noPot: EffectiveForm = { ...EFF, budgetPotId: undefined };
    const { fixture } = await render(ApplyWizardComponent, {
      providers: [
        provideRouter([]),
        provideFormly(),
        {
          provide: ApiClient,
          useValue: {
            ...fakeApi(create),
            effectiveForm: () => of(noPot),
            createApplication: create as unknown as ApiClient['createApplication'],
          },
        },
      ],
    });
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    comp.contactForm.setValue({ email: 'a@b.de', name: '' });
    comp.model = { title: 'X' };
    comp.onAltchaSolved('sol');
    comp.submit();
    const payload = create.mock.calls[0][0] as { budgetPotId: string | null; applicantName: string | null };
    expect(payload.budgetPotId).toBeNull();
    // name empty string → applicantName null (the `|| null` branch).
    expect(payload.applicantName).toBeNull();
  });

  it('discardDraft is a no-op for clearing when no type is selected', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    // No type → draftKey() null → clearDraft returns early; still resets state.
    expect(() => comp.discardDraft()).not.toThrow();
    expect(comp.model).toEqual({});
    expect(comp.activeIndex()).toBe(0);
  });

  it('restores a draft whose contact entry omits the email field', async () => {
    sessionStorage.setItem(
      'ap.draft.t1',
      JSON.stringify({ contact: { name: 'Nur Name' } }), // no email field
    );
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.selectType('t1');
    expect(comp.contactForm.controls.email.value).toBe('');
    expect(comp.contactForm.controls.name.value).toBe('Nur Name');
  });

  it('survives a sessionStorage.removeItem that throws while clearing', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp.selectType('t1'); // sets typeId → clearDraft has a key
    const spy = jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('locked');
    });
    expect(() => comp.discardDraft()).not.toThrow();
    spy.mockRestore();
  });
});
