import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@shared/ui';
import type { FormFieldDef, I18nMap } from '@core/api/models';
import { AdminApiService } from '../admin-api.service';
import type { ApplicationTypeFull, FormDraft } from '../admin.models';
import { groupsFromFields, groupsToFields } from '../form-field.util';
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Api = Record<string, any>;

async function setup(
  d: FormDraft,
  opts: { api?: Api; type?: ApplicationTypeFull | null; paramId?: string | null } = {},
) {
  const createFormVersion = jest.fn(
    (_id: string, _fields: FormFieldDef[], _description: I18nMap) => of({ id: 'fv2' }),
  );
  const updateApplicationType = jest.fn((_id: string, _body: Record<string, unknown>) =>
    of(void 0),
  );
  const setFormActive = jest.fn((_id: string, active: boolean) =>
    of({ ...d, active, formVersionId: 'fv1' }),
  );
  const types = opts.type === undefined ? [TYPE] : opts.type === null ? [] : [opts.type];
  const api: Api = {
    listApplicationTypesFull: jest.fn(() => of(types)),
    getFormDraft: jest.fn(() => of(d)),
    createFormVersion,
    updateApplicationType,
    setFormActive,
    listConfigRevisions: jest.fn(() => of([])),
    ...opts.api,
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const id = opts.paramId === undefined ? 'f1' : opts.paramId;
  const view = await render(FormEditorComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: of(convertToParamMap(id === null ? {} : { id })) },
      },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, c, api, createFormVersion, updateApplicationType, setFormActive, toast };
}

