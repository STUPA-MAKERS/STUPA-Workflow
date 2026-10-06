import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { DeleteMeetingDialogComponent } from './delete-meeting-dialog.component';

const PLANNED = { id: 'm-1', title: '35. Sitzung', status: 'planned', protocolId: null } as unknown as Meeting;

async function setup(meeting: Meeting | null = PLANNED) {
  const closed = jest.fn();
  const deleted = jest.fn();
  const view = await render(DeleteMeetingDialogComponent, {
    inputs: { meeting },
    on: { closed, deleted },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, deleted, toasts };
}

const GET = { method: 'GET', url: '/api/meetings/m-1' };
const DELETE = { method: 'DELETE', url: '/api/meetings/m-1' };

/** Answer the count request of the dialog with `votes` votes. */
function flushCount(http: HttpTestingController, votes: number) {
  http.expectOne(GET).flush({ ...PLANNED, gremiumId: 'g-1', votes: Array.from({ length: votes }, (_, i) => ({ id: `v-${i}` })) });
}

describe('DeleteMeetingDialogComponent', () => {
  it('names what goes with a planned meeting and offers an outlined danger button', async () => {
    const { http } = await setup();
    flushCount(http, 0);
    expect(screen.getByRole('dialog', { name: 'Sitzung löschen' })).toBeInTheDocument();
    expect(
      screen.getByText(
        '„35. Sitzung“ wird mit Tagesordnung, Anwesenheit und Vertretungen gelöscht. Das kann nicht rückgängig gemacht werden.',
      ),
    ).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: 'Endgültig löschen' });
    expect(confirm).toHaveClass('btn--danger');
    expect(confirm).not.toHaveClass('btn--fill');
    // Without votes the dialog names none.
    expect(screen.queryByText(/Abstimmung/)).toBeNull();
  });

  it('names the number of votes that go with the meeting', async () => {
    const { http, cmp, detectChanges } = await setup();
    expect(cmp.votesText()).toBeNull(); // still loading
    flushCount(http, 3);
    detectChanges();
    expect(screen.getByText('Mit der Sitzung werden 3 Abstimmungen gelöscht.')).toBeInTheDocument();
    cmp.voteCount.set(1);
    expect(cmp.votesText()).toBe('Mit der Sitzung wird 1 Abstimmung gelöscht.');
  });

  it('says that all votes go when the count does not load', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(GET).flush(null, { status: 500, statusText: 'x' });
    detectChanges();
    expect(screen.getByText('Mit der Sitzung werden alle ihre Abstimmungen gelöscht.')).toBeInTheDocument();
  });

  it('drops a late answer for a meeting that is no longer in the dialog', async () => {
    const { http, cmp, fixture } = await setup();
    const first = http.expectOne(GET);
    fixture.componentRef.setInput('meeting', { ...PLANNED, id: 'm-2' });
    fixture.detectChanges();
    const second = http.expectOne({ method: 'GET', url: '/api/meetings/m-2' });
    // The answers of m-1 come late: a count and an error change nothing.
    first.flush({ ...PLANNED, votes: [{ id: 'v-1' }, { id: 'v-2' }] });
    expect(cmp.voteCount()).toBeNull();
    fixture.componentRef.setInput('meeting', { ...PLANNED, id: 'm-3' });
    fixture.detectChanges();
    second.flush(null, { status: 500, statusText: 'x' });
    expect(cmp.countFailed()).toBe(false);
    http.expectOne({ method: 'GET', url: '/api/meetings/m-3' }).flush({ ...PLANNED, votes: [] });
    expect(cmp.voteCount()).toBe(0);
  });

  it('deletes the meeting and reports it', async () => {
    const { http, deleted, toasts } = await setup();
    flushCount(http, 2);
    await userEvent.click(screen.getByRole('button', { name: 'Endgültig löschen' }));
    const req = http.expectOne(DELETE);
    req.flush(null, { status: 204, statusText: 'No Content' });
    expect(deleted).toHaveBeenCalledWith('m-1');
    expect(toasts()).toContain('Sitzung gelöscht.');
  });

  it('names the open vote, another refusal and a bare error', async () => {
    const { http, cmp, deleted, toasts } = await setup();
    flushCount(http, 1);
    cmp.confirm();
    cmp.confirm(); // one request at a time
    http.expectOne(DELETE).flush({ code: 'open_vote' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain(
      'Eine Abstimmung der Sitzung ist noch offen. Bitte die Abstimmung zuerst schließen oder abbrechen.',
    );
    cmp.confirm();
    http
      .expectOne(DELETE)
      .flush({ detail: 'final protocol' }, { status: 403, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: final protocol');
    cmp.confirm();
    http.expectOne(DELETE).flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
    expect(deleted).not.toHaveBeenCalled();
    expect(cmp.deleting()).toBe(false);
  });

  it('has no axe violations', async () => {
    const { http, detectChanges } = await setup();
    flushCount(http, 2);
    detectChanges();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('closes on cancel', async () => {
    const { closed } = await setup();
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
  });

  it('stays closed and sends nothing without a meeting', async () => {
    const { http, cmp } = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    cmp.confirm();
    http.verify();
  });
});
