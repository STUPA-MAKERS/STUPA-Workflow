import { toastWith } from '../../../../testing/load-error';
import { Router, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { ApplicationTypeCreateBody, ApplicationTypeFull } from '../admin.models';
import { FormsListComponent } from './forms-list.component';

function type(id: string, de: string): ApplicationTypeFull {
  return { id, name: { de, en: de }, gremiumId: 'g1', hasBudget: false, activeFormVersionId: null };
}

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Api = Record<string, any>;

/**
 * The page opens on form.configure, but create and delete each need their own admin key. The
 * default grants both, so the dialog tests reach the button.
 */
async function setup(opts: { api?: Api; perms?: string[] } = {}) {
  const createApplicationType = jest.fn((b: ApplicationTypeCreateBody) =>
    of({ id: 'f-new', name: b.name, gremiumId: null, hasBudget: false, activeFormVersionId: null }),
  );
  const deleteApplicationType = jest.fn(() => of(void 0));
  const api: Api = {
    listApplicationTypesFull: jest.fn(() => of([type('f1', 'Förderantrag')])),
    listGremienOptions: jest.fn(() => of([{ id: 'g1', name: 'StuPa' }])),
    listApplicationTypeGroups: jest.fn(() => of([])),
    createApplicationType,
    deleteApplicationType,
    ...opts.api,
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(FormsListComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      {
        provide: AuthService,
        useValue: fakeAuth(opts.perms ?? ['admin.types', 'admin.types_delete']),
      },
      { provide: ToastService, useFactory: () => toastWith(toast) },
      provideRouter([{ path: 'admin/forms/:id', children: [] }]),
    ],
  });
  const router = view.fixture.debugElement.injector.get(Router);
  jest.spyOn(router, 'navigate').mockResolvedValue(true);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, c, api, router, toast, createApplicationType, deleteApplicationType };
}

const GROUPS = [
  { id: 'gA', name: { de: 'Projektanträge' }, text: { de: 'Mit **Kosten**' }, position: 0 },
  { id: 'gB', name: { de: 'Spezielle' }, text: {}, position: 1 },
];

function grouped(): ApplicationTypeFull[] {
  return [
    { ...type('f1', 'VSM'), groupId: 'gA', position: 0 },
    { ...type('f2', 'QSM'), groupId: 'gA', position: 1 },
    { ...type('f3', 'Sonstiges'), groupId: null, position: 0 },
  ];
}

async function setupGroups(extra: Api = {}, perms?: string[]) {
  return setup({
    api: {
      listApplicationTypesFull: jest.fn(() => of(grouped())),
      listApplicationTypeGroups: jest.fn(() => of(GROUPS)),
      ...extra,
    },
    perms,
  });
}