describe('FormEditorComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the draft title and questions', async () => {
    await setup(draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' }, required: true }]));
    expect(screen.getByRole('heading', { name: 'Förderantrag' })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Titel')).toBeInTheDocument();
  });

  it('loads a markerless form as a single untitled group', async () => {
    const { fixture } = await setup(
      draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.groups()).toHaveLength(1);
    expect(c.groups()[0].titleDe).toBe('');
    expect(c.groups()[0].fields).toHaveLength(1);
  });

  it('splits a form with section markers into titled groups', async () => {
    const { fixture } = await setup(
      draft([
        { key: 'q1', type: 'text', label: { de: 'A', en: '' } },
        { key: 'section_1', type: 'section', label: { de: 'Zweiter Schritt', en: 'Second' } },
        { key: 'q2', type: 'text', label: { de: 'B', en: '' } },
      ]),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.groups()).toHaveLength(2);
    expect(c.groups()[0].titleDe).toBe('');
    expect(c.groups()[1].titleDe).toBe('Zweiter Schritt');
    expect(c.groups()[1].fields[0].key).toBe('q2');
  });

  it('adds a question through a group type menu', async () => {
    const { fixture } = await setup(draft([]));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // Empty form loads as a single empty group.
    expect(c.groups()).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: '+ Frage hinzufügen' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Langtext' }));
    expect(c.groups()[0].fields).toHaveLength(1);
    expect(c.groups()[0].fields[0].type).toBe('textarea');
  });

  it('adds and reorders groups', async () => {
    const { fixture } = await setup(
      draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addGroup();
    expect(c.groups()).toHaveLength(2);
    c.setGroupTitle(1, 'de', 'Schritt 2');
    c.moveGroup(1, -1);
    expect(c.groups()[0].titleDe).toBe('Schritt 2');
  });

  it('saves a normalized form version with the description', async () => {
    const { createFormVersion } = await setup(
      draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }], { de: 'Hallo', en: '' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(createFormVersion).toHaveBeenCalledTimes(1);
    const [typeId, fields, description] = createFormVersion.mock.calls[0];
    expect(typeId).toBe('f1');
    // Markerless single group → serializes back to exactly the original flat fields.
    expect(fields).toEqual([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]);
    expect(description).toEqual({ de: 'Hallo', en: '' });
  });

  it('serializes a multi-group form back to section markers', async () => {
    const { fixture, createFormVersion } = await setup(
      draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addGroup();
    c.setGroupTitle(1, 'de', 'Budget');
    c.addQuestion(1, 'currency');
    c.groups()[1].fields[0].key = 'amount';
    c.groups()[1].fields[0].label.de = 'Betrag';
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    const fields = createFormVersion.mock.calls[0][1];
    expect(fields).toEqual([
      { key: 'title', type: 'text', label: { de: 'Titel', en: '' } },
      { key: 'section_1', type: 'section', label: { de: 'Budget', en: '' } },
      { key: 'amount', type: 'currency', label: { de: 'Betrag', en: '' } },
    ]);
  });

  it('writes the question label back into the model (regression: label stayed empty)', async () => {
    const { fixture } = await setup(draft([{ key: 'sum', type: 'text', label: { de: '', en: '' } }]));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.errorsFor(0, 0)).toContain('label (de) is required');
    await userEvent.type(screen.getByLabelText('Bezeichnung (DE)'), 'Summe');
    expect(c.groups()[0].fields[0].label.de).toBe('Summe');
    expect(c.errorsFor(0, 0)).not.toContain('label (de) is required');
  });

  it('toggles "Mit Budget" and persists it on the type (#24/budget)', async () => {
    const { fixture, updateApplicationType } = await setup(
      draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' } }]),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.hasBudget()).toBe(false);
    c.hasBudget.set(true);
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(updateApplicationType).toHaveBeenCalledTimes(1);
    expect(updateApplicationType.mock.calls[0][1]).toEqual(
      expect.objectContaining({ hasBudget: true }),
    );
  });

  it('defaults the promoted field metric to a valid target (amount)', async () => {
    const { fixture } = await setup(
      draft([{ key: 'sum', type: 'currency', label: { de: 'Summe', en: '' } }]),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.onPromotedToggle({ gi: 0, qi: 0 }, true);
    expect(c.groups()[0].fields[0].promoteTarget).toBe('amount');
    c.onPromotedToggle({ gi: 0, qi: 0 }, false);
    expect(c.groups()[0].fields[0].promoteTarget).toBeUndefined();
  });

  it('switches to preview mode', async () => {
    await setup(draft([{ key: 'title', type: 'text', label: { de: 'Titel', en: '' }, required: true }]));
    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    const preview = screen.getByText('Titel', { selector: '.fe__pv-label' });
    expect(within(preview).getByText('*')).toBeInTheDocument();
  });
});

describe('FormEditorComponent — load branches', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('does not load when the route carries no id', async () => {
    const { api, c } = await setup(draft([]), { paramId: null });
    expect(api['listApplicationTypesFull']).not.toHaveBeenCalled();
    expect(api['getFormDraft']).not.toHaveBeenCalled();
    expect(c.typeId()).toBe('');
  });

  it('ignores a missing type (no matching id) and leaves defaults', async () => {
    const { c } = await setup(draft([{ key: 'title', type: 'text', label: { de: 'T', en: '' } }]), {
      type: null,
    });
    // No matching type -> title stays the loaded-draft default (empty), not patched.
    expect(c.title()).toEqual({ de: '', en: '' });
    expect(c.hasBudget()).toBe(false);
  });

  it('loads comparison-offer rule fields from the type and falls back when absent', async () => {
    const withCmp: ApplicationTypeFull = {
      ...TYPE,
      hasBudget: true,
      comparisonOffers: { required: true, minCount: 3, thresholdAmount: '100', as: 'both' },
    };
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]), {
      type: withCmp,
    });
    expect(c.hasBudget()).toBe(true);
    expect(c.cmpRequired()).toBe(true);
    expect(c.cmpMinCount()).toBe(3);
  });

  it('survives a failing type fetch (error branch on listApplicationTypesFull)', async () => {
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]), {
      api: { listApplicationTypesFull: jest.fn(() => throwError(() => new Error('boom'))) },
    });
    // Draft still loads -> not loading, groups present.
    expect(c.loading()).toBe(false);
    expect(c.groups()).toHaveLength(1);
  });

  it('clears the loading flag when the draft fetch fails', async () => {
    const { c } = await setup(draft([]), {
      api: { getFormDraft: jest.fn(() => throwError(() => new Error('boom'))) },
    });
    expect(c.loading()).toBe(false);
  });

  it('defaults description/active/version when the draft omits them', async () => {
    const { c } = await setup({
      applicationTypeId: 'f1',
      fields: [{ key: 't', type: 'text', label: { de: 'T', en: '' } }],
    });
    expect(c.description()).toEqual({ de: '', en: '' });
    expect(c.active()).toBe(false);
    expect(c.hasVersion()).toBe(false);
    expect(c.formVersion()).toBeNull();
  });
});

