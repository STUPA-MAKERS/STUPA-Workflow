import { provideHttpClient } from '@angular/common/http';
import { signal } from '@angular/core';
import { provideRouter, Router } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import type { Team } from '@core/api/teams.service';
import { runAxe } from '../../../../testing/a11y';
import { freeTeam } from '../../../../testing/gremien-fixtures';
import { GremienStore } from '../gremien.store';
import { TeamSubTeamsComponent } from './team-sub-teams.component';

async function setup(teams: readonly Team[], canManage: boolean) {
  localStorage.setItem('ap.locale', 'de');
  const list = signal(teams);
  const store = {
    subTeams: (id: string) => list().filter((t) => t.parentId === id),
    reloadTeams: jest.fn(),
  };
  const view = await render(TeamSubTeamsComponent, {
    inputs: { teamId: 't-1', canManage },
    providers: [provideHttpClient(), provideRouter([]), { provide: GremienStore, useValue: store }],
  });
  return { view, store, cmp: view.fixture.componentInstance };
}

describe('TeamSubTeamsComponent (spec 003062)', () => {
  afterEach(() => localStorage.clear());

  it('lists the sub-teams as links, and offers "Sub-Team anlegen" to a manager', async () => {
    const s = await setup(
      [
        freeTeam({ id: 't-2', name: 'Party', parentId: 't-1' }),
        freeTeam({ id: 't-3', name: 'Presse', parentId: 't-1', isMember: false, canManage: false }),
        freeTeam({ id: 't-4', name: 'Technik', parentId: 't-1', canManage: false }),
        freeTeam({ id: 't-9', name: 'Andere', parentId: 't-8' }),
      ],
      true,
    );
    expect(screen.getByRole('link', { name: 'Party' }).getAttribute('href')).toBe('/teams/t-2');
    expect(screen.getByRole('link', { name: 'Presse' })).toBeTruthy();
    expect(screen.queryByText('Andere')).toBeNull();
    expect(s.cmp.rows()).toEqual(
      expect.objectContaining({
        data: [
          expect.objectContaining({ title: 'Party' }),
          expect.objectContaining({ title: 'Presse' }),
          expect.objectContaining({ title: 'Technik' }),
        ],
      }),
    );
    screen.getByRole('button', { name: /^Sub-Team anlegen/ }).click();
    expect(s.cmp.createOpen()).toBe(true);
    expect(await runAxe(s.view.container)).toHaveNoViolations();
  });

  it('says when there is no sub-team, and offers no button to a member', async () => {
    await setup([], false);
    expect(screen.getByText('Keine Sub-Teams')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Sub-Team anlegen/ })).toBeNull();
  });

  it('opens a new sub-team', async () => {
    const s = await setup([], true);
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    s.cmp.created({ team: freeTeam({ id: 't-new' }), members: [], subTeams: [] });
    expect(s.store.reloadTeams).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith(['/teams', 't-new']);
  });
});
