import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError, type Observable } from 'rxjs';
import {
  TicketsApiService,
  type TicketArea,
  type TicketMailbox,
  type TicketMailboxTest,
} from '@core/api/tickets.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastWith } from '../../../../testing/load-error';
import {
  TicketMailboxDialogComponent,
  draftErrors,
  draftOf,
  mailboxBody,
} from './ticket-mailbox-dialog.component';

const ASTA: TicketArea = {
  id: 'a-asta',
  name: 'AStA-Büro',
  gremiumId: 'g1',
  platform: false,
  notifyNew: false,
  inApp: false,
  categories: [],
  mine: true,
};
const BOX: TicketMailbox = {
  areaId: 'a-asta',
  address: 'buero@example.org',
  imapHost: 'mail.example.org',
  imapPort: 993,
  imapUser: 'buero',
  smtpHost: 'smtp.example.org',
  smtpPort: 587,
  smtpUser: 'buero',
  doneFolder: 'Erledigt',
  enabled: false,
};

/** The methods of the dialog that a test calls directly. */
interface Inner {
  patch(part: Record<string, unknown>): void;
  patchField(field: string, value: unknown): void;
  onAction(key: string): void;
  doDelete(): void;
  confirmDelete(): boolean;
  errors(): Record<string, string>;
  dirty(): boolean;
}

