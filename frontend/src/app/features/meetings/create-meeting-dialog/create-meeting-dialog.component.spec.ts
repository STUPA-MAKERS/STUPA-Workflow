import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { MeetingMember } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { CreateMeetingDialogComponent } from './create-meeting-dialog.component';

const GREMIEN = [
  { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa' },
  { id: 'g-2', name: 'Finanzausschuss', slug: 'fa' },
];

const MEMBERS: MeetingMember[] = [
  { principalId: 'p-1', displayName: 'Mara Keller', email: 'mara@x.de', canKeepProtocol: true },
  { principalId: 'p-2', displayName: 'Tom Brandt', email: 'tom@x.de', canKeepProtocol: false },
  { principalId: 'p-3', displayName: null, email: 'lea@x.de', canKeepProtocol: true },
  { principalId: 'p-4', displayName: null, email: null, canKeepProtocol: true },
];

function fakeAuth(admin: boolean, managed: string[]): Partial<AuthService> {
  return {
    isAdmin: (() => admin) as unknown as AuthService['isAdmin'],
    sessionManageGremien: (() => managed) as unknown as AuthService['sessionManageGremien'],
  };
}

async function setup(
  opts: { admin?: boolean; managed?: string[]; gremiumId?: string; open?: boolean } = {},
) {
  const closed = jest.fn();
  const navigate = jest.fn(() => Promise.resolve(true));
  const view = await render(CreateMeetingDialogComponent, {
    inputs: { open: opts.open ?? true, gremiumId: opts.gremiumId ?? '' },
    on: { closed },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts.admin ?? true, opts.managed ?? []) },
      { provide: Router, useValue: { navigate } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const cmp = view.fixture.componentInstance;
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp, closed, navigate, toasts };
}

function flushGremien(
  http: HttpTestingController,
  fixture: { detectChanges(): void },
  rows = GREMIEN,
): void {
  http.expectOne('/api/gremien').flush(rows);
  fixture.detectChanges();
}

describe('CreateMeetingDialogComponent', () => {
  it('asks in step 1 for the Gremium, the date, the start and an optional end', async () => {
    const { http, fixture } = await setup();
    flushGremien(http, fixture);
    const dialog = screen.getByRole('dialog', { name: 'Sitzung anlegen' });
    expect(within(dialog).getByText('Schritt 1 von 2')).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Gremium/)).toBeInTheDocument();
    expect(within(dialog).getByText('Geplantes Datum')).toBeInTheDocument();
    expect(within(dialog).getByText('Uhrzeit')).toBeInTheDocument();
    expect(within(dialog).getByText('Ende (optional)')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Weiter' })).toBeDisabled();
  });

  it('goes to step 2 with a prefilled title and lists only members who can keep the minutes (O20)', async () => {
    const { http, cmp, fixture } = await setup();
    flushGremien(http, fixture);
    await userEvent.selectOptions(screen.getByLabelText(/Gremium/), 'g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush(MEMBERS);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));

    expect(screen.getByText('Schritt 2 von 2')).toBeInTheDocument();
    expect(cmp.title()).toBe('Sitzung des Studierendenparlament am 10. November 2026');
    const keeper = screen.getByLabelText('Protokollführung');
    const names = within(keeper).getAllByRole('option').map((o) => o.textContent?.trim());
    // Tom has no protocol.write; the fallbacks are the e-mail and the id.
    expect(names).toEqual(['— niemand —', 'Mara Keller', 'lea@x.de', 'p-4']);
  });

  it('creates the meeting, closes and opens its page', async () => {
    const { http, cmp, fixture, closed, navigate, toasts } = await setup();
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush(MEMBERS);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.endTime.set('20:00');
    cmp.next();
    cmp.keeper.set('p-1');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung anlegen' }));

    const req = http.expectOne('/api/meetings');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      title: 'Sitzung des Studierendenparlament am 10. November 2026',
      gremiumId: 'g-1',
      date: '2026-11-10',
      startTime: '18:00',
      endTime: '20:00',
      protokollantId: 'p-1',
    });
    req.flush({ id: 'm-9', title: 'x', status: 'planned', votes: [], createdAt: '2026-10-01T00:00:00Z' });
    expect(closed).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(['/meetings', 'm-9']);
    expect(toasts()).toContain('Sitzung angelegt.');
  });

  it('sends no end and no minute-taker when none is set, and reports a failed create', async () => {
    const { http, cmp, closed, toasts, fixture } = await setup();
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-2');
    http.expectOne('/api/gremien/g-2/meeting-members').flush([]);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.submit(); // step 1: the submit goes to step 2
    expect(cmp.step()).toBe(2);
    cmp.submit();
    cmp.submit(); // a second submit while the first runs is ignored
    const req = http.expectOne('/api/meetings');
    expect(req.request.body.endTime).toBeNull();
    expect(req.request.body.protokollantId).toBeNull();
    req.flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
    expect(cmp.creating()).toBe(false);
    expect(closed).not.toHaveBeenCalled();
    expect(toasts()).toContain('Sitzung konnte nicht angelegt werden.');
  });

  it('keeps step 1 when the end is before the start, or when a field is missing', async () => {
    const { http, cmp, toasts, fixture } = await setup();
    flushGremien(http, fixture);
    cmp.next(); // nothing set
    expect(cmp.step()).toBe(1);
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.endTime.set('17:00');
    cmp.next();
    expect(cmp.step()).toBe(1);
    expect(toasts()).toContain('Die End-Uhrzeit muss nach der Start-Uhrzeit liegen.');
  });

  it('keeps a title that the user typed, and goes back to step 1', async () => {
    const { http, cmp, fixture } = await setup();
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.next();
    cmp.title.set('Sondersitzung');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(cmp.step()).toBe(1);
    cmp.date.set('2026-11-17');
    cmp.next();
    expect(cmp.title()).toBe('Sondersitzung');
  });

  it('follows the new date while the title is still the prefill', async () => {
    const { http, cmp, fixture } = await setup();
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.next();
    cmp.back();
    cmp.date.set('2026-11-17');
    cmp.next();
    expect(cmp.title()).toBe('Sitzung des Studierendenparlament am 17. November 2026');
  });

  it('offers a non-admin only the Gremien with session.manage', async () => {
    const { http, fixture } = await setup({ admin: false, managed: ['g-2'] });
    flushGremien(http, fixture);
    const options = within(screen.getByLabelText(/Gremium/)).getAllByRole('option');
    expect(options.map((o) => o.textContent?.trim())).toEqual(['Gremium wählen …', 'Finanzausschuss']);
  });

  it('says so when there is no Gremium to choose, also when the list fails', async () => {
    const { http, fixture } = await setup();
    http.expectOne('/api/gremien').flush(null, { status: 500, statusText: 'e' });
    fixture.detectChanges();
    expect(screen.getByRole('status')).toHaveTextContent('Kein Gremium verfügbar');
  });

  it('preselects the Gremium of the list filter', async () => {
    const { http, cmp, fixture } = await setup({ gremiumId: 'g-1' });
    http.expectOne('/api/gremien/g-1/meeting-members').flush(MEMBERS);
    flushGremien(http, fixture);
    expect(cmp.gremium()).toBe('g-1');
    expect(cmp.members()).toEqual(MEMBERS);
  });

  it('drops a preselected Gremium that the user cannot manage', async () => {
    const { http, cmp, fixture } = await setup({ gremiumId: 'g-9' });
    http.expectOne('/api/gremien/g-9/meeting-members').flush(MEMBERS);
    flushGremien(http, fixture);
    expect(cmp.gremium()).toBe('');
    expect(cmp.members()).toEqual([]);
  });

  it('starts empty on every opening and loads the Gremien once', async () => {
    const { http, cmp, fixture } = await setup({ open: false });
    http.expectNone('/api/gremien');
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
    cmp.date.set('2026-11-10');
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    fixture.componentRef.setInput('gremiumId', 'g-2');
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    http.expectNone('/api/gremien');
    http.expectOne('/api/gremien/g-2/meeting-members').flush([]);
    expect(cmp.date()).toBe('');
    expect(cmp.gremium()).toBe('g-2');
  });

  it('drops a members answer for a Gremium that the user changed since, and an error', async () => {
    const { http, cmp, fixture } = await setup();
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-1');
    const stale = http.expectOne('/api/gremien/g-1/meeting-members');
    cmp.onGremiumChange('g-2');
    stale.flush(MEMBERS);
    expect(cmp.members()).toEqual([]);
    http.expectOne('/api/gremien/g-2/meeting-members').flush(null, { status: 500, statusText: 'e' });
    expect(cmp.members()).toEqual([]);
    cmp.onGremiumChange('');
    http.expectNone((r) => r.url.includes('meeting-members'));
  });

  it('has no axe violations in both steps', async () => {
    const { http, cmp, fixture } = await setup();
    flushGremien(http, fixture);
    expect(await runAxe(document.body)).toHaveNoViolations();
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush(MEMBERS);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.next();
    fixture.detectChanges();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('closes on cancel without a request', async () => {
    const { http, closed, fixture } = await setup();
    flushGremien(http, fixture);
    // The footer button; the round close button of the dialog has the same name.
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
    http.verify();
  });

  it('prints the prefilled date in English for the English locale', async () => {
    const { http, cmp, fixture } = await setup();
    fixture.debugElement.injector.get(I18nService).setLocale('en');
    flushGremien(http, fixture);
    cmp.onGremiumChange('g-1');
    http.expectOne('/api/gremien/g-1/meeting-members').flush([]);
    cmp.date.set('2026-11-10');
    cmp.time.set('18:00');
    cmp.next();
    expect(cmp.title()).toBe('Studierendenparlament meeting on 10 November 2026');
  });
});
