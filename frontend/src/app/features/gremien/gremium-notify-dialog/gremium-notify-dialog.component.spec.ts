import { render } from '@testing-library/angular';
import { throwError, of } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { gremienApiMock } from '../../../../testing/gremien-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { GremiumNotifyDialogComponent, messageError, subjectError } from './gremium-notify-dialog.component';

async function setup(api = gremienApiMock()) {
  localStorage.setItem('ap.locale', 'de');
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(GremiumNotifyDialogComponent, {
    inputs: { open: true, gremiumId: 'g-1', gremiumName: 'STUPA' },
    providers: [
      { provide: GremienApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const cmp = view.fixture.componentInstance;
  const closed = jest.fn();
  cmp.closed.subscribe(closed);
  return { ...view, api, toast, cmp, closed };
}

describe('gremium notify checks (§ 001854)', () => {
  it('needs a subject of at most 200 characters', () => {
    expect(subjectError('  ')).toBe('gremien.notify.subjectRequired');
    expect(subjectError('x'.repeat(201))).toBe('gremien.notify.subjectTooLong');
    expect(subjectError(' Klausur ')).toBeNull();
  });

  it('needs a message', () => {
    expect(messageError(' \n ')).toBe('gremien.notify.messageRequired');
    expect(messageError('Hallo')).toBeNull();
  });
});

describe('GremiumNotifyDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows the errors only after a send and sends nothing', async () => {
    const { cmp, api } = await setup();
    expect(cmp.subjectErr()).toBeNull();
    cmp.send();
    expect(cmp.subjectErr()).toBe('gremien.notify.subjectRequired');
    expect(cmp.messageErr()).toBe('gremien.notify.messageRequired');
    expect(cmp.text(cmp.messageErr())).toBe('Gib eine Nachricht ein.');
    expect(cmp.text(null)).toBe('');
    expect(api.notify).not.toHaveBeenCalled();
  });

  it('sends the trimmed message, tells the count and closes (§ 001850)', async () => {
    const { cmp, api, toast, closed } = await setup();
    cmp.subject.set(' Klausur ');
    cmp.message.set(' Bitte anmelden. ');
    cmp.send();
    expect(api.notify).toHaveBeenCalledWith('g-1', { subject: 'Klausur', message: 'Bitte anmelden.' });
    expect(toast.success).toHaveBeenCalledWith('Nachricht an 3 Personen gesendet.');
    expect(closed).toHaveBeenCalled();
    expect(cmp.sending()).toBe(false);
  });

  it('says 1 Person for one recipient', async () => {
    const { cmp, toast } = await setup(gremienApiMock({ notify: jest.fn(() => of({ recipients: 1 })) }));
    cmp.subject.set('A');
    cmp.message.set('B');
    cmp.send();
    expect(toast.success).toHaveBeenCalledWith('Nachricht an 1 Person gesendet.');
  });

  it('keeps the draft open after an error', async () => {
    const { cmp, toast, closed } = await setup(
      gremienApiMock({ notify: jest.fn(() => throwError(() => new Error('x'))) }),
    );
    cmp.subject.set('A');
    cmp.message.set('B');
    cmp.send();
    expect(toast.error).toHaveBeenCalledWith('Die Nachricht konnte nicht gesendet werden.');
    expect(closed).not.toHaveBeenCalled();
    expect(cmp.subject()).toBe('A');
  });

  it('closes on cancel and has no axe violations', async () => {
    const { cmp, closed, container } = await setup();
    expect(await runAxe(container as HTMLElement)).toHaveNoViolations();
    cmp.cancel();
    expect(closed).toHaveBeenCalled();
  });
});
