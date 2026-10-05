import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { GremiumRole } from '../admin.models';
import { GremiumRoleMatrixComponent } from './gremium-role-matrix.component';

const ALL = ['session.manage', 'vote.manage', 'vote.cast', 'protocol.write', 'protocol.finalize'];
const ROLES: GremiumRole[] = [
  {
    id: 'gr-p',
    gremiumId: 'g-1',
    key: 'protokoll',
    name: { de: 'Protokoll' },
    forced: false,
    permissions: ['vote.cast', 'protocol.write'],
  },
  {
    id: 'gr-m',
    gremiumId: 'g-1',
    key: 'member',
    name: { de: 'Mitglied' },
    forced: true,
    permissions: ['vote.cast'],
  },
  {
    id: 'gr-v',
    gremiumId: 'g-1',
    key: 'vorstand',
    name: { de: 'Vorstand' },
    forced: true,
    permissions: [...ALL],
  },
  { id: 'gr-x', gremiumId: 'g-1', key: 'kasse', name: {}, permissions: undefined },
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremiumRoles: jest.fn(() => of(clone(ROLES))),
    listRoleMappings: jest.fn(() =>
      of([
        { id: 'm1', gremiumId: 'g-1', gremiumRoleId: 'gr-v', oidcGroup: 'stupa-vorstand' },
        { id: 'm2', gremiumId: 'g-1', gremiumRoleId: 'gr-v', oidcGroup: 'stupa-sprecher' },
        { id: 'm3', gremiumId: 'g-2', gremiumRoleId: 'gr-o', oidcGroup: 'other' },
      ]),
    ),
    listMembershipMappings: jest.fn(() => of([{ id: 'mm', gremiumId: 'g-1', oidcGroup: 'stupa' }])),
    updateGremiumRole: jest.fn((id: string, b: Partial<GremiumRole>) =>
      of({ ...clone(ROLES.find((r) => r.id === id)!), ...b }),
    ),
    createGremiumRole: jest.fn((gid: string, b: Partial<GremiumRole>) =>
      of({ id: 'gr-new', gremiumId: gid, forced: false, ...b }),
    ),
    deleteGremiumRole: jest.fn(() => of(void 0)),
    ...over,
  };
}

async function setup(
  opts: {
    api?: ReturnType<typeof makeApi>;
    perms?: string[];
    inputs?: Record<string, unknown>;
  } = {},
) {
  const api = opts.api ?? makeApi();
  const perms = opts.perms ?? ['admin.gremium_roles', 'admin.group_mappings'];
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(GremiumRoleMatrixComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { can: (p: string) => perms.includes(p) } },
    ],
    componentInputs: { gremiumId: 'g-1', gremiumName: 'Studierendenparlament', ...opts.inputs },
  });
  // NgModel writes its value after a microtask.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const counts: number[] = [];
  view.fixture.componentInstance.countChange.subscribe((n) => counts.push(n));
  return { ...view, api, toast, counts };
}

const row = (name: string) =>
  screen
    .getByRole('rowheader', { name: new RegExp(`^${name}`) })
    .closest('[role=row]') as HTMLElement;

