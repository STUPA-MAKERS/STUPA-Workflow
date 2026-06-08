import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
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
});
