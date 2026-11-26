import { TeamsApiService } from '@core/api/teams.service';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { gremienApiMock, gremium, teamsApiMock } from '../../../testing/gremien-fixtures';
import { GREMIEN_NOW, GremienStore } from './gremien.store';

describe('GremienStore', () => {
  function setup(api = gremienApiMock()) {
    TestBed.configureTestingModule({
      providers: [
        GremienStore,
        { provide: GremienApiService, useValue: api },
        { provide: TeamsApiService, useValue: teamsApiMock(api) },
      ],
    });
    return { store: TestBed.inject(GremienStore), api };
  }

  it('loads the overview and finds a gremium by id', () => {
    const { store } = setup();
    expect(store.loading()).toBe(true);
    expect(store.loaded()).toBe(false);
    store.load();
    expect(store.loading()).toBe(false);
    expect(store.loaded()).toBe(true);
    expect(store.find('g-1')).toEqual(gremium());
    expect(store.find('g-x')).toBeNull();
    expect(store.find(null)).toBeNull();
    expect(store.team('g-1')?.gremiumId).toBe('g-1');
    expect(store.team('t-x')).toBeNull();
    expect(store.team(null)).toBeNull();
    expect(store.teamOfGremium('g-1')?.id).toBe('g-1');
    expect(store.teamOfGremium('g-x')).toBeNull();
    expect(store.teamOfGremium(null)).toBeNull();
    expect(store.subTeams(null)).toEqual([]);
  });

  it('reports a failed read and counts it as loaded', () => {
    const { store } = setup(gremienApiMock({ overview: jest.fn(() => throwError(() => new Error('x'))) }));
    store.load();
    expect(store.error()).toBe(true);
    expect(store.loading()).toBe(false);
    expect(store.loaded()).toBe(true);
    expect(store.items()).toEqual([]);
  });

  it('refreshes while the rows show, keeps them on an error, and loads before the first answer', () => {
    const { store, api } = setup();
    store.refresh();
    expect(store.loaded()).toBe(true);
    const rows = store.items();
    const fail = jest.fn(() => throwError(() => new Error('x')));
    (api.overview as jest.Mock).mockImplementation(fail);
    store.refresh();
    expect(store.items()).toBe(rows);
    expect(store.refreshing()).toBe(false);
    expect(store.loading()).toBe(false);
    (api.overview as jest.Mock).mockImplementation(() => of([]));
    store.refresh();
    expect(store.items()).toEqual([]);
    expect(store.refreshing()).toBe(false);
  });

  it('gives the current time by default', () => {
    TestBed.configureTestingModule({});
    const now = TestBed.inject(GREMIEN_NOW)();
    expect(Math.abs(now.getTime() - Date.now())).toBeLessThan(5000);
  });
});
