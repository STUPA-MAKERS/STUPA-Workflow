import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideRouter } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type {
  PaperlessConnection,
  PaperlessConnectionIn,
  PaperlessFailedFiling,
} from '../admin.models';
import { PaperlessComponent, isPaperlessUrl } from './paperless.component';
import { loadErrorToast, toastWith } from '../../../../testing/load-error';

const STORED: PaperlessConnection = {
  baseUrl: 'https://paperless.example.org',
  tokenSet: true,
  fileProtocols: true,
  fileApplications: false,
  filePlans: false,
  insertEnabled: false,
      linkEnabled: false,
  allowedHosts: ['paperless.example.org'],
};

const FAILED: PaperlessFailedFiling[] = [
  {
    id: 'f1',
    kind: 'protocol',
    elementId: 'p1',
    title: '3. Sitzung',
    failedAt: '2026-11-20T09:00:00Z',
    error: 'unreachable',
  },
  {
    id: 'f2',
    kind: 'attachment',
    elementId: 'a1',
    title: 'Plakate – angebot.pdf',
    failedAt: null,
    error: null,
  },
];

function makeApi(initial: PaperlessConnection = STORED, failed: PaperlessFailedFiling[] = FAILED) {
  return {
    getPaperless: jest.fn(() => of({ ...initial })),
    putPaperless: jest.fn((b: PaperlessConnectionIn) =>
      of({ ...initial, ...b, tokenSet: initial.tokenSet || !!b.token } as PaperlessConnection),
    ),
    testPaperless: jest.fn(() => of({ ok: true, error: null as string | null })),
    listPaperlessFailed: jest.fn(() => of(failed.map((f) => ({ ...f })))),
    retryPaperlessFiling: jest.fn(() => of(undefined)),
    backfillPaperless: jest.fn(() => of({ started: 3 })),
  };
}

type Api = ReturnType<typeof makeApi>;

interface Page {
  act(key: string): void;
  set(key: string, value: boolean): void;
  save(): void;
  errorText(code: string | null): string;
}

async function setup(opts: { api?: Api; perms?: string[] } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.paperless']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(PaperlessComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const page = view.fixture.componentInstance as unknown as Page;
  return { ...view, api, toast, page };
}

const urlField = () => screen.getByLabelText(/Adresse von Paperless/) as HTMLInputElement;
const tokenField = (name: RegExp = /Neuer Token/) => screen.getByLabelText(name) as HTMLInputElement;
const save = () => screen.getByRole('button', { name: 'Speichern' });
const sw = (name: string) => screen.getByRole('switch', { name });
/** The rows of "Fehlgeschlagene Ablagen": each is one button with the title and the line under it. */
const rows = () =>
  screen
    .queryAllByRole('button')
    .map((b) => b.textContent?.replace(/\s+/g, ' ').trim() ?? '')
    .filter((text) => /Sitzung|angebot/.test(text));

describe('isPaperlessUrl', () => {
  it.each([
    ['https://paperless.example.org', true],
    ['http://paperless.internal:8000/', true],
    [' https://paperless.example.org ', true],
    ['https://user@paperless.example.org', false],
    ['ftp://paperless.example.org', false],
    ['paperless.example.org', false],
    ['', false],
  ])('%s → %s', (text, ok) => {
    expect(isPaperlessUrl(text)).toBe(ok);
  });
});