describe('FormEditorComponent — activation toggle', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('activates an inactive form and toasts success', async () => {
    const { c, setFormActive, toast } = await setup({
      applicationTypeId: 'f1',
      formVersionId: 'fv1',
      version: 1,
      active: false,
      fields: [{ key: 't', type: 'text', label: { de: 'T', en: '' } }],
    });
    c.toggleActive();
    expect(setFormActive).toHaveBeenCalledWith('f1', true);
    expect(c.active()).toBe(true);
    expect(c.hasVersion()).toBe(true);
    expect(c.togglingActive()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('deactivates an active form', async () => {
    const { c, setFormActive } = await setup({
      applicationTypeId: 'f1',
      formVersionId: 'fv1',
      version: 1,
      active: true,
      fields: [{ key: 't', type: 'text', label: { de: 'T', en: '' } }],
    });
    c.toggleActive();
    expect(setFormActive).toHaveBeenCalledWith('f1', false);
    expect(c.active()).toBe(false);
  });

  it('reports an error and resets the toggling flag on failure', async () => {
    const { c, toast } = await setup(
      {
        applicationTypeId: 'f1',
        formVersionId: 'fv1',
        active: false,
        fields: [{ key: 't', type: 'text', label: { de: 'T', en: '' } }],
      },
      { api: { setFormActive: jest.fn(() => throwError(() => new Error('x'))) } },
    );
    c.toggleActive();
    expect(c.togglingActive()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });

  it('no-ops when there is no id', async () => {
    const { c, setFormActive } = await setup(draft([]), { paramId: null });
    c.toggleActive();
    expect(setFormActive).not.toHaveBeenCalled();
  });

  it('no-ops while a toggle is already in flight', async () => {
    const { c, setFormActive } = await setup({
      applicationTypeId: 'f1',
      formVersionId: 'fv1',
      active: false,
      fields: [{ key: 't', type: 'text', label: { de: 'T', en: '' } }],
    });
    c.togglingActive.set(true);
    c.toggleActive();
    expect(setFormActive).not.toHaveBeenCalled();
  });
});

describe('FormEditorComponent — title/description/label helpers', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('sets title and description per language', async () => {
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]));
    c.setTitle('en', 'English');
    expect(c.title()).toEqual({ de: 'Förderantrag', en: 'English' });
    c.setDescription('de', 'Hallo');
    c.setDescription('en', 'Hi');
    expect(c.description()).toEqual({ de: 'Hallo', en: 'Hi' });
  });

  it('resolves an i18n map and returns empty for undefined', async () => {
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]));
    expect(c.resolved({ de: 'D', en: 'E' })).toBe('D');
    expect(c.resolved(undefined)).toBe('');
  });

  it('returns the localized type label', async () => {
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]));
    expect(typeof c.typeLabel('text')).toBe('string');
    expect(c.typeLabel('text').length).toBeGreaterThan(0);
  });
});