async function setup(mailbox: TicketMailbox | null = null, hosts: string[] = ['mail.example.org']) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    createMailbox: jest.fn((_id: string, b: object): Observable<TicketMailbox> => of({ ...BOX, ...b })),
    updateMailbox: jest.fn((_id: string, b: object): Observable<TicketMailbox> => of({ ...BOX, ...b })),
    deleteMailbox: jest.fn((): Observable<void> => of(undefined)),
    testMailbox: jest.fn(
      (): Observable<TicketMailboxTest> =>
        of({ imap: { ok: true }, smtp: { ok: false, error: 'login_failed' } }),
    ),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const saved = jest.fn();
  const deleted = jest.fn();
  const closed = jest.fn();
  const view = await render(TicketMailboxDialogComponent, {
    inputs: { open: true, area: ASTA, mailbox, allowedHosts: hosts },
    on: { saved, deleted, closed },
    providers: [
      { provide: TicketsApiService, useValue: api },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance as unknown as Inner;
  const act = async (fn: () => void) => {
    fn();
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  return { ...view, cmp, act, api, toast, saved, deleted, closed };
}

const FULL = {
  address: 'buero@example.org',
  imapHost: 'Mail.Example.org ',
  imapUser: 'buero',
  imapPassword: 'geheim-1',
  smtpHost: 'smtp.example.org',
  smtpUser: 'buero',
  smtpPassword: 'geheim-2',
};

describe('the draft of a Postfach', () => {
  it('keeps the signature and the switch "Eingang bestätigen"', () => {
    expect(draftOf(null)).toMatchObject({ signature: '', confirm: false });
    const draft = draftOf({ ...BOX, signature: 'Viele Grüße\n{name}', confirm: true });
    expect(draft).toMatchObject({ signature: 'Viele Grüße\n{name}', confirm: true });
    expect(mailboxBody({ ...draft, signature: ' Dein AStA \n' })).toMatchObject({
      signature: 'Dein AStA',
      confirm: true,
    });
  });

  it('starts a new Postfach with the TLS ports, the folder and the switch off', () => {
    expect(draftOf(null)).toMatchObject({
      imapPort: '993',
      smtpPort: '465',
      doneFolder: 'Erledigt',
      enabled: false,
      imapPassword: '',
    });
  });

  it('never fills a password from a stored Postfach', () => {
    expect(draftOf(BOX)).toMatchObject({ imapPassword: '', smtpPassword: '', smtpPort: '587' });
  });

  it('asks for each field of a new Postfach, and for no password of a stored one', () => {
    expect(Object.keys(draftErrors(draftOf(null), null)).sort()).toEqual([
      'address',
      'imapHost',
      'imapPassword',
      'imapUser',
      'smtpHost',
      'smtpPassword',
      'smtpUser',
    ]);
    expect(draftErrors(draftOf(BOX), draftOf(BOX))).toEqual({});
  });

  it('refuses a bad address and a bad port', () => {
    const draft = { ...draftOf(BOX), address: 'kein', imapPort: '0', smtpPort: '70000' };
    expect(draftErrors(draft, draftOf(BOX))).toEqual({
      address: 'admin.helpTickets.mailbox.addressInvalid',
      imapPort: 'admin.helpTickets.mailbox.portInvalid',
      smtpPort: 'admin.helpTickets.mailbox.portInvalid',
      imapPassword: 'admin.helpTickets.mailbox.passwordAgain',
      smtpPassword: 'admin.helpTickets.mailbox.passwordAgain',
    });
    expect(draftErrors({ ...draftOf(BOX), imapPort: 'abc' }, draftOf(BOX))).toHaveProperty('imapPort');
  });

  /** § F/integrations/ticket-mail/002812: a stored password does not follow a change. */
  it('asks for the password again when host, port or user of an account changes', () => {
    const stored = draftOf(BOX);
    expect(draftErrors({ ...stored, imapHost: 'other.example.org' }, stored)).toEqual({
      imapPassword: 'admin.helpTickets.mailbox.passwordAgain',
    });
    expect(draftErrors({ ...stored, smtpPort: '465', imapUser: 'x' }, stored)).toEqual({
      imapPassword: 'admin.helpTickets.mailbox.passwordAgain',
      smtpPassword: 'admin.helpTickets.mailbox.passwordAgain',
    });
    expect(draftErrors({ ...stored, imapUser: 'x', imapPassword: 'neu' }, stored)).toEqual({});
    expect(draftErrors({ ...stored, imapHost: ' MAIL.example.org ' }, stored)).toEqual({});
  });

  it('sends a password only when the person typed one', () => {
    const body = mailboxBody({ ...draftOf(BOX), imapHost: ' Mail.Example.org ', smtpPassword: 'neu' });
    expect(body).toMatchObject({ imapHost: 'mail.example.org', imapPort: 993, smtpPassword: 'neu' });
    expect(body).not.toHaveProperty('imapPassword');
  });
});

describe('TicketMailboxDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('names the Bereich and shows password fields that are empty', async () => {
    await setup(BOX);
    expect(screen.getByRole('dialog', { name: /Postfach/ })).toHaveTextContent('AStA-Büro');
    const passwords = screen.getAllByLabelText(/Neues Passwort/) as HTMLInputElement[];
    expect(passwords.map((p) => [p.type, p.value])).toEqual([
      ['password', ''],
      ['password', ''],
    ]);
    expect((screen.getByLabelText(/E-Mail-Adresse/) as HTMLInputElement).value).toBe(
      'buero@example.org',
    );
  });

  it('names the missing fields of a new Postfach and does not save', async () => {
    const { cmp, act, api } = await setup();
    expect(screen.queryByRole('button', { name: 'Verbindung testen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Postfach entfernen' })).toBeNull();
    await act(() => cmp.onAction('save'));
    expect(api.createMailbox).not.toHaveBeenCalled();
    expect(cmp.errors()['address']).toBe('Bitte ausfüllen.');
    expect(cmp.errors()['imapPassword']).toBe('Bitte ausfüllen.');
  });

  it('creates a Postfach with both passwords', async () => {
    const { cmp, act, api, saved } = await setup();
    await act(() => cmp.patch(FULL));
    await act(() => cmp.patchField('smtpPort', 587));
    await act(() => cmp.patchField('doneFolder', null));
    await act(() => cmp.patchField('doneFolder', 'Archiv'));
    await act(() => cmp.onAction('save'));
    expect(api.createMailbox).toHaveBeenCalledWith('a-asta', {
      address: 'buero@example.org',
      imapHost: 'mail.example.org',
      imapPort: 993,
      imapUser: 'buero',
      imapPassword: 'geheim-1',
      smtpHost: 'smtp.example.org',
      smtpPort: 587,
      smtpUser: 'buero',
      smtpPassword: 'geheim-2',
      doneFolder: 'Archiv',
      enabled: false,
      signature: '',
      confirm: false,
    });
    expect(saved).toHaveBeenCalledTimes(1);
  });

  it('changes a stored Postfach without its passwords, once while the save runs', async () => {
    const { cmp, act, api, saved } = await setup(BOX);
    const pending = new Subject<TicketMailbox>();
    api.updateMailbox.mockReturnValueOnce(pending);
    await act(() => cmp.patch({ enabled: true }));
    await act(() => cmp.onAction('save'));
    await act(() => cmp.onAction('save'));
    expect(api.updateMailbox).toHaveBeenCalledTimes(1);
    const body = api.updateMailbox.mock.calls[0][1] as Record<string, unknown>;
    expect(body).toMatchObject({ enabled: true });
    expect(body).not.toHaveProperty('imapPassword');
    expect(body).not.toHaveProperty('smtpPassword');
    pending.next({ ...BOX, enabled: true });
    expect(saved).toHaveBeenCalledWith({ ...BOX, enabled: true });
  });

  it('names the allowed hosts under a host that the server refused', async () => {
    const { cmp, act, api, toast } = await setup(BOX, ['mail.example.org', 'smtp.example.org:587']);
    api.updateMailbox.mockReturnValueOnce(
      throwError(() => ({
        status: 422,
        error: { code: 'mail_host_not_allowed', errors: [{ field: 'imapHost' }] },
      })),
    );
    await act(() => cmp.patch({ imapHost: 'intern.local', imapPassword: 'geheim' }));
    await act(() => cmp.onAction('save'));
    expect(cmp.errors()).toEqual({
      imapHost:
        'Der Betreiber hat diesen Server nicht erlaubt. Erlaubt: mail.example.org, smtp.example.org:587',
    });
    expect(toast.error).not.toHaveBeenCalled();
    await act(() => cmp.patch({ imapHost: 'mail.example.org' }));
    expect(cmp.errors()).toEqual({});
  });

  it('asks for the password again before it saves a new host', async () => {
    const { cmp, act, api } = await setup(BOX);
    await act(() => cmp.patch({ smtpUser: 'office' }));
    await act(() => cmp.onAction('save'));
    expect(api.updateMailbox).not.toHaveBeenCalled();
    expect(cmp.errors()).toEqual({
      smtpPassword: 'Bei neuem Host, Port oder Benutzer bitte das Passwort erneut eingeben.',
    });
  });

  it.each([
    ['ticket_mailbox_exists', 'Dieser Bereich hat schon ein Postfach.'],
    ['', 'Das Postfach konnte nicht gespeichert werden.'],
  ])('names a failed save (%s)', async (code, text) => {
    const { cmp, act, api, toast } = await setup(BOX);
    api.updateMailbox.mockReturnValueOnce(throwError(() => ({ status: 409, error: code ? { code } : null })));
    await act(() => cmp.onAction('save'));
    expect(toast.error).toHaveBeenCalledWith(text);
  });

  it('tests the stored Postfach and shows the result of each connection', async () => {
    const { api } = await setup(BOX);
    await userEvent.click(screen.getByRole('button', { name: 'Verbindung testen' }));
    expect(api.testMailbox).toHaveBeenCalledWith('a-asta');
    const lines = screen.getAllByRole('status').map((n) => n.textContent?.trim());
    expect(lines).toEqual([
      'Posteingang: Anmeldung hat geklappt.',
      'Postausgang: Benutzer oder Passwort stimmen nicht.',
    ]);
  });

  it('does not test a draft with a change, and drops the result with the next change', async () => {
    const { cmp, act, api } = await setup(BOX);
    await act(() => cmp.onAction('test'));
    expect(screen.getAllByRole('status')).toHaveLength(2);
    await act(() => cmp.patch({ imapUser: 'office' }));
    expect(screen.queryAllByRole('status')).toHaveLength(0);
    expect(cmp.dirty()).toBe(true);
    expect(screen.getByRole('button', { name: 'Verbindung testen' })).toBeDisabled();
    await act(() => cmp.onAction('test'));
    expect(api.testMailbox).toHaveBeenCalledTimes(1);
  });

  it('names a test that could not run and an unknown cause', async () => {
    const { cmp, act, api, toast } = await setup(BOX);
    api.testMailbox.mockReturnValueOnce(throwError(() => new Error('x')));
    await act(() => cmp.onAction('test'));
    expect(toast.error).toHaveBeenCalledWith('Der Test konnte nicht laufen.');
    api.testMailbox.mockReturnValueOnce(of({ imap: { ok: false, error: 'new_code' }, smtp: { ok: true } }));
    await act(() => cmp.onAction('test'));
    expect(screen.getAllByRole('status')[0]).toHaveTextContent('Posteingang: Unbekannter Fehler.');
  });

  it('shows the error of the fetch and a note without allowed hosts', async () => {
    await setup({ ...BOX, error: 'tls_failed' }, []);
    expect(
      screen.getByText('Der Abruf schlägt fehl: Das Zertifikat des Servers ist nicht gültig.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/TICKET_MAIL_HOST_ALLOWLIST/)).toBeInTheDocument();
  });

  it('removes the Postfach after a question, and names a failure', async () => {
    const { cmp, act, api, deleted, toast, closed } = await setup(BOX);
    await act(() => cmp.onAction('delete'));
    expect(cmp.confirmDelete()).toBe(true);
    expect(api.deleteMailbox).not.toHaveBeenCalled();
    api.deleteMailbox.mockReturnValueOnce(throwError(() => new Error('x')));
    await act(() => cmp.doDelete());
    expect(toast.error).toHaveBeenCalledWith('Das Postfach konnte nicht entfernt werden.');
    await act(() => cmp.doDelete());
    expect(deleted).toHaveBeenCalledWith(ASTA);
    await act(() => cmp.onAction('cancel'));
    expect(closed).toHaveBeenCalled();
  });
});
