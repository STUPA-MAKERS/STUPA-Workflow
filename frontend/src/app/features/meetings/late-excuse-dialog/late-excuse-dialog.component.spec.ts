import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { LATE_EXCUSE_NOTE_MAX, LateExcuseDialogComponent } from './late-excuse-dialog.component';

const URL = '/api/meetings/m-1/attendance/me/late-excuse';

async function setup(meetingId: string | null = 'm-1') {
  const closed = jest.fn();
  const excused = jest.fn();
  const view = await render(LateExcuseDialogComponent, {
    inputs: { meetingId },
    on: { closed, excused },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, excused, toasts };
}

/** § 000922 */
describe('LateExcuseDialogComponent', () => {
  it('stays closed without a meeting', async () => {
    const { http, cmp } = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    cmp.save();
    http.verify();
  });

  it('needs a reason, sends it and hands the new roster on', async () => {
    const { http, excused, toasts, container } = await setup();
    const dialog = screen.getByRole('dialog', { name: 'Nachträglich entschuldigen' });
    expect(dialog).not.toHaveAccessibleDescription();
    const submit = screen.getByRole('button', { name: 'Entschuldigen' });
    expect(submit).toBeDisabled();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.type(screen.getByLabelText(/Grund/), ' Krank ');
    await userEvent.click(submit);
    const req = http.expectOne(URL);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ note: 'Krank' });
    req.flush([{ principalId: 'p-1', status: 'excused' }]);
    expect(excused).toHaveBeenCalledWith([{ principalId: 'p-1', status: 'excused' }]);
    expect(toasts()).toContain('Entschuldigung gespeichert.');
  });

  it('refuses a reason that is too long and sends nothing while a send runs', async () => {
    const { http, cmp, fixture } = await setup();
    cmp.note.set('x'.repeat(LATE_EXCUSE_NOTE_MAX + 1));
    fixture.detectChanges();
    expect(screen.getByLabelText(/Grund/)).toHaveAttribute('maxlength', String(LATE_EXCUSE_NOTE_MAX));
    expect(screen.getByRole('button', { name: 'Entschuldigen' })).toBeDisabled();
    cmp.save();
    http.expectNone(URL);
    cmp.note.set('Krank');
    cmp.save();
    cmp.save();
    expect(http.match(URL)).toHaveLength(1);
  });

  it.each([
    ['late_excuse_expired', 'Die Frist für eine nachträgliche Entschuldigung ist abgelaufen.'],
    ['not_absent', 'Nur eine Abwesenheit kann nachträglich entschuldigt werden.'],
    ['other', 'Aktion fehlgeschlagen.'],
  ])('names the cause of a refusal (%s)', async (code, text) => {
    const { http, cmp, excused, closed, toasts } = await setup();
    cmp.note.set('Krank');
    cmp.save();
    http.expectOne(URL).flush({ code }, { status: 409, statusText: 'Conflict' });
    expect(toasts()).toContain(text);
    expect(excused).not.toHaveBeenCalled();
    expect(cmp.saving()).toBe(false);
    expect(closed).toHaveBeenCalledTimes(code === 'other' ? 0 : 1);
  });

  it('closes on "Abbrechen" and starts empty on the next opening', async () => {
    const { cmp, closed, fixture } = await setup();
    cmp.note.set('Krank');
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(closed).toHaveBeenCalled();
    fixture.componentRef.setInput('meetingId', 'm-2');
    fixture.detectChanges();
    expect(cmp.note()).toBe('');
  });
});