describe('FormEditorComponent — group & question mutations', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  // jsdom (jest) has no structuredClone; the component relies on the browser global.
  const g = globalThis as unknown as { structuredClone?: <T>(v: T) => T };
  const savedClone = g.structuredClone;
  beforeAll(() => {
    g.structuredClone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
  });
  afterAll(() => {
    g.structuredClone = savedClone;
  });

  function base() {
    return setup(
      draft([
        { key: 'q1', type: 'text', label: { de: 'A', en: '' } },
        { key: 'q2', type: 'text', label: { de: 'B', en: '' } },
      ]),
    );
  }

  it('removes a group', async () => {
    const { c } = await base();
    c.addGroup();
    expect(c.groups()).toHaveLength(2);
    c.removeGroup(1);
    expect(c.groups()).toHaveLength(1);
  });

  it('reorder is a no-op at the edges and when from===to', async () => {
    const { c } = await base();
    c.addGroup();
    c.setGroupTitle(0, 'de', 'First');
    c.moveGroup(0, -1); // to=-1 -> out of bounds
    expect(c.groups()).toHaveLength(2);
    expect(c.groups()[0].titleDe).toBe('First');
    c.moveGroup(1, 1); // to=2 -> out of bounds
    expect(c.groups()).toHaveLength(2);
    // from===to via the private reorderGroup directly (covers the equal-index guard)
    c.reorderGroup(0, 0);
    expect(c.groups()[0].titleDe).toBe('First');
  });

  it('removes a question from a group', async () => {
    const { c } = await base();
    c.removeQuestion({ gi: 0, qi: 0 });
    expect(c.groups()[0].fields).toHaveLength(1);
    expect(c.groups()[0].fields[0].key).toBe('q2');
  });

  it('duplicates a question, suffixing _copy (and handling an empty key)', async () => {
    const { c } = await base();
    c.duplicateQuestion({ gi: 0, qi: 0 });
    expect(c.groups()[0].fields).toHaveLength(3);
    expect(c.groups()[0].fields[1].key).toBe('q1_copy');
    // empty key -> stays empty
    c.groups()[0].fields[0].key = '';
    c.touch();
    c.duplicateQuestion({ gi: 0, qi: 0 });
    expect(c.groups()[0].fields[1].key).toBe('');
  });

  it('moves a question within its group', async () => {
    const { c } = await base();
    c.moveQuestion({ gi: 0, qi: 0 }, 1);
    expect(c.groups()[0].fields.map((f: FormFieldDef) => f.key)).toEqual(['q2', 'q1']);
  });

  it('moveQuestion is a no-op for a non-existent group', async () => {
    const { c } = await base();
    c.moveQuestion({ gi: 5, qi: 0 }, 1);
    expect(c.groups()[0].fields).toHaveLength(2);
  });

  it('passes a boundary question into the next/previous group', async () => {
    const { c } = await base();
    c.addGroup(); // group 1
    // push last question of group 0 forward into group 1
    c.moveQuestion({ gi: 0, qi: 1 }, 1);
    expect(c.groups()[0].fields).toHaveLength(1);
    expect(c.groups()[1].fields[0].key).toBe('q2');
    // pull it back into group 0 (dir -1 -> push onto the end of the previous group)
    c.moveQuestion({ gi: 1, qi: 0 }, -1);
    expect(c.groups()[1].fields).toHaveLength(0);
    expect(c.groups()[0].fields.map((f: FormFieldDef) => f.key)).toEqual(['q1', 'q2']);
  });

  it('moveQuestion at a boundary with no neighbour group does nothing', async () => {
    const { c } = await base();
    // first question, dir -1 -> ngi=-1 -> out of bounds
    c.moveQuestion({ gi: 0, qi: 0 }, -1);
    expect(c.groups()[0].fields.map((f: FormFieldDef) => f.key)).toEqual(['q1', 'q2']);
    // last question, dir +1 -> ngi beyond list
    c.moveQuestion({ gi: 0, qi: 1 }, 1);
    expect(c.groups()[0].fields.map((f: FormFieldDef) => f.key)).toEqual(['q1', 'q2']);
  });
});

