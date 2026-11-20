import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from '@core/api/api.config';
import { localToday } from '@shared/date-format';
import { OutsideDecisionDialogComponent } from './outside-decision-dialog.component';

@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  standalone: true,
  imports: [OutsideDecisionDialogComponent],
  template: `
    <app-outside-decision-dialog
      [applicationId]="id()"
      [requested]="requested()"
      [gremiumId]="gremium"
      [(open)]="open"
      (done)="done = done + 1"
    />
  `,
})
class Host {
  readonly id = signal<string | null>('app-1');
  readonly requested = signal<string | null>('250.00');
  readonly gremium = 'g1';
  readonly open = signal(false);
  done = 0;
}

const URL = '/api/applications/app-1/outside-decision';
const GREMIEN = [
  { id: 'g1', name: 'StuPa' },
  { id: 'g2', name: 'AStA' },
];
const MEETINGS = [
  { id: 'm1', title: '33. Sitzung', date: '2026-10-01' },
  { id: 'm2', title: '34. Sitzung', date: '2026-11-11' },
  { id: 'm3', title: 'Ohne Datum', date: null },
];

async function setup() {
  const view = await render(Host, {
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const host = view.fixture.componentInstance;
  const cmp = view.fixture.debugElement.children[0].componentInstance as OutsideDecisionDialogComponent;
  const openIt = () => {
    host.open.set(true);
    view.detectChanges();
    http.expectOne('/api/committees').flush(GREMIEN);
    http.expectOne((r) => r.url === '/api/meetings').flush(MEETINGS);
    view.detectChanges();
  };
  const fill = () => {
    cmp.result.set('passed');
    cmp.date.set('2026-11-18');
  };
  return { ...view, http, toast, host, cmp, openIt, fill };
}

describe('OutsideDecisionDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** Spec 001600: the Gremium is preset with the Gremium of the vote state. */
  it('presets the Gremium and lists its meetings, the newest first', async () => {
    const { cmp, openIt } = await setup();
    openIt();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(cmp.gremium()).toBe('g1');
    expect(cmp.gremiumOptions().map((o) => o.label)).toEqual(['StuPa', 'AStA']);
    expect(cmp.meetingOptions().map((o) => o.label)).toEqual([
      '34. Sitzung · 11.11.2026',
      '33. Sitzung · 01.10.2026',
      'Ohne Datum',
    ]);
  });

  it('needs the result, a date not after today and a Gremium', async () => {
    const { http, cmp, openIt } = await setup();
    openIt();
    cmp.submit();
    expect(cmp.ready()).toBe(false);
    cmp.result.set('failed');
    cmp.date.set('2999-01-01');
    expect(cmp.dateError()).toBe('Das Datum darf nicht nach heute liegen.');
    cmp.date.set(localToday());
    expect(cmp.ready()).toBe(true);
    cmp.pickGremium('');
    expect(cmp.ready()).toBe(false);
    http.verify();
  });

  it('checks the counts', async () => {
    const { cmp, openIt, fill } = await setup();
    openIt();
    fill();
    cmp.yes.set('x');
    expect(cmp.countError()).not.toBe('');
    cmp.yes.set('10001');
    expect(cmp.countError()).not.toBe('');
    cmp.yes.set('7');
    expect(cmp.countError()).toBe('');
  });

  /** Spec 001610: a passed decision names the amount; it is prefilled with the request. */
  it('records a passed decision with the amount, the counts and the meeting', async () => {
    const { http, host, cmp, toast, openIt, fill } = await setup();
    const success = jest.spyOn(toast, 'success');
    openIt();
    fill();
    expect(cmp.asksAmount()).toBe(true);
    cmp.yes.set('7');
    cmp.no.set(' ');
    cmp.meeting.set('m2');
    cmp.submit();
    const post = http.expectOne((r) => r.method === 'POST' && r.url === URL);
    expect(post.request.body).toEqual({
      result: 'passed',
      meetingDate: '2026-11-18',
      gremiumId: 'g1',
      yes: 7,
      no: null,
      abstain: null,
      meetingId: 'm2',
      decision: { approvedAmount: '250.00', conditions: [] },
    });
    post.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });
    expect(host.open()).toBe(false);
    expect(host.done).toBe(1);
    expect(success).toHaveBeenCalled();
  });

  it('sends no decision for a failed result or an application without money', async () => {
    const { http, host, cmp, openIt } = await setup();
    host.requested.set(null);
    openIt();
    cmp.result.set('passed');
    cmp.date.set('2026-11-18');
    expect(cmp.asksAmount()).toBe(false);
    cmp.submit();
    expect(http.expectOne(URL).request.body.decision).toBeNull();
  });

  it('shows a refusal of the server in the dialog', async () => {
    const { http, host, cmp, openIt, fill } = await setup();
    openIt();
    fill();
    cmp.submit();
    http
      .expectOne(URL)
      .flush({ code: 'meeting_unknown' }, { status: 422, statusText: 'x' });
    expect(cmp.refusal()).toBe('Die Sitzung ist unbekannt oder nicht sichtbar.');
    expect(host.open()).toBe(true);
  });

  it.each([
    [409, true, { code: 'x' }],
    [403, false, { code: 'x' }],
    [422, false, { code: 'x' }],
    [500, false, null],
  ])('reports a %s answer', async (status, closes, body) => {
    const { http, host, cmp, toast, openIt, fill } = await setup();
    const error = jest.spyOn(toast, 'error');
    openIt();
    fill();
    cmp.submit();
    http.expectOne(URL).flush(body, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledTimes(1);
    expect(host.open()).toBe(!closes);
    expect(host.done).toBe(closes ? 1 : 0);
  });

  it('keeps going when the pickers fail and drops stale meetings', async () => {
    const { http, host, cmp, detectChanges } = await setup();
    host.open.set(true);
    detectChanges();
    http.expectOne('/api/committees').flush({}, { status: 500, statusText: 'x' });
    const stale = http.expectOne((r) => r.url === '/api/meetings');
    cmp.pickGremium('g2');
    stale.flush(MEETINGS);
    expect(cmp.meetingOptions()).toEqual([]);
    http.expectOne((r) => r.url === '/api/meetings').flush({}, { status: 500, statusText: 'x' });
    expect(cmp.gremiumOptions()).toEqual([]);
    cmp.close();
    expect(host.open()).toBe(false);
  });
});
