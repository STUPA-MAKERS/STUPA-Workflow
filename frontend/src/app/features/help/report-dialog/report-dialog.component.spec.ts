import { HttpErrorResponse } from '@angular/common/http';
import { computed, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError } from 'rxjs';
import { TicketsApiService, type TicketCreate, type TicketCreated } from '@core/api/tickets.service';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { ThemeService } from '@core/theme/theme.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AltchaService } from '../../apply/altcha.service';
import { DraftAttachmentsService, type DraftFile, type PendingUpload } from '../../apply/draft-attachments.service';
import type { UploadFailure } from '../../apply/draft-attachments.service';
import { HelpService } from '../help.service';
import type { ReportEnv } from '../report-context';
import { MAX_TICKET_FILES, ReportDialogComponent } from './report-dialog.component';

class FakeDrafts {
  readonly files = signal<DraftFile[]>([]);
  readonly pending = signal<PendingUpload[]>([]);
  readonly busy = computed(() => this.pending().length > 0);
  readonly count = computed(() => this.files().filter((f) => !f.failed).length);
  failures: UploadFailure[] = [];
  readonly upload = jest.fn(async (files: readonly File[]) => {
    this.files.update((list) => [...list, ...files.map((f, i) => fileOf(`${list.length + i}`, f.name, f.type))]);
    return { failed: this.failures };
  });
  removeOk = true;
  readonly remove = jest.fn(async (id: string) => {
    if (this.removeOk) this.files.update((list) => list.filter((f) => f.id !== id));
    return this.removeOk;
  });
  readonly discard = jest.fn(async () => undefined);
  readonly clear = jest.fn(() => this.files.set([]));
  markedIds: string[] = [];
  readonly markFailed = jest.fn(() => this.markedIds);
  attachmentIds(): string[] {
    return this.files().map((f) => f.id);
  }
  token(): string {
    return 'draft-token';
  }
}

function fileOf(id: string, filename = `f${id}.png`, mime = 'image/png', extra: Partial<DraftFile> = {}): DraftFile {
  return {
    id,
    filename,
    mime,
    size: 2048,
    scanned: true,
    isComparisonOffer: false,
    scanState: 'clean',
    fieldKey: null,
    ...extra,
  };
}

const ENV: ReportEnv = {
  href: 'https://stupa.example.org/applications/A-1?tab=files#x',
  path: '/applications/A-1',
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0',
  width: 1440,
  height: 900,
};

async function setup(
  opts: { signedIn?: boolean; create?: jest.Mock; locale?: string; solution?: string | null } = {},
) {
  localStorage.setItem('ap.locale', opts.locale ?? 'de');
  const drafts = new FakeDrafts();
  const create =
    opts.create ?? jest.fn((_b: TicketCreate) => of<TicketCreated>({ number: 'T-0043' }));
  const toast = { success: jest.fn(), error: jest.fn() };
  const auth = jest.fn();
  const view = await render(ReportDialogComponent, {
    componentProviders: [{ provide: DraftAttachmentsService, useValue: drafts }],
    providers: [
      { provide: TicketsApiService, useValue: { create } },
      { provide: AuthService, useValue: { isAuthenticated: signal(opts.signedIn ?? true), markReportedTicket: auth } },
      {
        provide: BrandingService,
        useValue: { wikiUrl: signal('https://wiki.example.org/handbook'), ticketsPublic: signal(true) },
      },
      { provide: ThemeService, useValue: { resolved: signal('dark') } },
      { provide: ToastService, useValue: toast },
      {
        provide: AltchaService,
        useValue: { solve: jest.fn(async () => (opts.solution === undefined ? 'solution-1' : opts.solution)) },
      },
    ],
  });
  const c = view.fixture.componentInstance;
  c.env = () => ENV;
  const help = view.fixture.debugElement.injector.get(HelpService);
  const open = async () => {
    help.openReport();
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    view.fixture.detectChanges();
  };
  return { ...view, c, drafts, create, toast, help, open, auth };
}

const titleField = () => screen.getByLabelText(/Kurz: Was ist das Problem\?/) as HTMLInputElement;
const bodyField = () => screen.getByLabelText('Was ist passiert? Was hast du erwartet?') as HTMLTextAreaElement;
const sendButton = () => screen.getByRole('button', { name: 'Senden' });

async function fill(title = 'Upload bricht ab', body = 'Bei 12 MB kommt ein Fehler.') {
  await userEvent.type(titleField(), title);
  await userEvent.type(bodyField(), body);
}

const altchaButton = () => document.querySelector('.altcha__btn') as HTMLButtonElement;

