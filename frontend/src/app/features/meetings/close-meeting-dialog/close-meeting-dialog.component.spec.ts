import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting, MeetingVote } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { CloseMeetingDialogComponent } from './close-meeting-dialog.component';

const vote = (status: MeetingVote['status']): MeetingVote =>
  ({ id: `v-${status}`, status }) as unknown as MeetingVote;

const LIVE = {
  id: 'm-1',
  title: '34. Sitzung',
  status: 'live',
  votes: [vote('closed')],
  canFinalize: true,
} as unknown as Meeting;

async function setup(meeting: Meeting = LIVE, open = true) {
  const closed = jest.fn();
  const meetingClosed = jest.fn();
  const view = await render(CloseMeetingDialogComponent, {
    inputs: { meeting, open },
    on: { closed, meetingClosed },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, meetingClosed, toasts };
}

describe('CloseMeetingDialogComponent', () => {
  it('lists what the close needs and does, and closes with an outlined danger button', async () => {
    await setup();
    const dialog = screen.getByRole('dialog', { name: 'Sitzung schließen?' });
    expect(dialog).toHaveAccessibleDescription('34. Sitzung');
    expect(screen.getByText(/Das Schließen ist unwiderruflich/)).toBeInTheDocument();
    expect(screen.getByText('Keine offene Abstimmung')).toBeInTheDocument();
    expect(screen.getByText('Das Protokoll finalisierst du danach als eigenen Schritt')).toBeInTheDocument();
    // No draft vote: no line about cancelled votes.
    expect(screen.queryByText('Geplante Abstimmungen werden abgebrochen')).toBeNull();
    const confirm = screen.getByRole('button', { name: 'Sitzung schließen' });
    expect(confirm).toHaveClass('btn--danger');
    expect(confirm).toBeEnabled();
  });

  it('says that the planned votes are cancelled, and who finalizes without the right', async () => {
    await setup({ ...LIVE, votes: [vote('draft')], canFinalize: false } as Meeting);
    expect(screen.getByText('Geplante Abstimmungen werden abgebrochen')).toBeInTheDocument();
    expect(screen.getByText(/finalisiert danach, wer das Recht „Protokoll finalisieren“ hat/)).toBeInTheDocument();
  });

  it('blocks the close while a vote is open (O12)', async () => {
    const { http, cmp } = await setup({ ...LIVE, votes: [vote('open')] } as Meeting);
    expect(screen.getByRole('alert')).toHaveTextContent('Eine Abstimmung ist noch offen');
    expect(screen.getByRole('button', { name: 'Sitzung schließen' })).toBeDisabled();
    cmp.confirm();
    http.verify();
  });

  it('closes with one PATCH and never finalizes the protocol (O13)', async () => {
    const { http, meetingClosed, toasts } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung schließen' }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ status: 'closed' });
    req.flush({ id: 'm-1', title: '34. Sitzung', status: 'closed', votes: [], createdAt: 'x' });
    http.expectNone((r) => r.url.includes('/protocols/'));
    expect(meetingClosed).toHaveBeenCalledWith(expect.objectContaining({ status: 'closed' }));
    expect(toasts()).toContain('Sitzung geschlossen.');
  });

  it('shows the 409 open_vote reason in the list when a vote opened meanwhile', async () => {
    const { http, cmp, fixture, meetingClosed } = await setup();
    cmp.confirm();
    cmp.confirm(); // one request at a time
    http.expectOne('/api/meetings/m-1').flush({ code: 'open_vote' }, { status: 409, statusText: 'x' });
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Eine Abstimmung ist noch offen');
    expect(screen.getByRole('button', { name: 'Sitzung schließen' })).toBeDisabled();
    expect(meetingClosed).not.toHaveBeenCalled();
    // A new opening starts without the refusal.
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    expect(screen.getByText('Keine offene Abstimmung')).toBeInTheDocument();
  });

  it('clears the 409 refusal when a new meeting state shows no open vote', async () => {
    const { http, cmp, fixture } = await setup();
    cmp.confirm();
    http.expectOne('/api/meetings/m-1').flush({ code: 'open_vote' }, { status: 409, statusText: 'x' });
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Sitzung schließen' })).toBeDisabled();
    // The other tab opened the vote: the push shows it, the close stays blocked.
    fixture.componentRef.setInput('meeting', { ...LIVE, votes: [vote('open')] });
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Sitzung schließen' })).toBeDisabled();
    // The other tab closed the vote again: the close is possible without a new opening.
    fixture.componentRef.setInput('meeting', { ...LIVE, votes: [vote('closed')] });
    fixture.detectChanges();
    expect(screen.getByText('Keine offene Abstimmung')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sitzung schließen' })).toBeEnabled();
  });

  it('shows another refusal as a toast', async () => {
    const { http, cmp, toasts } = await setup();
    cmp.confirm();
    http.expectOne('/api/meetings/m-1').flush({ detail: 'nein' }, { status: 403, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: nein');
    cmp.confirm();
    http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
  });

  it('closes only a live meeting, and cancels', async () => {
    const { http, cmp, closed } = await setup({ ...LIVE, status: 'planned' } as Meeting);
    cmp.confirm();
    http.verify();
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    await setup({ ...LIVE, votes: [vote('open'), vote('draft')] } as Meeting);
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('renders nothing while closed', async () => {
    await setup(LIVE, false);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