describe('PaperlessComponent', () => {
  afterEach(() => localStorage.clear());

  /** § F/integrations/paperless/002511, § NF/security/network/002515: the token never shows. */
  it('shows the stored connection without the token, with nothing to save', async () => {
    const { api } = await setup();
    expect(api.getPaperless).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Paperless' })).toBeInTheDocument();
    expect(urlField().value).toBe(STORED.baseUrl);
    expect(tokenField().value).toBe('');
    expect(tokenField().type).toBe('password');
    expect(sw('Protokolle ablegen')).toHaveAttribute('aria-checked', 'true');
    expect(sw('Anträge ablegen')).toHaveAttribute('aria-checked', 'false');
    expect(sw('Haushaltspläne ablegen')).toHaveAttribute('aria-checked', 'false');
    expect(sw('Aus Paperless einfügen')).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  it('names the token field "Token" while none is stored', async () => {
    await setup({ api: makeApi({ ...STORED, baseUrl: null, tokenSet: false }) });
    expect(tokenField(/^Token/).value).toBe('');
    expect(urlField().value).toBe('');
    expect(screen.getByRole('button', { name: 'Verbindung testen' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Bestehende Dokumente ablegen' })).toBeDisabled();
  });

  /** § 002512: one switch per part. An empty token field keeps the stored token. */
  it('saves the switches and the address, and sends a token only when one is typed', async () => {
    const { api, toast, fixture } = await setup();
    await userEvent.click(sw('Anträge ablegen'));
    await userEvent.click(sw('Protokolle ablegen'));
    await userEvent.click(save());
    expect(api.putPaperless).toHaveBeenLastCalledWith({
      baseUrl: 'https://paperless.example.org',
      fileProtocols: false,
      fileApplications: true,
      filePlans: false,
      insertEnabled: false,
      linkEnabled: false,
    });
    expect(toast.success).toHaveBeenCalledWith('Gespeichert.');
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();

    await userEvent.type(tokenField(), 'new-token');
    await userEvent.click(sw('Haushaltspläne ablegen'));
    await userEvent.click(sw('Aus Paperless einfügen'));
    await userEvent.click(save());
    expect(api.putPaperless).toHaveBeenLastCalledWith(
      expect.objectContaining({ token: 'new-token', filePlans: true, insertEnabled: true }),
    );
    fixture.detectChanges();
    expect(tokenField().value).toBe('');
  });

  it('sends no address when the field is empty and ignores an unknown switch', async () => {
    const { api, page } = await setup();
    page.set('other', true);
    await userEvent.clear(urlField());
    await userEvent.click(save());
    expect(api.putPaperless).toHaveBeenLastCalledWith(expect.objectContaining({ baseUrl: null }));
  });

  it('refuses an address that is not http(s)', async () => {
    const { api, page } = await setup();
    await userEvent.clear(urlField());
    await userEvent.type(urlField(), 'paperless');
    expect(screen.getByText('Bitte eine Adresse mit http:// oder https:// eingeben.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
    page.save();
    expect(api.putPaperless).not.toHaveBeenCalled();
  });

  /** § NF/security/network/002514: the server refuses a host outside the allowlist. */
  it('names the allowed hosts when the server refuses the host', async () => {
    const api = makeApi();
    api.putPaperless.mockReturnValueOnce(
      throwError(() => ({ status: 422, error: { code: 'paperless_host_not_allowed' } })),
    );
    const { fixture } = await setup({ api });
    await userEvent.clear(urlField());
    await userEvent.type(urlField(), 'https://other.example.org');
    await userEvent.type(tokenField(), 'new-token');
    await userEvent.click(save());
    fixture.detectChanges();
    expect(
      screen.getByText('Dieser Host ist im Betrieb nicht freigegeben. Freigegeben: paperless.example.org'),
    ).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    fixture.detectChanges();
    expect(urlField().value).toBe(STORED.baseUrl);
    expect(screen.queryByText(/nicht freigegeben/)).toBeNull();
  });

  /** § F/integrations/paperless/002813: a new address needs the token again. */
  it('asks for the token again when the address changes', async () => {
    const { api, page } = await setup();
    await userEvent.clear(urlField());
    await userEvent.type(urlField(), 'https://paperless.example.org/dms');
    expect(screen.getByText('Bei einer neuen Adresse bitte den Token erneut eingeben.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
    page.save();
    expect(api.putPaperless).not.toHaveBeenCalled();
    await userEvent.type(tokenField(), 'new-token');
    expect(screen.queryByText(/Token erneut/)).toBeNull();
    await userEvent.click(save());
    expect(api.putPaperless).toHaveBeenLastCalledWith(
      expect.objectContaining({ baseUrl: 'https://paperless.example.org/dms', token: 'new-token' }),
    );
  });

  it('asks for no token for the stored address with a slash at its end', async () => {
    await setup();
    await userEvent.type(urlField(), '/');
    expect(screen.queryByText(/Token erneut/)).toBeNull();
  });

  it('shows no host error for another failed save', async () => {
    const api = makeApi();
    api.putPaperless.mockReturnValueOnce(throwError(() => null));
    const { toast, fixture } = await setup({ api });
    await userEvent.click(sw('Anträge ablegen'));
    await userEvent.click(save());
    fixture.detectChanges();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(screen.queryByText(/nicht freigegeben/)).toBeNull();
  });

  it('tests the stored connection and names the result', async () => {
    const api = makeApi();
    const { toast, page } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: 'Verbindung testen' }));
    expect(api.testPaperless).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith('Die Verbindung zu Paperless steht.');

    api.testPaperless.mockReturnValueOnce(of({ ok: false, error: 'unauthorized' }));
    page.act('test');
    expect(toast.error).toHaveBeenLastCalledWith('Paperless lehnt den Token ab.');

    api.testPaperless.mockReturnValueOnce(throwError(() => null));
    page.act('test');
    expect(toast.error).toHaveBeenLastCalledWith('Unbekannter Fehler.');
    expect(page.errorText('new_code')).toBe('Unbekannter Fehler.');
  });

  it('runs one test at a time and none while the form has a change', async () => {
    const api = makeApi();
    const pending = new Subject<{ ok: boolean; error: string | null }>();
    api.testPaperless.mockReturnValueOnce(pending);
    const { page, fixture } = await setup({ api });
    page.act('test');
    page.act('test');
    expect(api.testPaperless).toHaveBeenCalledTimes(1);
    pending.next({ ok: true, error: null });
    await userEvent.click(sw('Anträge ablegen'));
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Verbindung testen' })).toBeDisabled();
  });

  /** § 002530: the action asks first. */
  it('starts the backfill after the question', async () => {
    const api = makeApi();
    const { toast, page, fixture } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: 'Bestehende Dokumente ablegen' }));
    fixture.detectChanges();
    expect(api.backfillPaperless).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Ablegen' }));
    expect(api.backfillPaperless).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith('3 Ablagen gestartet.');

    api.backfillPaperless.mockReturnValueOnce(of({ started: 1 }));
    page.act('backfill');
    expect(toast.success).toHaveBeenLastCalledWith('1 Ablage gestartet.');

    api.backfillPaperless.mockReturnValueOnce(throwError(() => null));
    page.act('backfill');
    expect(toast.error).toHaveBeenLastCalledWith('Die Ablage konnte nicht gestartet werden.');

    const pending = new Subject<{ started: number }>();
    api.backfillPaperless.mockReturnValueOnce(pending);
    page.act('backfill');
    page.act('backfill');
    page.act('other');
    expect(api.backfillPaperless).toHaveBeenCalledTimes(4);
  });

  /** § 002526: the failed filings; a press on a row asks and starts the job again. */
  it('lists the failed filings with their kind, the time and the cause', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: 'Fehlgeschlagene Ablagen' })).toBeInTheDocument();
    expect(rows()).toEqual([
      expect.stringMatching(/^3\. Sitzung ?Protokoll · 20\.11\.2026.* · Paperless ist nicht erreichbar\.$/),
      expect.stringMatching(/^Plakate – angebot\.pdf ?Anhang · Unbekannter Fehler\.$/),
    ]);
  });

  it('starts a failed filing again after the question and takes its row out', async () => {
    const { api, toast, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /^3\. Sitzung/ }));
    fixture.detectChanges();
    expect(api.retryPaperlessFiling).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog', { name: 'Ablage erneut versuchen?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Erneut versuchen' }));
    fixture.detectChanges();
    expect(api.retryPaperlessFiling).toHaveBeenCalledWith('f1');
    expect(toast.success).toHaveBeenCalledWith('Die Ablage startet erneut.');
    expect(rows()).toHaveLength(1);
  });

  it('takes the row out after a 404 and keeps it after another error', async () => {
    const api = makeApi();
    api.retryPaperlessFiling
      .mockReturnValueOnce(throwError(() => ({ status: 404 })))
      .mockReturnValueOnce(throwError(() => ({ status: 500 })));
    const { toast, page, fixture } = await setup({ api });
    page.act('retry:f1');
    fixture.detectChanges();
    expect(rows()).toHaveLength(1);
    page.act('retry:f2');
    page.act('retry:gone');
    fixture.detectChanges();
    expect(toast.error).toHaveBeenCalledWith('Die Ablage konnte nicht erneut gestartet werden.');
    expect(rows()).toHaveLength(1);
    expect(api.retryPaperlessFiling).toHaveBeenCalledTimes(2);
  });

  it('runs one retry at a time', async () => {
    const api = makeApi();
    api.retryPaperlessFiling.mockReturnValueOnce(new Subject<undefined>());
    const { page } = await setup({ api });
    page.act('retry:f1');
    page.act('retry:f2');
    expect(api.retryPaperlessFiling).toHaveBeenCalledTimes(1);
  });

  it('shows no group without a failed filing', async () => {
    await setup({ api: makeApi(STORED, []) });
    expect(screen.queryByRole('heading', { name: 'Fehlgeschlagene Ablagen' })).toBeNull();
  });

  it('names a failed read of the failed filings', async () => {
    const api = makeApi();
    api.listPaperlessFailed.mockReturnValueOnce(throwError(() => null));
    await setup({ api });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Die fehlgeschlagenen Ablagen konnten nicht geladen werden.',
    );
    expect(screen.queryByRole('heading', { name: 'Fehlgeschlagene Ablagen' })).toBeNull();
  });

  it('shows no form without the right', async () => {
    const { api } = await setup({ perms: [] });
    expect(api.getPaperless).not.toHaveBeenCalled();
    expect(api.listPaperlessFailed).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('fehlt das Recht, Paperless zu verwalten');
    expect(screen.queryByRole('heading', { name: 'Fehlgeschlagene Ablagen' })).toBeNull();
  });

  it('names a failed read', async () => {
    const api = makeApi();
    api.getPaperless.mockReturnValueOnce(throwError(() => null));
    await setup({ api });
    expect(loadErrorToast()).toContain('Die Einstellungen konnten nicht geladen werden.');
  });

  it('shows the skeleton while it loads', async () => {
    const api = makeApi();
    api.getPaperless.mockReturnValueOnce(new Subject<PaperlessConnection>());
    api.listPaperlessFailed.mockReturnValueOnce(new Subject<PaperlessFailedFiling[]>());
    await setup({ api });
    expect(screen.queryByLabelText(/Adresse von Paperless/)).toBeNull();
    expect(document.querySelectorAll('.sts__skelSwitch')).toHaveLength(5);
  });

  it('saves the switch of the links to Paperless (002767)', async () => {
    const api = makeApi();
    await setup({ api });
    await userEvent.click(sw('Paperless-Dokumente verknüpfen'));
    await userEvent.click(save());
    expect(api.putPaperless).toHaveBeenCalledWith(expect.objectContaining({ linkEnabled: true }));
  });
});