describe('FormsListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  describe('groups of Antragsarten (specs 001180, 001183)', () => {
    it('shows each group with its text and the types without a group last', async () => {
      await setupGroups();
      const first = screen.getByRole('group', { name: 'Projektanträge' });
      expect(first.querySelector('strong')?.textContent).toBe('Kosten');
      expect(screen.getByRole('group', { name: 'Spezielle' })).toHaveTextContent(
        'Noch keine Antragsart in dieser Gruppe',
      );
      expect(screen.getByRole('group', { name: 'Weitere Anträge' })).toHaveTextContent('Sonstiges');
    });

    it('shows one table without a heading when no group exists', async () => {
      const { c } = await setup();
      expect(c.blocks()).toEqual([expect.objectContaining({ group: null })]);
      expect(c.blockHeading(c.blocks()[0])).toBe('');
    });

    it('creates a group from the dialog', async () => {
      const createApplicationTypeGroup = jest.fn(() =>
        of({ id: 'gC', name: { de: 'Neu' }, text: { de: 'T' }, position: 2 }),
      );
      const { c, toast } = await setupGroups({ createApplicationTypeGroup });
      await userEvent.click(screen.getByRole('button', { name: 'Gruppe anlegen' }));
      await userEvent.type(screen.getByLabelText(/Name \(DE\)/), 'Neu');
      c.patchGroup('textDe', ' T ');
      c.saveGroup(new Event('submit'));
      expect(createApplicationTypeGroup).toHaveBeenCalledWith({ name: { de: 'Neu' }, text: { de: 'T' } });
      expect(c.groups().map((g: { id: string }) => g.id)).toEqual(['gA', 'gB', 'gC']);
      expect(toast.success).toHaveBeenCalled();
      expect(c.groupDialog()).toBeNull();
    });

    it('edits a group with both languages and reports a failed save', async () => {
      const updateApplicationTypeGroup = jest
        .fn()
        .mockReturnValueOnce(of({ ...GROUPS[0], name: { de: 'P', en: 'E' } }))
        .mockReturnValueOnce(throwError(() => new Error('x')));
      const { c, toast } = await setupGroups({ updateApplicationTypeGroup });
      c.groupAction(GROUPS[0], { id: 'edit', label: '' });
      expect(c.groupForm()).toEqual({ nameDe: 'Projektanträge', nameEn: '', textDe: 'Mit **Kosten**', textEn: '' });
      c.patchGroup('nameDe', 'P');
      c.patchGroup('nameEn', 'E');
      c.patchGroup('textEn', 'Text');
      c.saveGroup(new Event('submit'));
      expect(updateApplicationTypeGroup).toHaveBeenCalledWith('gA', {
        name: { de: 'P', en: 'E' },
        text: { de: 'Mit **Kosten**', en: 'Text' },
      });
      expect(c.groups()[0].name).toEqual({ de: 'P', en: 'E' });
      c.groupAction(GROUPS[1], { id: 'edit', label: '' });
      c.saveGroup(new Event('submit'));
      expect(toast.error).toHaveBeenCalled();
      expect(c.saving()).toBe(false);
    });

    it('saves no group without a German name', async () => {
      const createApplicationTypeGroup = jest.fn();
      const { c } = await setupGroups({ createApplicationTypeGroup });
      c.openGroupCreate();
      c.saveGroup(new Event('submit'));
      expect(createApplicationTypeGroup).not.toHaveBeenCalled();
    });

    it('deletes a group and loads the list again', async () => {
      const deleteApplicationTypeGroup = jest
        .fn()
        .mockReturnValueOnce(of(void 0))
        .mockReturnValueOnce(throwError(() => new Error('x')));
      const { c, api, toast } = await setupGroups({ deleteApplicationTypeGroup });
      c.groupAction(GROUPS[1], { id: 'delete', label: '' });
      expect(c.confirmGroupDelete()).toBe(GROUPS[1]);
      c.deleteGroup();
      expect(deleteApplicationTypeGroup).toHaveBeenCalledWith('gB');
      expect(api['listApplicationTypeGroups']).toHaveBeenCalledTimes(2);
      c.groupAction(GROUPS[0], { id: 'delete', label: '' });
      c.deleteGroup();
      expect(toast.error).toHaveBeenCalled();
      expect(c.deleting()).toBe(false);
    });

    it('moves groups and types with the arrows', async () => {
      const moveApplicationTypeGroup = jest
        .fn()
        .mockReturnValueOnce(of([GROUPS[1], GROUPS[0]]))
        .mockReturnValueOnce(throwError(() => new Error('x')));
      const moveApplicationType = jest
        .fn()
        .mockReturnValueOnce(of([...grouped()].reverse()))
        .mockReturnValueOnce(throwError(() => new Error('x')));
      const { c, toast } = await setupGroups({ moveApplicationTypeGroup, moveApplicationType });
      await userEvent.click(screen.getByRole('button', { name: 'Nach unten: Projektanträge' }));
      expect(moveApplicationTypeGroup).toHaveBeenCalledWith('gA', 1);
      expect(c.groups()[0].id).toBe('gB');
      const menu = c.rowMenus().get('f2')[0].items;
      expect(menu.map((i: { id: string }) => i.id)).toEqual(['up', 'down', 'group']);
      expect(menu[1].disabledReason).toBe('Steht schon am Rand der Gruppe');
      expect(c.rowMenus().get('f1')[0].items[0].disabledReason).toBe('Steht schon am Rand der Gruppe');
      c.typeAction(grouped()[1], { id: 'up', label: '' });
      expect(moveApplicationType).toHaveBeenCalledWith('f2', -1);
      expect(c.types()[0].id).toBe('f3');
      c.moveGroup(GROUPS[0], -1);
      c.typeAction(grouped()[0], { id: 'down', label: '' });
      expect(toast.error).toHaveBeenCalledTimes(2);
    });

    it('changes the group of a type', async () => {
      const updateApplicationType = jest
        .fn()
        .mockReturnValueOnce(of(void 0))
        .mockReturnValueOnce(throwError(() => new Error('x')));
      const { c, toast } = await setupGroups({ updateApplicationType });
      const [vsm, , loose] = grouped();
      c.typeAction(vsm, { id: 'group', label: '' });
      expect(c.regroupTo()).toBe('gA');
      expect(c.groupOptions().map((o: { value: string }) => o.value)).toEqual(['', 'gA', 'gB']);
      c.saveRegroup();
      expect(updateApplicationType).not.toHaveBeenCalled();
      expect(c.regroup()).toBeNull();
      c.typeAction(vsm, { id: 'group', label: '' });
      c.regroupTo.set('');
      c.saveRegroup();
      expect(updateApplicationType).toHaveBeenCalledWith('f1', { groupId: null });
      expect(toast.success).toHaveBeenCalled();
      c.typeAction(loose, { id: 'group', label: '' });
      expect(c.regroupTo()).toBe('');
      c.regroupTo.set('gB');
      c.saveRegroup();
      expect(updateApplicationType).toHaveBeenLastCalledWith('f3', { groupId: 'gB' });
      expect(toast.error).toHaveBeenCalled();
      c.regroup.set(null);
      c.saveRegroup();
      expect(updateApplicationType).toHaveBeenCalledTimes(2);
    });

    it('offers no group actions without admin.types', async () => {
      const { c } = await setupGroups({}, ['admin.types_delete']);
      expect(screen.queryByRole('button', { name: 'Gruppe anlegen' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Nach oben/ })).not.toBeInTheDocument();
      expect(c.rowMenus().get('f1')).toEqual([{ items: [expect.objectContaining({ id: 'delete' })] }]);
      c.openGroupCreate();
      expect(c.groupDialog()).toBeNull();
    });
  });

  it('lists application types', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Förderantrag' })).toBeInTheDocument();
  });

  it('opens the editor on a click on the row', async () => {
    const { router } = await setup();
    await userEvent.click(screen.getByText('StuPa'));
    expect(router.navigate).toHaveBeenCalledWith(['/admin/forms', 'f1']);
  });

  it('creates a type via the dialog with an auto key', async () => {
    const { createApplicationType } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Formular anlegen' }));

    const nameDe = screen.getByLabelText(/Titel \(DE\)/);
    await userEvent.type(nameDe, 'Härtefall Antrag');

    await userEvent.click(screen.getByRole('button', { name: 'Anlegen' }));

    expect(createApplicationType).toHaveBeenCalledTimes(1);
    const body = createApplicationType.mock.calls[0][0];
    expect(body.key).toBe('haertefall-antrag');
    expect(body.name).toEqual({ de: 'Härtefall Antrag', en: '' });
  });

  it('navigates to the editor of the freshly created type', async () => {
    const { c, router } = await setup();
    c.patch('nameDe', 'Neuer Antrag');
    c.submit(new Event('submit'));
    expect(router.navigate).toHaveBeenCalledWith(['/admin/forms', 'f-new']);
  });
});