async function solveAltcha(fixture: { detectChanges(): void; whenStable(): Promise<unknown> }) {
  await userEvent.click(altchaButton());
  await fixture.whenStable();
  fixture.detectChanges();
}

function httpError(status: number, error: unknown = null): HttpErrorResponse {
  return new HttpErrorResponse({ status, error });
}

describe('ReportDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('sends a signed-in report with the context and shows only the number', async () => {
    const { open, create, drafts, fixture, auth } = await setup();
    await open();
    expect(screen.getByRole('link', { name: /Handbuch im Wiki/ })).toHaveAttribute(
      'href',
      'https://wiki.example.org/handbook',
    );
    // A signed-in reporter gives no e-mail and solves no ALTCHA.
    expect(screen.queryByLabelText(/Deine E-Mail/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Ich bin kein Roboter/ })).not.toBeInTheDocument();
    // The context rows: the page without the query, the browser and the window.
    expect(screen.getByText('https://stupa.example.org/applications/A-1')).toBeInTheDocument();
    expect(screen.getByText('Firefox 131 · Linux')).toBeInTheDocument();
    expect(screen.getByText('1440 × 900 · Deutsch')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('radio', { name: 'Idee' }));
    await fill('  Upload bricht ab  ');
    await userEvent.click(sendButton());
    fixture.detectChanges();

    expect(create).toHaveBeenCalledWith({
      kind: 'idea',
      title: 'Upload bricht ab',
      body: 'Bei 12 MB kommt ein Fehler.',
      email: null,
      context: {
        url: 'https://stupa.example.org/applications/A-1',
        route: '/applications/A-1',
        userAgent: ENV.userAgent,
        viewport: '1440x900',
        language: 'de',
        colorScheme: 'dark',
      },
      attachmentIds: undefined,
      draftToken: null,
      altcha: null,
    });
    expect(drafts.clear).toHaveBeenCalled();
    // The tab "Tickets" shows the own report from now on.
    expect(auth).toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Deine Meldung hat die Nummer T-0043');
    expect(screen.queryByRole('button', { name: 'Senden' })).not.toBeInTheDocument();
    // The focused send button is gone: the focus moves to the confirmation.
    await fixture.whenStable();
    expect(document.activeElement).toBe(screen.getByRole('status'));
  });

  it('starts a fresh report after a send, and keeps a closed draft', async () => {
    const { open, help, fixture, c } = await setup();
    await open();
    await fill('Erster Versuch', 'Text');
    // Closing keeps the draft.
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    fixture.detectChanges();
    expect(help.reportOpen()).toBe(false);
    await open();
    expect(c.title()).toBe('Erster Versuch');

    await userEvent.click(sendButton());
    fixture.detectChanges();
    // "Schließen" after the send.
    await userEvent.click(screen.getAllByRole('button', { name: 'Schließen' }).at(-1)!);
    await open();
    expect(c.title()).toBe('');
    expect(c.body()).toBe('');
    expect(c.sentNumber()).toBeNull();
  });

  it('names the missing fields and does not send', async () => {
    const { open, create, fixture } = await setup();
    await open();
    await userEvent.click(sendButton());
    fixture.detectChanges();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getAllByText('Bitte ausfüllen.')).toHaveLength(2);
    expect(bodyField()).toHaveAttribute('aria-invalid', 'true');
  });

  it('refuses a title or a body over the cap of the server', async () => {
    const { open, create, c } = await setup();
    await open();
    c.title.set('x'.repeat(201));
    c.body.set('ok');
    c.send();
    expect(create).not.toHaveBeenCalled();
    c.title.set('ok');
    c.body.set('x'.repeat(10_001));
    c.send();
    expect(create).not.toHaveBeenCalled();
  });

  it('asks a visitor for the e-mail and the ALTCHA solution', async () => {
    const { open, create, fixture, c, auth } = await setup({ signedIn: false });
    await open();
    await fill();
    const email = screen.getByLabelText(/Deine E-Mail/);
    await userEvent.click(sendButton());
    fixture.detectChanges();
    expect(screen.getAllByText('Bitte ausfüllen.').length).toBeGreaterThan(0);
    await userEvent.type(email, 'kein-at');
    fixture.detectChanges();
    expect(screen.getByText('Bitte eine gültige E-Mail-Adresse eingeben.')).toBeInTheDocument();
    await userEvent.clear(email);
    await userEvent.type(email, 'jana@example.org');
    // Unsolved: no send.
    await userEvent.click(sendButton());
    expect(create).not.toHaveBeenCalled();

    await solveAltcha(fixture);
    expect(c.altcha()).toBe('solution-1');
    await userEvent.click(sendButton());
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ email: 'jana@example.org', altcha: 'solution-1' }),
    );
    // Without a session there is no tab to show.
    expect(auth).not.toHaveBeenCalled();
  });

  it('sends without a solution when the server has ALTCHA off', async () => {
    const { open, create, c, fixture } = await setup({ signedIn: false, solution: null });
    await open();
    await fill();
    await userEvent.type(screen.getByLabelText(/Deine E-Mail/), 'jana@example.org');
    await solveAltcha(fixture);
    expect(c.altcha()).toBe('');
    await userEvent.click(sendButton());
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ altcha: null }));
  });

  it.each([
    [httpError(400, { code: 'altcha_failed' }), 'Die Prüfung „Kein Roboter“ ist abgelaufen. Bitte noch einmal bestätigen.'],
    [httpError(403), 'Meldungen ohne Konto sind ausgeschaltet. Bitte melde dich an.'],
    [httpError(413), 'Die Meldung ist zu groß. Bitte Anhänge entfernen.'],
    [httpError(429), 'Zu viele Meldungen. Versuche es später noch einmal.'],
    [httpError(422, { code: 'validation_error' }), 'Bitte die Angaben prüfen.'],
    [httpError(400), 'Die Meldung konnte nicht gesendet werden.'],
    [new Error('offline'), 'Die Meldung konnte nicht gesendet werden.'],
  ])('names the refusal %#, and a visitor solves again', async (err, text) => {
    const create = jest.fn(() => throwError(() => err));
    const { open, fixture, c } = await setup({ signedIn: false, create });
    await open();
    await fill();
    await userEvent.type(screen.getByLabelText(/Deine E-Mail/), 'jana@example.org');
    await solveAltcha(fixture);
    await userEvent.click(sendButton());
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent(text);
    expect(c.altcha()).toBeNull();
    // The widget asks again.
    expect(altchaButton()).toHaveTextContent('Ich bin kein Roboter');
    expect(c.sending()).toBe(false);
  });

  it('names a lost draft file of a 422 and keeps the ALTCHA of a signed-in reporter', async () => {
    const create = jest.fn(() => throwError(() => httpError(422, { code: 'attachment_missing' })));
    const { open, fixture, c, drafts } = await setup({ create });
    drafts.files.set([fileOf('a1')]);
    drafts.markedIds = ['a1'];
    await open();
    await fill();
    await userEvent.click(sendButton());
    fixture.detectChanges();
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ attachmentIds: ['a1'], draftToken: 'draft-token' }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Ein Anhang ist nicht verwendbar. Bitte entfernen.');
    expect(c.altcha()).toBeNull();
  });

  it('sends only once while a send runs', async () => {
    const pending = new Subject<TicketCreated>();
    const create = jest.fn(() => pending);
    const { open, c } = await setup({ create });
    await open();
    await fill();
    c.send();
    c.send();
    expect(create).toHaveBeenCalledTimes(1);
  });

  it('keeps the kind to the three kinds', async () => {
    const { open, c } = await setup({ locale: 'en' });
    await open();
    c.setKind('question');
    expect(c.kind()).toBe('question');
    c.setKind('other');
    c.setKind(null);
    expect(c.kind()).toBe('question');
    // The English window line.
    expect(screen.getByText('1440 × 900 · English')).toBeInTheDocument();
  });

  it('attaches picked and pasted files up to the limit', async () => {
    const { open, drafts, toast, fixture, c } = await setup();
    await open();
    const input = document.querySelector('input[type=file]') as HTMLInputElement;
    const click = jest.spyOn(input, 'click').mockImplementation(() => undefined);
    await userEvent.click(screen.getByRole('button', { name: 'Datei anhängen' }));
    expect(click).toHaveBeenCalled();

    const png = new File(['x'], 'shot.png', { type: 'image/png' });
    Object.defineProperty(input, 'files', { value: [png], configurable: true });
    input.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(drafts.upload).toHaveBeenCalledWith([png]);
    expect(screen.getByText('shot.png')).toBeInTheDocument();
    expect(input.value).toBe('');

    // A paste with a file becomes an attachment; a paste of text stays text.
    const form = document.querySelector('form.rd') as HTMLFormElement;
    const pasteFile = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
    Object.defineProperty(pasteFile, 'clipboardData', { value: { files: [new File(['y'], 'p.pdf', { type: 'application/pdf' })] } });
    form.dispatchEvent(pasteFile);
    expect(pasteFile.defaultPrevented).toBe(true);
    const pasteText = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
    Object.defineProperty(pasteText, 'clipboardData', { value: { files: [] } });
    form.dispatchEvent(pasteText);
    expect(pasteText.defaultPrevented).toBe(false);
    const pasteNone = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
    form.dispatchEvent(pasteNone);
    expect(pasteNone.defaultPrevented).toBe(false);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByText('p.pdf')).toBeInTheDocument();

    // Over the limit: a toast and only the room is taken.
    const many = Array.from({ length: MAX_TICKET_FILES }, (_, i) => new File(['z'], `m${i}.png`, { type: 'image/png' }));
    await c.addFiles(many);
    expect(toast.error).toHaveBeenCalledWith('Höchstens 5 Dateien.');
    expect(drafts.upload).toHaveBeenLastCalledWith(many.slice(0, MAX_TICKET_FILES - 2));
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Datei anhängen' })).not.toBeInTheDocument();
    // Full: nothing more is uploaded.
    drafts.upload.mockClear();
    await c.addFiles([png]);
    expect(drafts.upload).not.toHaveBeenCalled();
  });

  it('names the files the upload refused', async () => {
    const { open, drafts, toast, c } = await setup();
    await open();
    drafts.failures = [{ filename: 'big.zip', reason: 'help.report.error.tooLarge' }];
    await c.addFiles([new File(['x'], 'big.zip')]);
    expect(toast.error).toHaveBeenCalledWith('big.zip: Die Meldung ist zu groß. Bitte Anhänge entfernen.');
  });

  it('shows the scan state, a lost file and an upload in flight, and removes a file', async () => {
    const { open, drafts, toast, fixture } = await setup();
    drafts.files.set([
      fileOf('1', 'scan.pdf', 'application/pdf', { scanState: 'scanning', scanned: false }),
      fileOf('2', 'lost.png', 'image/png', { failed: true }),
    ]);
    drafts.pending.set([{ key: 1, filename: 'up.png', size: 1, fieldKey: null }]);
    await open();
    expect(screen.getByText('up.png')).toBeInTheDocument();
    // The send waits for the upload.
    expect(sendButton()).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: /lost\.png/ }));
    fixture.detectChanges();
    expect(drafts.remove).toHaveBeenCalledWith('2');
    expect(screen.queryByText('lost.png')).not.toBeInTheDocument();

    drafts.removeOk = false;
    await userEvent.click(screen.getByRole('button', { name: /scan\.pdf/ }));
    expect(toast.error).toHaveBeenCalledWith('Die Datei konnte nicht entfernt werden.');
  });

  it('closes on Abbrechen and leaves the draft files', async () => {
    const { open, drafts, help } = await setup();
    await open();
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(help.reportOpen()).toBe(false);
    expect(drafts.discard).not.toHaveBeenCalled();
  });

  it('reads the context without a url or a browser', async () => {
    const { open, c } = await setup();
    c.env = () => ({ ...ENV, href: '', userAgent: '' });
    await open();
    expect(c.contextRows().map((r) => r.label)).toEqual(['tickets.context.window', 'tickets.context.time']);
    c.openedAt.set(null);
    expect(c.contextRows().map((r) => r.label)).toEqual(['tickets.context.window']);
  });

  it('names the file type before the size', async () => {
    const { c } = await setup();
    expect(c.fileType('bild.png')).toBe('PNG · ');
    expect(c.fileType('README')).toBe('');
  });

  it('waits for an upload in flight before it sends', async () => {
    const { open, create, drafts, c } = await setup();
    await open();
    c.title.set('Titel');
    c.body.set('Text');
    drafts.pending.set([{ key: 1, filename: 'up.png', size: 1, fieldKey: null }]);
    c.send();
    expect(create).not.toHaveBeenCalled();
  });

  it('takes a pick without a file list as no file', async () => {
    const { open, drafts, c } = await setup();
    await open();
    const input = document.createElement('input');
    Object.defineProperty(input, 'files', { value: null });
    c.onPicked({ target: input } as unknown as Event);
    await Promise.resolve();
    expect(drafts.upload).not.toHaveBeenCalled();
  });

  it('names a refusal that arrives after the dialog was closed', async () => {
    const pending = new Subject<TicketCreated>();
    const { open, fixture, c, help } = await setup({ signedIn: false, create: jest.fn(() => pending) });
    await open();
    await fill();
    await userEvent.type(screen.getByLabelText(/Deine E-Mail/), 'jana@example.org');
    await solveAltcha(fixture);
    await userEvent.click(sendButton());
    help.closeReport();
    fixture.detectChanges();
    pending.error(httpError(429));
    expect(c.error()).toBe('help.report.error.rateLimit');
    expect(c.altcha()).toBeNull();
  });
});