describe('GremiumRoleMatrixComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows one column per right of the catalogue, "Protokoll freigeben" included', async () => {
    await setup();
    const heads = screen
      .getAllByRole('columnheader')
      .map((h) => (h.querySelector('.rm__colLabel') ?? h).textContent?.trim());
    expect(heads).toEqual([
      'Rolle · OIDC-Gruppen',
      'Sitzungen verwalten',
      'Abstimmungen führen',
      'Abstimmen',
      'Protokoll führen',
      'Protokoll freigeben',
      'Aktionen',
    ]);
    const keys = [...document.querySelectorAll('.rm__colKey')].map((k) => k.textContent);
    expect(keys).toEqual(ALL);
  });

  it('sorts the forced roles first and shows the groups of each role', async () => {
    await setup();
    const names = screen
      .getAllByRole('rowheader')
      .map((h) => h.querySelector('.rm__name')?.textContent?.trim());
    expect(names).toEqual(['Vorstand', 'Mitglied', 'Kasse', 'Protokoll']);
    expect(within(row('Vorstand')).getByText('stupa-vorstand, stupa-sprecher')).toBeInTheDocument();
    expect(within(row('Vorstand')).getByText('Pflichtrolle')).toBeInTheDocument();
    // The member role names the groups that give the membership.
    expect(within(row('Mitglied')).getByText(/Mitgliedschaft über/)).toHaveTextContent(
      'Mitgliedschaft über stupa',
    );
    expect(within(row('Protokoll')).queryByText('Pflichtrolle')).toBeNull();
  });

  it('saves a box at once and puts it back when the save fails', async () => {
    const api = makeApi();
    const { toast } = await setup({ api });
    const box = screen.getByRole('checkbox', { name: 'Protokoll freigeben: Protokoll' });
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    expect(api.updateGremiumRole).toHaveBeenCalledWith('gr-p', {
      permissions: ['vote.cast', 'protocol.write', 'protocol.finalize'],
    });
    expect(screen.getByRole('checkbox', { name: 'Protokoll freigeben: Protokoll' })).toBeChecked();

    api.updateGremiumRole.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Abstimmen: Protokoll' }));
    expect(screen.getByRole('checkbox', { name: 'Abstimmen: Protokoll' })).toBeChecked();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('is read-only without admin.gremium_roles and hides the groups without admin.group_mappings', async () => {
    const api = makeApi();
    await setup({ api, perms: [] });
    for (const box of screen.getAllByRole('checkbox')) expect(box).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Gremium-Rolle hinzufügen/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Bearbeiten:/ })).toBeNull();
    expect(screen.queryByText('stupa-vorstand, stupa-sprecher')).toBeNull();
    expect(api.listRoleMappings).not.toHaveBeenCalled();
  });

  it('keeps the delete of a forced role disabled', async () => {
    await setup();
    expect(screen.getByRole('button', { name: 'Rolle löschen: Vorstand' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rolle löschen: Protokoll' })).toBeEnabled();
  });

  it('deletes an own role after the confirmation', async () => {
    const api = makeApi();
    const { counts } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: 'Rolle löschen: Protokoll' }));
    const dialog = screen.getByRole('dialog', { name: 'Gremium-Rolle löschen' });
    await userEvent.click(within(dialog).getByText('Rolle löschen'));
    expect(api.deleteGremiumRole).toHaveBeenCalledWith('gr-p');
    expect(screen.queryByRole('rowheader', { name: /^Protokoll/ })).toBeNull();
    expect(counts).toEqual([3]);
  });

  it('names a role in use when the server answers 409', async () => {
    const api = makeApi({ deleteGremiumRole: jest.fn(() => throwError(() => ({ status: 409 }))) });
    const { toast } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: 'Rolle löschen: Protokoll' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Rolle löschen'));
    expect(toast.error).toHaveBeenCalledWith(
      'Eine Mitgliedschaft oder eine Gruppen-Zuordnung verwendet die Rolle noch.',
    );
  });

  it('adds a role through the dialog and edits one', async () => {
    const api = makeApi();
    const { counts, toast } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: /Gremium-Rolle hinzufügen/ }));
    await userEvent.type(screen.getByRole('textbox', { name: /Schlüssel/ }), 'beisitz');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.createGremiumRole).toHaveBeenCalledWith(
      'g-1',
      expect.objectContaining({ key: 'beisitz' }),
    );
    expect(screen.getByRole('rowheader', { name: /^Beisitz/ })).toBeInTheDocument();
    expect(counts).toEqual([5]);
    expect(toast.success).toHaveBeenCalledWith('Rolle gespeichert.');

    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten: Protokoll' }));
    const name = screen.getByRole('textbox', { name: 'Bezeichnung (DE)' });
    await userEvent.clear(name);
    await userEvent.type(name, 'Schriftführung');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.updateGremiumRole).toHaveBeenCalledWith(
      'gr-p',
      expect.objectContaining({ name: { de: 'Schriftführung', en: 'Schriftführung' } }),
    );
    expect(screen.getByRole('rowheader', { name: /^Schriftführung/ })).toBeInTheDocument();
  });

  it('asks for a delete from the dialog', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten: Protokoll' }));
    await userEvent.click(screen.getByText('Rolle löschen', { selector: '.btn__label' }));
    expect(screen.getByRole('dialog', { name: 'Gremium-Rolle löschen' })).toBeInTheDocument();
  });

  it('names a failed load', async () => {
    await setup({
      api: makeApi({ listGremiumRoles: jest.fn(() => throwError(() => ({ status: 403 }))) }),
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Rollen konnten nicht geladen werden.');
  });

  it('shows the heading by default and leaves it out on the roles page', async () => {
    await setup();
    expect(
      screen.getByRole('heading', { name: 'Gremienrollen und Berechtigungen' }),
    ).toBeInTheDocument();
  });

  it('shows the heading by default and leaves it out on the roles page (2)', async () => {
    await setup({ inputs: { heading: false } });
    expect(screen.queryByRole('heading', { name: 'Gremienrollen und Berechtigungen' })).toBeNull();
  });

  it('ignores the mapping reads when they fail', async () => {
    const api = makeApi({
      listRoleMappings: jest.fn(() => throwError(() => ({ status: 500 }))),
      listMembershipMappings: jest.fn(() => throwError(() => ({ status: 500 }))),
    });
    await setup({ api });
    expect(within(row('Mitglied')).getByText(/Mitgliedschaft über/)).toHaveTextContent(
      'Mitgliedschaft über —',
    );
  });

  it('guards a toggle without the right or during a save and a delete of a forced role', async () => {
    const api = makeApi();
    const { fixture } = await setup({ api });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const role = ROLES[0];
    c.busy.set(new Set([role.id]));
    c.toggle(role, 'vote.manage', { target: { checked: true } });
    expect(api.updateGremiumRole).not.toHaveBeenCalled();
    c.askDelete(ROLES[1]);
    expect(c.confirmDelete()).toBeNull();
    c.doDelete();
    expect(api.deleteGremiumRole).not.toHaveBeenCalled();
    c.openAdd();
    c.closeDialog();
    expect(c.dialogRole()).toBeUndefined();
    expect(c.groupsOf(null)).toEqual([]);
    expect(c.keyTail('x')).toBe('');
  });
});
