import { Injector, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { topLead, topPlanLead } from './top-application-lead.util';

const PLAN_TOP: AgendaItem = {
  id: 't-1',
  applicationId: null,
  planVersionId: 'pv-1',
  title: 'Haushaltsplan VS-Mittel 2026: Beschluss',
  position: 0,
};
const APP_TOP: AgendaItem = { id: 't-2', applicationId: 'a-1', title: 'Zuschuss', position: 1 };

/** §F/finance/budget/000838: the item of a plan links to the version, for a reader of the plan. */
describe('topPlanLead', () => {
  const i18n = () => TestBed.inject(I18nService);

  it('is the row of the plan for a reader of the plan', () => {
    expect(topPlanLead(PLAN_TOP, 'pv-1', i18n())).toEqual({
      icon: 'euro',
      title: 'Haushaltsplan VS-Mittel 2026: Beschluss',
      sub: 'Haushaltsplan',
      link: ['/budget/plan'],
      queryParams: { planVersion: 'pv-1' },
    });
    expect(topPlanLead({ ...PLAN_TOP, title: null }, 'pv-1', i18n())?.title).toBe('Unbenannter TOP');
  });

  it('is no row without a plan, and for a reader who may not read the plan', () => {
    expect(topPlanLead(null, null, i18n())).toBeNull();
    expect(topPlanLead(APP_TOP, null, i18n())).toBeNull();
    expect(topPlanLead(PLAN_TOP, null, i18n())).toBeNull();
    expect(topPlanLead(PLAN_TOP, 'pv-other', i18n())).toBeNull();
  });
});

describe('topLead', () => {
  function setup(readable: boolean) {
    const planOfVersionReadable = jest.fn(() => of(readable));
    TestBed.configureTestingModule({
      providers: [{ provide: ApiClient, useValue: { planOfVersionReadable } }],
    });
    const top = signal<AgendaItem | null>(null);
    const lead = TestBed.runInInjectionContext(() =>
      topLead(top, TestBed.inject(Injector), TestBed.inject(I18nService)),
    );
    return { top, lead, planOfVersionReadable };
  }

  it('asks for the plan only on an item with a plan and shows the row to its reader', () => {
    const { top, lead, planOfVersionReadable } = setup(true);
    TestBed.tick();
    expect(lead()).toBeNull();
    top.set(APP_TOP);
    TestBed.tick();
    expect(lead()?.link).toEqual(['/applications', 'a-1']);
    expect(planOfVersionReadable).not.toHaveBeenCalled();
    top.set(PLAN_TOP);
    TestBed.tick();
    expect(planOfVersionReadable).toHaveBeenCalledWith('pv-1');
    expect(lead()?.queryParams).toEqual({ planVersion: 'pv-1' });
  });

  it('shows no row to a person who may not read the plan', () => {
    const { top, lead } = setup(false);
    top.set(PLAN_TOP);
    TestBed.tick();
    expect(lead()).toBeNull();
  });
});