describe('FormsListComponent — loading & errors', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('surfaces a load error when the type fetch fails', async () => {
    const { c } = await setup({
      api: { listApplicationTypesFull: jest.fn(() => throwError(() => new Error('x'))) },
    });
    expect(c.loadError()).toBe(true);
    expect(c.loading()).toBe(false);
  });

  /** Without a mapping the cell shows the dash fallback. */
  it('falls back to an empty gremien list when that fetch fails', async () => {
    const { c } = await setup({
      api: { listGremienOptions: jest.fn(() => throwError(() => new Error('x'))) },
    });
    expect(c.gremiumName('g1')).toBe('—');
  });

  it('clears the loading flag after a successful load', async () => {
    const { c } = await setup();
    expect(c.loading()).toBe(false);
    expect(c.loadError()).toBe(false);
    expect(c.types()).toHaveLength(1);
  });
});

describe('FormsListComponent — display helpers', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('resolves the type name and falls back to "untitled" when empty', async () => {
    const { c } = await setup();
    expect(c.name(type('f1', 'Förderantrag'))).toBe('Förderantrag');
    expect(c.name({ id: 'f2', name: { de: '', en: '' }, hasBudget: false })).toBe(
      'Unbenanntes Formular',
    );
  });

  it('resolves a gremium name and dashes unknown / null ids', async () => {
    const { c } = await setup();
    expect(c.gremiumName('g1')).toBe('StuPa');
    expect(c.gremiumName('nope')).toBe('—');
    expect(c.gremiumName(null)).toBe('—');
    expect(c.gremiumName()).toBe('—');
  });

  it('builds a slug preview from the DE title (dash when empty)', async () => {
    const { c } = await setup();
    expect(c.keyPreview()).toBe('—');
    c.patch('nameDe', 'Mein Antrag');
    expect(c.keyPreview()).toBe('mein-antrag');
  });

  /** Spec 000761: an Antragsart cannot get a budget while Budget is off. */
  it('has no budget column and no "Mit Budget" while Budget is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['budget']));
    const { c } = await setup();
    localStorage.removeItem('ap.features.off');
    expect(c.columns().map((col: { key: string }) => col.key)).not.toContain('budget');
    expect(c.budgetOn).toBe(false);
  });

  it('exposes a row id and a column set', async () => {
    const { c } = await setup();
    expect(c.rowId(type('f9', 'X'))).toBe('f9');
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual([
      'name',
      'gremium',
      'budget',
      'status',
      'version',
      'actions',
    ]);
  });

  /** The name links to the editor, and each row menu names its type. */
  it('shows the budget, the status as text and the version of each type', async () => {
    const rows: ApplicationTypeFull[] = [
      { ...type('f1', 'Förderantrag'), hasBudget: true, activeFormVersionId: 'fv-1', activeFormVersion: 7 },
      type('f2', 'Raumantrag'),
    ];
    const { c } = await setup({ api: { listApplicationTypesFull: jest.fn(() => of(rows)) } });
    expect(screen.getByText('Mit Budget')).toBeInTheDocument();
    expect(screen.getByText('Ohne Budget')).toBeInTheDocument();
    expect(screen.getByText('Aktiv')).toBeInTheDocument();
    expect(screen.getByText('Entwurf')).toBeInTheDocument();
    expect(screen.getByText('v7')).toBeInTheDocument();
    expect(c.versionLabel(rows[1])).toBe('—');
    expect(screen.getByRole('link', { name: 'Förderantrag' })).toHaveAttribute('href', '/admin/forms/f1');
    expect(screen.getByRole('button', { name: 'Aktionen: Raumantrag' })).toBeInTheDocument();
  });
});

