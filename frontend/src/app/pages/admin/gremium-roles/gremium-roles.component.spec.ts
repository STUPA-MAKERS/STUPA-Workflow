import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import type { GremiumRole } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GremiumRolesComponent } from './gremium-roles.component';

const ROLES: GremiumRole[] = [
  { id: 'gr-1', key: 'vorsitz', name: { de: 'Vorsitz', en: 'Chair' } },
];

function makeApi() {
  return {
    listGremiumRoles: jest.fn(() => of(ROLES)),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createGremiumRole: jest.fn((b: any) => of({ id: 'gr-new', ...b })),
    updateGremiumRole: jest.fn((id: string, b: { name: unknown }) => of({ ...ROLES[0], id, ...b })),
    deleteGremiumRole: jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const view = await render(GremiumRolesComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, api };
}

describe('GremiumRolesComponent (#42)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists gremium roles', async () => {
    await setup();
    expect(screen.getByText('Vorsitz')).toBeInTheDocument();
    expect(screen.getByText('vorsitz')).toBeInTheDocument();
  });

  it('creates a role via the dialog', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.patch('key', 'beisitz');
    c.patch('labelDe', 'Beisitz');
    c.save();
    expect(api.createGremiumRole).toHaveBeenCalledWith({
      key: 'beisitz',
      name: { de: 'Beisitz', en: 'Beisitz' },
    });
    expect(c.roles().some((r: GremiumRole) => r.id === 'gr-new')).toBe(true);
  });

  it('deletes a role via confirmation', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.askDelete(ROLES[0]);
    c.doDelete();
    expect(api.deleteGremiumRole).toHaveBeenCalledWith('gr-1');
    expect(c.roles()).toHaveLength(0);
  });
});
