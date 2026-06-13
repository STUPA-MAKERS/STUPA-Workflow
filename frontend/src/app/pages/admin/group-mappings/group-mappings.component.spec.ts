import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { GroupMappingsComponent } from './group-mappings.component';

function setupApi() {
  return {
    listGroupMappings: jest.fn(() =>
      of([
        { id: 'm1', oidcGroup: 'stupa-vorstand', roleId: 'r1', gremiumId: 'g1' },
        { id: 'm2', oidcGroup: 'fsr-info', roleId: 'r1', gremiumId: null },
      ]),
    ),
    listRoles: jest.fn(() => of([{ id: 'r1', key: 'board', label: { de: 'Vorstand' }, permissions: [] }])),
    listGremienOptions: jest.fn(() => of([{ id: 'g1', name: 'StuPa' }])),
    createGroupMapping: jest.fn(() => of({ id: 'm3', oidcGroup: 'x', roleId: 'r1', gremiumId: null })),
    updateGroupMapping: jest.fn(() => of({ id: 'm1', oidcGroup: 'x', roleId: 'r1', gremiumId: null })),
    deleteGroupMapping: jest.fn(() => of(void 0)),
  };
}

async function setup() {
  const api = setupApi();
  await render(GroupMappingsComponent, {
    providers: [provideRouter([]), { provide: AdminApiService, useValue: api }],
  });
  return api;
}

describe('GroupMappingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists mappings with resolved role + committee, and "global" for none', async () => {
    await setup();
    expect(await screen.findByText('stupa-vorstand')).toBeInTheDocument();
    expect(screen.getByText('fsr-info')).toBeInTheDocument();
    expect(screen.getAllByText('Vorstand').length).toBeGreaterThan(0);
    expect(screen.getByText('StuPa')).toBeInTheDocument();
    // null gremium → global marker.
    expect(screen.getByText('— (global)')).toBeInTheDocument();
  });

  it('opens the add dialog', async () => {
    await setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Mapping hinzufügen' }));
    expect(screen.getByPlaceholderText('Gruppenname aus dem IdP')).toBeInTheDocument();
  });
});