describe('FormsListComponent — create dialog state', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('opens the dialog with a blank form and closes it', async () => {
    const { c } = await setup();
    c.patch('nameDe', 'dirty');
    c.openCreate();
    expect(c.dialogOpen()).toBe(true);
    expect(c.form()).toEqual({ nameDe: '', nameEn: '', gremiumId: '', hasBudget: false });
    c.closeDialog();
    expect(c.dialogOpen()).toBe(false);
  });

  it('patches arbitrary form fields', async () => {
    const { c } = await setup();
    c.patch('hasBudget', true);
    c.patch('gremiumId', 'g1');
    expect(c.form()).toEqual(
      expect.objectContaining({ hasBudget: true, gremiumId: 'g1' }),
    );
  });

  it('refuses to submit a blank DE title', async () => {
    const { c, createApplicationType } = await setup();
    c.submit(new Event('submit'));
    expect(createApplicationType).not.toHaveBeenCalled();
  });

  it('refuses to submit while already saving', async () => {
    const { c, createApplicationType } = await setup();
    c.patch('nameDe', 'X');
    c.saving.set(true);
    c.submit(new Event('submit'));
    expect(createApplicationType).not.toHaveBeenCalled();
  });

  it('trims the EN title and passes the gremium id through', async () => {
    const { c, createApplicationType } = await setup();
    c.patch('nameDe', '  Antrag  ');
    c.patch('nameEn', '  Request  ');
    c.patch('gremiumId', 'g1');
    c.submit(new Event('submit'));
    const body = createApplicationType.mock.calls[0][0];
    expect(body.name).toEqual({ de: 'Antrag', en: 'Request' });
    expect(body.gremiumId).toBe('g1');
  });

  it('sends a null gremium id when none is chosen', async () => {
    const { c, createApplicationType } = await setup();
    c.patch('nameDe', 'Antrag');
    c.submit(new Event('submit'));
    expect(createApplicationType.mock.calls[0][0].gremiumId).toBeNull();
  });

  it('toasts and resets saving on a create failure', async () => {
    const { c, toast } = await setup({
      api: { createApplicationType: jest.fn(() => throwError(() => new Error('x'))) },
    });
    c.patch('nameDe', 'Antrag');
    c.submit(new Event('submit'));
    expect(c.saving()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });
});