describe('FormEditorComponent — type adaptation & options', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('adds options when switching to a choice type', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.onTypeChange({ gi: 0, qi: 0 }, 'select');
    expect(c.groups()[0].fields[0].type).toBe('select');
    expect(c.groups()[0].fields[0].options).toHaveLength(1);
  });

  it('keeps existing options when switching to multiselect', async () => {
    const { c } = await setup(
      draft([
        {
          key: 'q',
          type: 'select',
          label: { de: 'A', en: '' },
          options: [{ value: 'x', label: { de: 'X', en: '' } }],
        },
      ]),
    );
    c.onTypeChange({ gi: 0, qi: 0 }, 'multiselect');
    expect(c.groups()[0].fields[0].options).toHaveLength(1);
  });

  it('seeds a compute object for the computed type', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.onTypeChange({ gi: 0, qi: 0 }, 'computed');
    expect(c.groups()[0].fields[0].compute).toEqual({ var: '' });
  });

  it('strips promotion metadata for non-numeric types', async () => {
    const { c } = await setup(
      draft([
        {
          key: 'q',
          type: 'currency',
          label: { de: 'A', en: '' },
          isPromoted: true,
          promoteTarget: 'amount',
        },
      ]),
    );
    c.onTypeChange({ gi: 0, qi: 0 }, 'text');
    expect(c.groups()[0].fields[0].isPromoted).toBeUndefined();
    expect(c.groups()[0].fields[0].promoteTarget).toBeUndefined();
  });

  it('adds and removes options', async () => {
    const { c } = await setup(
      draft([
        {
          key: 'q',
          type: 'select',
          label: { de: 'A', en: '' },
          options: [{ value: 'x', label: { de: 'X', en: '' } }],
        },
      ]),
    );
    c.addOption({ gi: 0, qi: 0 });
    expect(c.groups()[0].fields[0].options).toHaveLength(2);
    c.removeOption({ gi: 0, qi: 0 }, 0);
    expect(c.groups()[0].fields[0].options).toHaveLength(1);
  });

  it('addOption falls back to an empty list when options is undefined', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.addOption({ gi: 0, qi: 0 });
    expect(c.groups()[0].fields[0].options).toHaveLength(1);
  });

  it('removeOption falls back gracefully when options is undefined', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.removeOption({ gi: 0, qi: 0 }, 0);
    expect(c.groups()[0].fields[0].options).toEqual([]);
  });
});

describe('FormEditorComponent — expansion, type predicates', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('toggles and reports the expanded state per question', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    expect(c.isExpanded({ gi: 0, qi: 0 })).toBe(false);
    c.toggleExpanded({ gi: 0, qi: 0 });
    expect(c.isExpanded({ gi: 0, qi: 0 })).toBe(true);
    c.toggleExpanded({ gi: 0, qi: 0 });
    expect(c.isExpanded({ gi: 0, qi: 0 })).toBe(false);
  });

  it('classifies field types via the predicates', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    expect(c.isChoice('select')).toBe(true);
    expect(c.isChoice('multiselect')).toBe(true);
    expect(c.isChoice('text')).toBe(false);
    expect(c.isPositions('positions')).toBe(true);
    expect(c.isPositions('text')).toBe(false);
    expect(c.isNumeric('number')).toBe(true);
    expect(c.isNumeric('currency')).toBe(true);
    expect(c.isNumeric('text')).toBe(false);
    expect(c.isText('text')).toBe(true);
    expect(c.isText('textarea')).toBe(true);
    expect(c.isText('number')).toBe(false);
  });
});

describe('FormEditorComponent — drag reorder', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('reorders groups by drag start + drop', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.addGroup();
    c.setGroupTitle(1, 'de', 'Second');
    c.onDragStart(1);
    c.onDrop(0);
    expect(c.groups()[0].titleDe).toBe('Second');
  });

  it('onDragOver prevents default', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    const ev = { preventDefault: jest.fn() } as unknown as DragEvent;
    c.onDragOver(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
  });

  it('onDrop is a no-op when dropping onto the same group or with no active drag', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.addGroup();
    c.setGroupTitle(1, 'de', 'Second');
    // no active drag
    c.onDrop(0);
    expect(c.groups()[1].titleDe).toBe('Second');
    // drop onto same group
    c.onDragStart(1);
    c.onDrop(1);
    expect(c.groups()[1].titleDe).toBe('Second');
  });
});

