import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from '@core/api/api.config';
import { AmendAmountDialogComponent } from './amend-amount-dialog.component';
import { kindSpies } from '../../../../testing/toast';

@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  standalone: true,
  imports: [AmendAmountDialogComponent],
  template: `
    <app-amend-amount-dialog
      [applicationId]="'app-1'"
      [requested]="'250.00'"
      [approved]="approved()"
      [gremiumId]="'g1'"
      [(open)]="open"
      (done)="done = done + 1"
    />
  `,
})
class Host {
  readonly approved = signal<string | null>('200.00');
  readonly open = signal(false);
  done = 0;
}

const URL = '/api/applications/app-1/approved-amount';

async function setup() {
  const view = await render(Host, {
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const host = view.fixture.componentInstance;
  const cmp = view.fixture.debugElement.children[0].componentInstance as AmendAmountDialogComponent;
  const openIt = () => {
    host.open.set(true);
    view.detectChanges();
    http.expectOne('/api/committees').flush([{ id: 'g1', name: 'StuPa' }]);
    view.detectChanges();
  };
  const fill = () => {
    cmp.amount.set('122.00');
    cmp.reason.set('  Mehrkosten Druck  ');
    cmp.date.set('2026-11-18');
  };
  return { ...view, http, toast, host, cmp, openIt, fill };
}

describe('AmendAmountDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('starts with the current approved amount and the Gremium', async () => {
    const { cmp, openIt } = await setup();
    openIt();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(cmp.amount()).toBe('200.00');
    expect(cmp.gremium()).toBe('g1');
    expect(cmp.gremiumOptions()).toEqual([{ value: 'g1', label: 'StuPa' }]);
  });

  it('starts with the requested amount when the approval was as requested', async () => {
    const { host, cmp, openIt } = await setup();
    host.approved.set(null);
    openIt();
    expect(cmp.amount()).toBe('250.00');
  });

  /** Spec 001620: a reason of at least 10 characters, a new amount, a date not after today. */
  it('checks the amount, the reason and the date', async () => {
    const { http, cmp, openIt, fill } = await setup();
    openIt();
    expect(cmp.amountError()).toBe('Der neue Betrag ist gleich dem bisherigen.');
    cmp.amount.set('-1');
    expect(cmp.amountError()).not.toBe('');
    cmp.amount.set('');
    expect(cmp.amountError()).toBe('');
    fill();
    cmp.reason.set('kurz');
    expect(cmp.reasonShort()).toBe(true);
    expect(cmp.ready()).toBe(false);
    cmp.reason.set('Mehrkosten Druck');
    cmp.date.set('2999-01-01');
    expect(cmp.dateError()).not.toBe('');
    cmp.submit();
    http.verify();
  });

  /** Spec 001622: an amount above the request is allowed, with a warning. */
  it('warns about an amount above the requested one and sends it', async () => {
    const { http, host, cmp, toast, openIt, fill, detectChanges } = await setup();
    const success = jest.spyOn(kindSpies(toast), 'success');
    openIt();
    fill();
    cmp.amount.set('300.00');
    detectChanges();
    expect(cmp.aboveRequested()).toBe(true);
    expect(screen.getByText('Der neue Betrag liegt über dem beantragten Betrag.')).toBeInTheDocument();
    cmp.submit();
    const post = http.expectOne((r) => r.method === 'POST' && r.url === URL);
    expect(post.request.body).toEqual({
      approvedAmount: '300.00',
      reason: 'Mehrkosten Druck',
      decisionDate: '2026-11-18',
      gremiumId: 'g1',
    });
    post.flush({ previousAmount: '200.00', approvedAmount: '300.00', decidedAt: '2026-11-19T10:00:00Z' });
    expect(host.open()).toBe(false);
    expect(host.done).toBe(1);
    expect(success).toHaveBeenCalled();
  });

  it('shows a refusal of the server in the dialog', async () => {
    const { http, cmp, openIt, fill } = await setup();
    openIt();
    fill();
    cmp.submit();
    http.expectOne(URL).flush({ code: 'gremium_unknown' }, { status: 422, statusText: 'x' });
    expect(cmp.refusal()).toBe('Das Gremium ist unbekannt.');
  });

  it.each([
    [409, true, { code: 'x' }],
    [403, false, { code: 'x' }],
    [422, false, { code: 'x' }],
    [500, false, null],
  ])('reports a %s answer', async (status, closes, body) => {
    const { http, host, cmp, toast, openIt, fill } = await setup();
    const error = jest.spyOn(kindSpies(toast), 'error');
    openIt();
    fill();
    cmp.submit();
    http.expectOne(URL).flush(body, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledTimes(1);
    expect(host.open()).toBe(!closes);
    cmp.close();
    expect(host.open()).toBe(false);
  });

  it('keeps an empty picker when the Gremien do not load', async () => {
    const { http, host, cmp, detectChanges } = await setup();
    host.open.set(true);
    detectChanges();
    http.expectOne('/api/committees').flush({}, { status: 500, statusText: 'x' });
    expect(cmp.gremiumOptions()).toEqual([]);
  });
});
