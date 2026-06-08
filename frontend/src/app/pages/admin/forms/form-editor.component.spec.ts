import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { FormFieldDef, I18nMap } from '@core/api/models';
import { AdminApiService } from '../admin-api.service';
import type { ApplicationTypeFull, FormDraft } from '../admin.models';
import { FormEditorComponent } from './form-editor.component';

const TYPE: ApplicationTypeFull = {
  id: 'f1',
  name: { de: 'Förderantrag', en: 'Funding' },
  gremiumId: 'g1',
  hasBudget: false,
  activeFormVersionId: 'fv1',
};

function draft(fields: FormFieldDef[], description?: I18nMap): FormDraft {
  return { applicationTypeId: 'f1', formVersionId: 'fv1', version: 1, active: true, description, fields };
}

async function setup(d: FormDraft) {
  const createFormVersion = jest.fn(() => of({ id: 'fv2' }));
  const updateApplicationType = jest.fn(() => of(void 0));
  const api = {
    listApplicationTypesFull: jest.fn(() => of([TYPE])),
    getFormDraft: jest.fn(() => of(d)),
    createFormVersion,
    updateApplicationType,
  };
  const view = await render(FormEditorComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ id: 'f1' })) } },
    ],
  });
  return { ...view, createFormVersion, updateApplicationType };
}

describe('FormEditorComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the draft title and questions', async () => {
    await setup(draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' }, required: true }]));
    expect(screen.getByRole('heading', { name: 'Förderantrag' })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Titel')).toBeInTheDocument();
  });

  it('adds a question through the type menu', async () => {
    const { fixture } = await setup(draft([]));
    expect(screen.getByText('Noch keine Fragen. Füge unten die erste hinzu.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '+ Frage hinzufügen' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Langtext' }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.fields()).toHaveLength(1);
    expect(c.fields()[0].type).toBe('textarea');
  });

  it('saves a normalized form version with the description', async () => {
    const { createFormVersion } = await setup(
      draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }], { de: 'Hallo', en: '' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(createFormVersion).toHaveBeenCalledTimes(1);
    const [typeId, fields, description] = createFormVersion.mock.calls[0];
    expect(typeId).toBe('f1');
    expect(fields).toEqual([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]);
    expect(description).toEqual({ de: 'Hallo', en: '' });
  });

  it('writes the question label back into the model (regression: label stayed empty)', async () => {
    const { fixture } = await setup(draft([{ key: 'sum', type: 'text', label: { de: '', en: '' } }]));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.fieldErrors()[0]).toContain('label (de) is required');
    await userEvent.type(screen.getByLabelText('Bezeichnung (DE)'), 'Summe');
    expect(c.fields()[0].label.de).toBe('Summe');
    expect(c.fieldErrors()[0]).not.toContain('label (de) is required');
  });

  it('switches to preview mode', async () => {
    await setup(draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' }, required: true }]));
    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    const preview = screen.getByText('Titel', { selector: '.fe__pv-label' });
    expect(within(preview).getByText('*')).toBeInTheDocument();
  });
});