describe('FormEditorComponent — validation setters & JsonLogic', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('sets and clears numeric validation values', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'number', label: { de: 'A', en: '' } }]));
    c.setVal({ gi: 0, qi: 0 }, 'min', '5');
    expect(c.groups()[0].fields[0].validation).toEqual({ min: 5 });
    c.setVal({ gi: 0, qi: 0 }, 'min', '');
    expect(c.groups()[0].fields[0].validation).toEqual({});
  });

  it('sets a string pattern (non-numeric key)', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.setVal({ gi: 0, qi: 0 }, 'pattern', '^a+$');
    expect(c.groups()[0].fields[0].validation).toEqual({ pattern: '^a+$' });
  });

  it('parses valid JsonLogic into the field and reflects the raw input', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.onLogicInput({ gi: 0, qi: 0 }, 'visibleIf', '{"var":"x"}');
    expect(c.groups()[0].fields[0].visibleIf).toEqual({ var: 'x' });
    expect(c.logicRaw(0, 0, 'visibleIf')).toBe('{"var":"x"}');
  });

  it('keeps the field unchanged on invalid JSON but stores the raw text', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    c.onLogicInput({ gi: 0, qi: 0 }, 'compute', '{ not json');
    expect(c.groups()[0].fields[0].compute).toBeUndefined();
    expect(c.logicRaw(0, 0, 'compute')).toBe('{ not json');
  });

  it('removes the logic key when cleared to empty', async () => {
    const { c } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' }, visibleIf: { var: 'x' } }]),
    );
    c.onLogicInput({ gi: 0, qi: 0 }, 'visibleIf', '   ');
    // The field key is dropped (trimmed empty) but the raw text is preserved verbatim.
    expect(c.groups()[0].fields[0].visibleIf).toBeUndefined();
    expect(c.logicRaw(0, 0, 'visibleIf')).toBe('   ');
  });

  it('logicRaw stringifies the current value when no raw edit exists', async () => {
    const { c } = await setup(draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]));
    expect(c.logicRaw(0, 0, 'compute', { var: 'y' })).toBe('{"var":"y"}');
    expect(c.logicRaw(0, 0, 'compute')).toBe('');
  });
});

describe('FormEditorComponent — save branches', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('refuses to save an invalid form and toasts the error', async () => {
    const { c, createFormVersion, toast } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: '', en: '' } }]),
    );
    expect(c.formValid()).toBe(false);
    c.save();
    expect(createFormVersion).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it('no-ops while already saving', async () => {
    const { c, createFormVersion } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]),
    );
    c.saving.set(true);
    c.save();
    expect(createFormVersion).not.toHaveBeenCalled();
  });

  it('patches the type then creates a version when the type changed', async () => {
    const { c, updateApplicationType, createFormVersion } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]),
    );
    c.cmpRequired.set(true);
    c.save();
    expect(updateApplicationType).toHaveBeenCalledTimes(1);
    expect(updateApplicationType.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        comparisonOffers: expect.objectContaining({ required: true, minCount: 2 }),
      }),
    );
    expect(createFormVersion).toHaveBeenCalledTimes(1);
    expect(c.active()).toBe(true);
    expect(c.hasVersion()).toBe(true);
    expect(c.saving()).toBe(false);
  });

  it('detects a minCount change as a type change', async () => {
    const { c, updateApplicationType } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]),
    );
    c.cmpMinCount.set(5);
    c.save();
    expect(updateApplicationType).toHaveBeenCalledTimes(1);
  });

  it('skips the type patch when nothing on the type changed', async () => {
    const { c, updateApplicationType, createFormVersion } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]),
    );
    c.save();
    expect(updateApplicationType).not.toHaveBeenCalled();
    expect(createFormVersion).toHaveBeenCalledTimes(1);
  });

  it('toasts a save failure and resets the saving flag', async () => {
    const { c, toast } = await setup(
      draft([{ key: 'q', type: 'text', label: { de: 'A', en: '' } }]),
      { api: { createFormVersion: jest.fn(() => throwError(() => new Error('x'))) } },
    );
    c.save();
    expect(c.saving()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });
});