describe('FormsListComponent — create gate', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('offers the create button with admin.types', async () => {
    const { c } = await setup({ perms: ['form.configure', 'admin.types'] });
    expect(c.canCreate()).toBe(true);
    expect(screen.getByRole('button', { name: 'Formular anlegen' })).toBeInTheDocument();
  });

  /**
   * The page itself opens on form.configure. The create posts an application type, which needs
   * admin.types, so the button must not be offered.
   */
  it('hides the create button for a form manager without admin.types', async () => {
    const { c } = await setup({ perms: ['form.configure'] });
    expect(c.canCreate()).toBe(false);
    expect(screen.queryByRole('button', { name: 'Formular anlegen' })).toBeNull();
  });

  it('keeps the dialog shut when openCreate is called without admin.types', async () => {
    const { c } = await setup({ perms: ['form.configure'] });
    c.openCreate();
    expect(c.dialogOpen()).toBe(false);
  });
});

describe('FormsListComponent — delete flow', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('allows the delete action with the permission', async () => {
    const { c } = await setup({ perms: ['admin.types_delete'] });
    expect(c.canDelete()).toBe(true);
  });

  it('hides the delete action without the permission', async () => {
    const { c } = await setup({ perms: [] });
    expect(c.canDelete()).toBe(false);
  });

  it('asks, names and cancels a deletion', async () => {
    const { c } = await setup();
    const t = type('f1', 'Förderantrag');
    expect(c.confirmDeleteName()).toBe('');
    c.askDelete(t);
    expect(c.confirmDelete()).toBe(t);
    expect(c.confirmDeleteName()).toBe('Förderantrag');
    c.cancelDelete();
    expect(c.confirmDelete()).toBeNull();
  });

  it('confirms a deletion, removes the row and toasts success', async () => {
    const { c, deleteApplicationType, toast } = await setup();
    const t = type('f1', 'Förderantrag');
    c.askDelete(t);
    c.confirmDeleteType();
    expect(deleteApplicationType).toHaveBeenCalledWith('f1');
    expect(c.types()).toHaveLength(0);
    expect(c.confirmDelete()).toBeNull();
    expect(c.deleting()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('confirmDeleteType is a no-op without a pending target', async () => {
    const { c, deleteApplicationType } = await setup();
    c.confirmDeleteType();
    expect(deleteApplicationType).not.toHaveBeenCalled();
  });

  it('confirmDeleteType is a no-op while a delete is in flight', async () => {
    const { c, deleteApplicationType } = await setup();
    c.askDelete(type('f1', 'Förderantrag'));
    c.deleting.set(true);
    c.confirmDeleteType();
    expect(deleteApplicationType).not.toHaveBeenCalled();
  });

  /** The row is kept. */
  it('toasts a delete failure and resets the deleting flag (e.g. 409)', async () => {
    const { c, toast } = await setup({
      api: { deleteApplicationType: jest.fn(() => throwError(() => new Error('409'))) },
    });
    c.askDelete(type('f1', 'Förderantrag'));
    c.confirmDeleteType();
    expect(c.deleting()).toBe(false);
    expect(c.types()).toHaveLength(1);
    expect(toast.error).toHaveBeenCalled();
  });
});
