import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TeamsApiService, type TeamDetail } from '@core/api/teams.service';
import { TodosApiService } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { freeTeam } from '../../../../testing/gremien-fixtures';
import { TeamMembersComponent, memberEntry } from './team-members.component';

const DETAIL: TeamDetail = {
  team: freeTeam(),
  members: [
    { principalId: 'p-1', displayName: 'Clara', role: 'manager' },
    { principalId: 'p-2', displayName: 'Paul', role: 'member' },
  ],
  subTeams: [],
};

async function setup(canManage: boolean) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    detail: jest.fn(() => of(DETAIL)),
    setMember: jest.fn(() => of(DETAIL)),
    removeMember: jest.fn(() => of(DETAIL)),
  };
  const todos = { entryOptions: jest.fn(() => of({ teams: [], persons: [{ id: 'p-3', name: 'Otto' }] })) };
  const view = await render(TeamMembersComponent, {
    inputs: { teamId: 't-1', canManage },
    providers: [
      provideHttpClient(),
      { provide: TeamsApiService, useValue: api },
      { provide: TodosApiService, useValue: todos },
    ],
  });
  return { view, api, cmp: view.fixture.componentInstance };
}

describe('TeamMembersComponent (spec 003063)', () => {
  afterEach(() => localStorage.clear());

  it('shows the members with their team role, and only a manager changes them', async () => {
    const s = await setup(false);
    expect(screen.getByText('Clara')).toBeTruthy();
    expect(screen.getByText('Verwaltung')).toBeTruthy();
    expect(screen.getByText('Mitglied')).toBeTruthy();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(await runAxe(s.view.container)).toHaveNoViolations();
  });

  it('adds a person, changes a role and removes a person', async () => {
    const s = await setup(true);
    const changed = jest.fn();
    s.cmp.changed.subscribe(changed);
    s.cmp.add({ kind: 'person', id: 'p-3', name: 'Otto' });
    s.cmp.add({ kind: 'team', id: 'g-1', name: 'StuPa', logoUrl: null });
    expect(s.api.setMember).toHaveBeenCalledTimes(1);
    expect(s.api.setMember).toHaveBeenCalledWith('t-1', 'p-3', 'member');
    s.cmp.setRole(memberEntry(DETAIL.members[1], true), 'manage');
    expect(s.api.setMember).toHaveBeenLastCalledWith('t-1', 'p-2', 'manager');
    s.cmp.remove(memberEntry(DETAIL.members[1], true));
    expect(s.api.removeMember).toHaveBeenCalledWith('t-1', 'p-2');
    expect(changed).toHaveBeenCalledTimes(3);
  });

  it('says that the team needs a manager', async () => {
    const s = await setup(true);
    const show = jest.spyOn(TestBed.inject(ToastService), 'show');
    s.api.removeMember.mockReturnValueOnce(throwError(() => ({ error: { code: 'last_manager' } })));
    s.cmp.remove(memberEntry(DETAIL.members[0], true));
    s.api.removeMember.mockReturnValueOnce(throwError(() => ({ error: {} })));
    s.cmp.remove(memberEntry(DETAIL.members[0], true));
    expect(show.mock.calls.map((c) => c[0])).toEqual([
      'Das Team braucht mindestens eine Person mit „Verwaltung“.',
      'Die Änderung konnte nicht gespeichert werden.',
    ]);
    expect(s.cmp.busy()).toBe(false);
  });

  it('keeps an empty list when the read fails', async () => {
    const s = await setup(true);
    s.api.detail.mockReturnValueOnce(throwError(() => new Error('x')));
    s.view.fixture.componentRef.setInput('teamId', 't-2');
    s.view.fixture.detectChanges();
    expect(s.cmp.entries()).toEqual([]);
  });
});
