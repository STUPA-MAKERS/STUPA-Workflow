import { of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@shared/ui';
import type { GremiumRole } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GremiumRolesComponent } from './gremium-roles.component';

const ROLES: GremiumRole[] = [
  { id: 'gr-1', gremiumId: 'g-1', key: 'vorsitz', name: { de: 'Vorsitz', en: 'Chair' }, permissions: ['vote.cast'] },
  { id: 'gr-2', gremiumId: 'g-1', key: 'beisitz', name: {}, permissions: undefined },
];

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremiumRoles: jest.fn(() => of([...ROLES])),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createGremiumRole: jest.fn((_gid: string, b: any) => of({ id: 'gr-new', gremiumId: _gid, ...b })),
    updateGremiumRole: jest.fn((id: string, b: { name: unknown }) => of({ ...ROLES[0], id, ...b })),
    deleteGremiumRole: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(api = makeApi(), toast = makeToast()) {
  const view = await render(GremiumRolesComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: 'g-1' }) } } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

describe('GremiumRolesComponent (#42)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists gremium roles via the route gremium id', async () => {
    const { api } = await setup();
    expect(api.listGremiumRoles).toHaveBeenCalledWith('g-1');
    expect(screen.getByText('Vorsitz')).toBeInTheDocument();
    expect(screen.getByText('vorsitz')).toBeInTheDocument();
  });

  it('permLabel + label resolve as expected', async () => {
    const { c } = await setup();
    expect(c.permLabel('vote.cast')).toBe('admin.gremiumPerm.vote.cast');
    // label(): locale → de → key fallbacks, and null guard
    expect(c.label(ROLES[0])).toBe('Vorsitz');
    expect(c.label({ name: {}, key: 'beisitz' })).toBe('beisitz');
    expect(c.label(null)).toBe('');
    expect(c.label({ name: { en: 'OnlyEn' }, key: 'k' })).toBe('k'); // de locale, no de/en→key? de missing→key
  });

  it('label uses en when locale is en', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { c } = await setup();
    expect(c.label(ROLES[0])).toBe('Chair');
  });

  it('togglePerm adds/removes preserving catalog order; no-op without draft', async () => {
    const { c } = await setup();
    // no draft yet → returns d unchanged (null)
    c.togglePerm('vote.manage', true);
    expect(c.draft()).toBeNull();

    c.openAdd();
    expect(c.draft().permissions).toEqual(['vote.cast']);
    c.togglePerm('session.manage', true);
    // order follows GREMIUM_PERMISSIONS: session.manage before vote.cast
    expect(c.draft().permissions).toEqual(['session.manage', 'vote.cast']);
    c.togglePerm('vote.cast', false);
    expect(c.draft().permissions).toEqual(['session.manage']);
  });

  it('openAdd starts a blank draft with default vote.cast and no editingId', async () => {
    const { c } = await setup();
    c.openAdd();
    expect(c.editingId()).toBeNull();
    expect(c.draft()).toEqual({ key: '', labelDe: '', labelEn: '', permissions: ['vote.cast'] });
  });

  it('openEdit loads the role into the draft (incl. missing permissions → [])', async () => {
    const { c } = await setup();
    c.openEdit(0);
    expect(c.editingId()).toBe('gr-1');
    expect(c.draft()).toEqual({ key: 'vorsitz', labelDe: 'Vorsitz', labelEn: 'Chair', permissions: ['vote.cast'] });
    // role with no de/en + undefined permissions
    c.openEdit(1);
    expect(c.draft()).toEqual({ key: 'beisitz', labelDe: '', labelEn: '', permissions: [] });
  });

  it('close clears draft + editingId', async () => {
    const { c } = await setup();
    c.openEdit(0);
    c.close();
    expect(c.draft()).toBeNull();
    expect(c.editingId()).toBeNull();
  });

  it('patch updates a draft field; no-op when no draft', async () => {
    const { c } = await setup();
    c.patch('key', 'x');
    expect(c.draft()).toBeNull();
    c.openAdd();
    c.patch('labelDe', 'Beisitz');
    expect(c.draft().labelDe).toBe('Beisitz');
  });

  it('save does nothing without a draft or with a blank key', async () => {
    const { c, api } = await setup();
    c.save(); // no draft
    c.openAdd();
    c.patch('key', '   ');
    c.save();
    expect(api.createGremiumRole).not.toHaveBeenCalled();
  });

  it('creates a role via the dialog (label fallbacks de→en→key)', async () => {
    const { c, api, toast } = await setup();
    c.openAdd();
    c.patch('key', 'beisitz');
    c.patch('labelDe', 'Beisitz');
    c.save();
    expect(api.createGremiumRole).toHaveBeenCalledWith('g-1', {
      key: 'beisitz',
      name: { de: 'Beisitz', en: 'Beisitz' },
      permissions: ['vote.cast'],
    });
    expect(c.roles().some((r: GremiumRole) => r.id === 'gr-new')).toBe(true);
    expect(toast.success).toHaveBeenCalled();
    expect(c.draft()).toBeNull();
  });

  it('create name falls back to key when both labels blank', async () => {
    const { c, api } = await setup();
    c.openAdd();
    c.patch('key', 'kasse');
    c.save();
    expect(api.createGremiumRole).toHaveBeenCalledWith('g-1', {
      key: 'kasse',
      name: { de: 'kasse', en: 'kasse' },
      permissions: ['vote.cast'],
    });
  });

  it('create en falls back to de label when en blank', async () => {
    const { c, api } = await setup();
    c.openAdd();
    c.patch('key', 'ref');
    c.patch('labelDe', 'Referent');
    c.patch('labelEn', '');
    c.save();
    expect(api.createGremiumRole).toHaveBeenCalledWith('g-1', {
      key: 'ref',
      name: { de: 'Referent', en: 'Referent' },
      permissions: ['vote.cast'],
    });
  });

  it('updates an existing role (editingId set → updateGremiumRole, replaces in list)', async () => {
    const { c, api, toast } = await setup();
    c.openEdit(0);
    c.patch('labelDe', 'Vorsitzende');
    c.save();
    expect(api.updateGremiumRole).toHaveBeenCalledWith('gr-1', {
      name: { de: 'Vorsitzende', en: 'Chair' },
      permissions: ['vote.cast'],
    });
    const updated = c.roles().find((r: GremiumRole) => r.id === 'gr-1');
    expect(updated.name.de).toBe('Vorsitzende');
    expect(toast.success).toHaveBeenCalled();
  });

  it('save error path shows an error toast and keeps the dialog open', async () => {
    const api = makeApi({ createGremiumRole: jest.fn(() => throwError(() => new Error('boom'))) });
    const { c, toast } = await setup(api);
    c.openAdd();
    c.patch('key', 'x');
    c.save();
    expect(toast.error).toHaveBeenCalled();
    expect(c.draft()).not.toBeNull(); // close() not called on error
  });

  it('askDelete sets the confirm target', async () => {
    const { c } = await setup();
    c.askDelete(ROLES[0]);
    expect(c.confirmDelete()).toEqual(ROLES[0]);
  });

  it('doDelete is a no-op without a confirm target', async () => {
    const { c, api } = await setup();
    c.doDelete();
    expect(api.deleteGremiumRole).not.toHaveBeenCalled();
  });

  it('deletes a role via confirmation and removes it from the list', async () => {
    const { c, api, toast } = await setup();
    c.askDelete(ROLES[0]);
    c.doDelete();
    expect(api.deleteGremiumRole).toHaveBeenCalledWith('gr-1');
    expect(c.roles().some((r: GremiumRole) => r.id === 'gr-1')).toBe(false);
    expect(c.confirmDelete()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
  });

  it('delete error path shows an error toast and keeps the role', async () => {
    const api = makeApi({ deleteGremiumRole: jest.fn(() => throwError(() => new Error('nope'))) });
    const { c, toast } = await setup(api);
    c.askDelete(ROLES[0]);
    c.doDelete();
    expect(toast.error).toHaveBeenCalled();
    expect(c.roles().some((r: GremiumRole) => r.id === 'gr-1')).toBe(true);
  });
});
