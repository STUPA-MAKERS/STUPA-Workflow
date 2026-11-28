import { provideTestStatuses } from '@core/api/statuses.service';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { render } from '@testing-library/angular';
import { BehaviorSubject, of, throwError } from 'rxjs';
import { type EventOption, EventsApiService } from '@core/api/events.service';
import { MOCK_EVENT_SALES, MOCK_PRETIX_EVENTS } from '@core/api/mock-sales';
import { SalesApiService } from '@core/api/sales.service';
import { AuthService } from '@core/auth/auth.service';
import { BudgetTreeApi } from '../budget/budget-tree.api';
import { node } from '../budget/plan/budget-plan.fixtures';
import { ToastService } from '@stupa-makers/ui-kit';
import { eventDetail } from '../../../testing/event-fixtures';
import { EventFormComponent } from './event-form.component';
import { EventsRefresh } from './events-refresh';
import { NEW_SERIES } from './events.util';

interface Options {
  readonly id?: string | null;
  readonly from?: string | null;
  readonly teams?: readonly EventOption[] | null;
  /** The pretix events of the picker; without them the picker is off. */
  readonly pretix?: boolean;
  readonly perms?: readonly string[];
}

async function setup(options: Options = {}) {
  localStorage.setItem('ap.locale', 'de');
  const first = eventDetail();
  const api = {
    get: jest.fn(() => of(first)),
    teams: jest.fn(() => (options.teams === null ? throwError(() => ({ status: 500 })) : of(options.teams ?? [{ id: 't-1', name: 'Kultur' }]))),
    series: jest.fn(() => of([{ id: 's-1', name: 'Erstiparty' }])),
    createSeries: jest.fn((name: string) => of({ id: 's-2', name })),
    create: jest.fn(() => of(eventDetail({ id: 'e-9' }))),
    update: jest.fn(() => of(first)),
  };
  const sales = {
    pretixEvents: jest.fn(() => (options.pretix ? of(MOCK_PRETIX_EVENTS) : throwError(() => ({ status: 404 })))),
    eventSales: jest.fn(() => of(MOCK_EVENT_SALES)),
    link: jest.fn(() => of({})),
    unlink: jest.fn(() => of(undefined)),
    setIncomeBudget: jest.fn(() => of({})),
  };
  const perms = new Set(options.perms ?? ['budget.book']);
  const paramMap = new BehaviorSubject(convertToParamMap(options.id ? { id: options.id } : {}));
  const query = convertToParamMap(options.from ? { from: options.from } : {});
  const view = await render(EventFormComponent, {
    providers: [
      provideTestStatuses(),
      provideRouter([]),
      { provide: EventsApiService, useValue: api },
      { provide: SalesApiService, useValue: sales },
      { provide: BudgetTreeApi, useValue: { tree: () => of([node({ id: 'inc', name: 'Einnahmen' })]) } },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ActivatedRoute, useValue: { paramMap, snapshot: { queryParamMap: query } } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const injector = view.fixture.debugElement.injector;
  const toast = jest.spyOn(injector.get(ToastService), 'show');
  const navigate = jest.spyOn(injector.get(Router), 'navigate').mockResolvedValue(true);
  const touched = jest.fn();
  injector.get(EventsRefresh).changed.subscribe(touched);
  const fields = (): { key: string; visible?: boolean; required?: boolean; options?: { value: string }[] }[] =>
    cmp.form().sections[0].fields;
  return { ...view, cmp, api, sales, toast, navigate, touched, fields, paramMap };
}

describe('EventFormComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/collaboration/events/003023: the fields of an Event. */
  it('opens the empty form with the one team and the start status', async () => {
    const { cmp, fields } = await setup();
    expect(cmp.title()).toBe('Veranstaltung anlegen');
    expect(cmp.value()).toMatchObject({ teamId: 't-1', status: 'planned', startsOn: '' });
    expect(fields().map((f) => f.key)).toEqual([
      'teamId',
      'title',
      'status',
      'startsOn',
      'startTime',
      'endsOn',
      'endTime',
      'place',
      'participants',
      'seriesId',
      'seriesName',
      'shopUrl',
      'pretixSlug',
      'incomeBudgetId',
      'descriptionMd',
    ]);
    expect(fields()[2].options?.map((o) => o.value)).toEqual(['planned', 'settled', 'cancelled']);
    expect(fields()[9].options?.map((o) => o.value)).toEqual(['', 's-1', NEW_SERIES]);
    expect(fields()[10]).toMatchObject({ visible: false, required: false });
  });

  it('leaves the team open for a person with several teams', async () => {
    const { cmp } = await setup({ teams: [{ id: 't-1', name: 'Kultur' }, { id: 't-2', name: 'Sport' }] });
    expect(cmp.value()['teamId']).toBe('');
  });

  it('leaves the team open when the teams cannot be read', async () => {
    const { cmp } = await setup({ teams: null });
    expect(cmp.value()['teamId']).toBe('');
  });

  /** §F/collaboration/events/003030: the plan of the Event, no dates and the start status. */
  it('fills a follow-up from another Event', async () => {
    const { cmp, api } = await setup({ from: 'e-1' });
    expect(api.get).toHaveBeenCalledWith('e-1');
    expect(cmp.editing()).toBe(false);
    expect(cmp.value()).toMatchObject({
      teamId: 't-1',
      title: 'Erstiparty',
      place: 'Hof',
      shopUrl: 'https://shop.example.org/erstiparty',
      seriesId: 's-1',
      descriptionMd: 'Party im **Hof**',
      startsOn: '',
      endsOn: '',
      startTime: '',
      endTime: '',
      status: 'planned',
    });
  });

  it('creates an Event and opens it', async () => {
    const { cmp, api, navigate, touched } = await setup();
    cmp.onValue({ ...cmp.value(), title: 'Sommerfest', startsOn: '2027-06-01', startTime: '18:00' });
    cmp.save(cmp.value());
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ teamId: 't-1', title: 'Sommerfest', startTime: '18:00:00', status: 'planned', seriesId: null }));
    expect(touched).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(['/events', 'e-9'], { queryParams: { from: null }, queryParamsHandling: 'merge' });
  });

  it('creates a new series first and saves the Event with it', async () => {
    const { cmp, api, fields } = await setup();
    cmp.onValue({ ...cmp.value(), title: 'Fest', seriesId: NEW_SERIES, seriesName: '' });
    expect(fields()[10]).toMatchObject({ visible: true, required: true });
    cmp.save(cmp.value());
    expect(api.createSeries).not.toHaveBeenCalled();
    cmp.onValue({ ...cmp.value(), seriesName: ' Sommer ' });
    cmp.save(cmp.value());
    expect(api.createSeries).toHaveBeenCalledWith('Sommer');
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ seriesId: 's-2' }));
    expect(cmp.value()).toMatchObject({ seriesId: 's-2', seriesName: '' });
    expect(fields()[9].options?.map((o) => o.value)).toEqual(['', 's-1', 's-2', NEW_SERIES]);
  });

  it('changes an Event with its version', async () => {
    const { cmp, api, navigate } = await setup({ id: 'e-1' });
    expect(cmp.title()).toBe('Veranstaltung bearbeiten');
    expect(cmp.value()).toMatchObject({ title: 'Erstiparty', startTime: '19:00' });
    cmp.save({ ...cmp.value(), place: 'Halle' });
    expect(api.update).toHaveBeenCalledWith('e-1', 1, expect.objectContaining({ place: 'Halle', seriesId: 's-1' }));
    cmp.close();
    expect(navigate).toHaveBeenLastCalledWith(['/events', 'e-1'], { queryParams: { from: null }, queryParamsHandling: 'merge' });
  });

  it('keeps a team of the Event that the person left', async () => {
    const { cmp, fields } = await setup({ id: 'e-1', teams: [{ id: 't-2', name: 'Sport' }] });
    expect(cmp.event()).not.toBeNull();
    expect(fields()[0].options?.map((o) => o.value)).toEqual(['t-1', 't-2']);
  });

  it.each([
    ['event_url_invalid', 'shopUrl', 'Der Link muss mit http:// oder https:// beginnen.'],
    ['event_dates_invalid', 'endsOn', 'Das Ende liegt vor dem Beginn.'],
    ['event_time_without_date', 'startTime', 'Eine Uhrzeit braucht ihren Tag.'],
    ['event_team_forbidden', 'teamId', 'Du bist nicht in diesem Team.'],
    ['series_exists', 'seriesName', 'Diese Reihe gibt es schon.'],
  ])('shows the refusal %s at its field', async (code, field, text) => {
    const { cmp, api } = await setup();
    api.create.mockReturnValueOnce(throwError(() => ({ error: { code } })));
    cmp.save(cmp.value());
    expect(cmp.errors()).toEqual({ [field]: text });
    cmp.onValue(cmp.value());
    expect(cmp.errors()).toEqual({});
  });

  it('says when a save fails and closes after a conflict', async () => {
    const { cmp, api, toast, navigate } = await setup({ id: 'e-1' });
    api.update.mockReturnValueOnce(throwError(() => ({ error: null })));
    cmp.save(cmp.value());
    expect(toast).toHaveBeenCalledWith('Die Veranstaltung konnte nicht gespeichert werden.', 'error');
    api.update.mockReturnValueOnce(throwError(() => ({ error: { code: 'event_version_conflict' } })));
    cmp.save(cmp.value());
    expect(toast).toHaveBeenLastCalledWith('Die Veranstaltung wurde inzwischen geändert. Sie ist neu geladen.', 'error');
    expect(navigate).toHaveBeenLastCalledWith(['/events', 'e-1'], expect.anything());
  });

  it('goes back to the list when the Event cannot be read, and saves once at a time', async () => {
    const { cmp, api, toast, navigate, paramMap } = await setup();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 404 })));
    paramMap.next(convertToParamMap({ id: 'e-7' }));
    expect(toast).toHaveBeenCalledWith('Die Veranstaltung konnte nicht geladen werden.', 'error');
    expect(navigate).toHaveBeenLastCalledWith(['/events'], { queryParams: { from: null }, queryParamsHandling: 'merge' });
    cmp.saving.set(true);
    cmp.save(cmp.value());
    expect(api.create).not.toHaveBeenCalled();
  });

  /** §F/integrations/pretix/003083, 003086: the picker and the income cost centre. */
  describe('pretix', () => {
    const field = (fields: () => { key: string; visible?: boolean }[], key: string) => fields().find((f) => f.key === key);

    it('hides both fields while the pretix events cannot be read', async () => {
      const { fields, cmp, sales } = await setup();
      expect(field(fields, 'pretixSlug')?.visible).toBe(false);
      expect(field(fields, 'incomeBudgetId')?.visible).toBe(false);
      cmp.save({ ...cmp.value(), title: 'X', pretixSlug: 'a' });
      expect(sales.link).not.toHaveBeenCalled();
    });

    it('offers the free events and asks for the cost centre once one is picked', async () => {
      const { fields, cmp } = await setup({ pretix: true });
      const picker = field(fields, 'pretixSlug') as { visible?: boolean; options?: { value: string; label: string }[] };
      expect(picker.visible).toBe(true);
      expect(picker.options?.map((o) => o.value)).toEqual(['', 'semesterparty-ws26']);
      expect(picker.options?.[1].label).toMatch(/^Semesterparty WS 26\/27 · /);
      expect(field(fields, 'incomeBudgetId')?.visible).toBe(false);
      cmp.onValue({ ...cmp.value(), pretixSlug: 'semesterparty-ws26' });
      expect(field(fields, 'incomeBudgetId')?.visible).toBe(true);
    });

    it('keeps the cost centre away without budget.book', async () => {
      const { fields, cmp } = await setup({ pretix: true, perms: [] });
      cmp.onValue({ ...cmp.value(), pretixSlug: 'semesterparty-ws26' });
      expect(field(fields, 'incomeBudgetId')?.visible).toBe(false);
    });

    it('links a new Event and sets its cost centre after the save', async () => {
      const { cmp, sales, navigate } = await setup({ pretix: true });
      cmp.save({ ...cmp.value(), title: 'Party', pretixSlug: 'semesterparty-ws26', incomeBudgetId: 'inc' });
      expect(sales.link).toHaveBeenCalledWith('e-9', 'semesterparty-ws26');
      expect(sales.setIncomeBudget).toHaveBeenCalledWith('e-9', 'inc');
      expect(navigate).toHaveBeenCalledWith(['/events', 'e-9'], expect.anything());
    });

    it('fills the saved link of an Event and removes it', async () => {
      const { cmp, sales } = await setup({ id: 'e-1', pretix: true });
      expect(cmp.value()).toMatchObject({ pretixSlug: 'semesterparty-ws26', incomeBudgetId: '' });
      cmp.save({ ...cmp.value(), pretixSlug: '' });
      expect(sales.unlink).toHaveBeenCalledWith('e-1');
    });

    it.each([
      ['pretix_event_taken', 'Diese Pretix-Veranstaltung gehört schon zu einer anderen Veranstaltung.'],
      ['other', 'Die Pretix-Veranstaltung konnte nicht verknüpft werden.'],
    ])('says why the link failed (%s) and still opens the saved Event', async (code, text) => {
      const { cmp, sales, toast, navigate } = await setup({ pretix: true });
      sales.link.mockReturnValueOnce(throwError(() => ({ error: { code } })));
      cmp.save({ ...cmp.value(), title: 'Party', pretixSlug: 'semesterparty-ws26' });
      expect(toast).toHaveBeenCalledWith(text, 'error');
      expect(navigate).toHaveBeenCalledWith(['/events', 'e-9'], expect.anything());
    });

    it('keeps the form when the link of an Event cannot be read', async () => {
      const { cmp, sales, paramMap } = await setup({ pretix: true });
      sales.eventSales.mockReturnValueOnce(throwError(() => ({ status: 500 })));
      paramMap.next(convertToParamMap({ id: 'e-1' }));
      expect(cmp.value()).toMatchObject({ pretixSlug: '', incomeBudgetId: '' });
    });
  });
});