describe('FormEditorComponent — nullish/branch edges', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('falls back to empty strings when the type name lacks de/en keys', async () => {
    const noNames = { id: 'f1', name: {}, hasBudget: false } as unknown as ApplicationTypeFull;
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]), {
      type: noNames,
    });
    expect(c.title()).toEqual({ de: '', en: '' });
  });

  it('treats a returned draft without an active flag as inactive on toggle', async () => {
    const { c } = await setup(
      {
        applicationTypeId: 'f1',
        formVersionId: 'fv1',
        active: false,
        fields: [{ key: 't', type: 'text', label: { de: 'T', en: '' } }],
      },
      // setFormActive returns a draft missing `active` -> `?? false`.
      { api: { setFormActive: jest.fn(() => of({ applicationTypeId: 'f1', formVersionId: 'fv1', fields: [] })) } },
    );
    c.toggleActive();
    expect(c.active()).toBe(false);
    expect(c.hasVersion()).toBe(true);
  });

  it('sets the EN group title (else-branch of the de/en ternary)', async () => {
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]));
    c.setGroupTitle(0, 'en', 'Step EN');
    expect(c.groups()[0].titleEn).toBe('Step EN');
    expect(c.groups()[0].titleDe).toBe('');
  });

  it('only mutates the addressed question, leaving siblings untouched', async () => {
    const { c } = await setup(
      draft([
        { key: 'a', type: 'text', label: { de: 'A', en: '' } },
        { key: 'b', type: 'text', label: { de: 'B', en: '' } },
      ]),
    );
    c.addOption({ gi: 0, qi: 1 }); // mutate the 2nd field only
    expect(c.groups()[0].fields[0].options).toBeUndefined();
    expect(c.groups()[0].fields[1].options).toHaveLength(1);
  });

  it('errorsFor returns an empty array for an unknown position', async () => {
    const { c } = await setup(draft([{ key: 't', type: 'text', label: { de: 'T', en: '' } }]));
    expect(c.errorsFor(9, 9)).toEqual([]);
  });
});

describe('group serialize/deserialize round-trip', () => {
  it('preserves a markerless flat form exactly', () => {
    const flat: FormFieldDef[] = [
      { key: 'title', type: 'text', label: { de: 'Titel', en: '' } },
      { key: 'amount', type: 'currency', label: { de: 'Betrag', en: '' } },
    ];
    expect(groupsToFields(groupsFromFields(flat))).toEqual(flat);
  });

  it('preserves a multi-section flat form (section keys re-numbered to section_N)', () => {
    const flat: FormFieldDef[] = [
      { key: 'title', type: 'text', label: { de: 'Titel', en: '' } },
      { key: 'section_1', type: 'section', label: { de: 'Budget', en: 'Budget' } },
      { key: 'amount', type: 'currency', label: { de: 'Betrag', en: '' } },
    ];
    expect(groupsToFields(groupsFromFields(flat))).toEqual(flat);
  });

  it('keeps a leading section marker as the first group title', () => {
    const flat: FormFieldDef[] = [
      { key: 'section_1', type: 'section', label: { de: 'Erster', en: 'First' } },
      { key: 'q1', type: 'text', label: { de: 'A', en: '' } },
    ];
    const groups = groupsFromFields(flat);
    expect(groups).toHaveLength(1);
    expect(groups[0].titleDe).toBe('Erster');
    expect(groupsToFields(groups)).toEqual(flat);
  });
});
