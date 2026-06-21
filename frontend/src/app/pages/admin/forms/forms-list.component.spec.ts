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

async function setup(opts: { api?: Api; perms?: string[] } = {}) {
  const createApplicationType = jest.fn((b: ApplicationTypeCreateBody) =>
    of({ id: 'f-new', name: b.name, gremiumId: null, hasBudget: false, activeFormVersionId: null }),
  );
  const deleteApplicationType = jest.fn(() => of(void 0));
  const api: Api = {
    listApplicationTypesFull: jest.fn(() => of([type('f1', 'Förderantrag')])),
    listGremienOptions: jest.fn(() => of([{ id: 'g1', name: 'StuPa' }])),
    createApplicationType,
    deleteApplicationType,
    ...opts.api,
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(FormsListComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: fakeAuth(opts.perms ?? ['admin.types_delete']) },
      { provide: ToastService, useValue: toast },
      provideRouter([{ path: 'admin/forms/:id', children: [] }]),
    ],
  });
  const router = view.fixture.debugElement.injector.get(Router);
  jest.spyOn(router, 'navigate').mockResolvedValue(true);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, c, api, router, toast, createApplicationType, deleteApplicationType };
}

describe('FormsListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists application types', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Förderantrag' })).toBeInTheDocument();
  });

  it('creates a type via the dialog with an auto key', async () => {
    const { createApplicationType } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Formular anlegen' }));

    const nameDe = screen.getByLabelText(/Titel \(DE\)/);
    await userEvent.type(nameDe, 'Härtefall Antrag');

    const add = screen.getAllByRole('button', { name: 'Formular anlegen' });
    // the dialog footer add button is the enabled one
    await userEvent.click(add[add.length - 1]);

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

  it('falls back to an empty gremien list when that fetch fails', async () => {
    const { c } = await setup({
      api: { listGremienOptions: jest.fn(() => throwError(() => new Error('x'))) },
    });
    // No mapping -> dash fallback.
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

  it('exposes a row id and a column set', async () => {
    const { c } = await setup();
    expect(c.rowId(type('f9', 'X'))).toBe('f9');
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual([
      'name',
      'gremium',
      'budget',
      'status',
      'actions',
    ]);
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

  it('toasts a delete failure and resets the deleting flag (e.g. 409)', async () => {
    const { c, toast } = await setup({
      api: { deleteApplicationType: jest.fn(() => throwError(() => new Error('409'))) },
    });
    c.askDelete(type('f1', 'Förderantrag'));
    c.confirmDeleteType();
    expect(c.deleting()).toBe(false);
    expect(c.types()).toHaveLength(1); // row kept
    expect(toast.error).toHaveBeenCalled();
  });
});
