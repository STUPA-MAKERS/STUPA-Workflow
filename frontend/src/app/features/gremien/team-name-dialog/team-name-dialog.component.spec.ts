import { TestBed } from '@angular/core/testing';
import { render } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TeamsApiService } from '@core/api/teams.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { freeTeam } from '../../../../testing/gremien-fixtures';
import { TeamNameDialogComponent } from './team-name-dialog.component';

async function setup(inputs: Record<string, unknown>) {
  localStorage.setItem('ap.locale', 'de');
  const detail = { team: freeTeam(), members: [], subTeams: [] };
  const api = { create: jest.fn(() => of(detail)), patch: jest.fn(() => of(detail)) };
  const view = await render(TeamNameDialogComponent, {
    inputs,
    providers: [{ provide: TeamsApiService, useValue: api }],
  });
  const cmp = view.fixture.componentInstance;
  const saved = jest.fn();
  cmp.saved.subscribe(saved);
  return { view, api, cmp, saved };
}

describe('TeamNameDialogComponent (spec 003065)', () => {
  afterEach(() => localStorage.clear());

  it('creates a team at the top, and nothing without a name', async () => {
    const s = await setup({});
    expect(s.cmp.heading()).toBe('teams.create');
    s.cmp.submit();
    expect(s.api.create).not.toHaveBeenCalled();
    s.cmp.name.set('  Ersti  ');
    s.cmp.submit();
    expect(s.api.create).toHaveBeenCalledWith('Ersti', null);
    expect(s.saved).toHaveBeenCalled();
    expect(s.cmp.open()).toBe(false);
  });

  it('creates a sub-team under its parent', async () => {
    const s = await setup({ parentId: 't-1' });
    expect(s.cmp.heading()).toBe('teams.createSub');
    s.cmp.name.set('Party');
    s.cmp.submit();
    expect(s.api.create).toHaveBeenCalledWith('Party', 't-1');
  });

  it('renames a team and starts with its name', async () => {
    const s = await setup({ renameId: 't-1', current: 'Ersti' });
    s.view.fixture.componentRef.setInput('open', true);
    s.view.fixture.detectChanges();
    expect(s.cmp.name()).toBe('Ersti');
    expect(s.cmp.heading()).toBe('teams.rename');
    expect(s.cmp.submitLabel()).toBe('action.save');
    s.cmp.name.set('Neu');
    s.cmp.submit();
    expect(s.api.patch).toHaveBeenCalledWith('t-1', { name: 'Neu' });
  });

  it('says why the server refused', async () => {
    const s = await setup({});
    const show = jest.spyOn(TestBed.inject(ToastService), 'show');
    s.api.create.mockReturnValueOnce(throwError(() => ({ error: { code: 'team_create_required' } })));
    s.cmp.name.set('X');
    s.cmp.submit();
    s.api.create.mockReturnValueOnce(throwError(() => ({ error: {} })));
    s.cmp.submit();
    expect(show.mock.calls.map((c) => c[0])).toEqual([
      'Dafür fehlt dir das Recht.',
      'Die Änderung konnte nicht gespeichert werden.',
    ]);
    expect(s.cmp.saving()).toBe(false);
  });
});
