import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { MailTemplatesComponent } from './mail-templates.component';

const TPL = {
  id: null,
  key: 'magic_link',
  subjectI18n: { de: 'Anmeldung', en: 'Sign in' },
  bodyI18n: { de: 'Hallo {{name}}', en: 'Hi {{name}}' },
  bodyHtmlI18n: {},
  placeholders: { name: 'Anzeigename' },
  source: 'builtin',
};

function setupApi() {
  return {
    listMailTemplates: jest.fn(() => of([TPL])),
    upsertMailTemplate: jest.fn(() => of({ ...TPL, source: 'override' })),
    resetMailTemplate: jest.fn(() => of({ ...TPL, source: 'builtin' })),
    previewMailPayload: jest.fn(() =>
      of({ subject: 'Anmeldung', text: 'Hallo Anzeigename', html: null, lang: 'de' }),
    ),
  };
}

async function setup(api = setupApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(MailTemplatesComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { api, toast, view };
}

describe('MailTemplatesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists templates and auto-selects the first with its subject', async () => {
    await setup();
    expect(await screen.findByRole('button', { name: /magic_link/ })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Anmeldung')).toBeInTheDocument();
    // placeholder reference is shown.
    expect(screen.getByText(/name/)).toBeInTheDocument();
  });

  it('saves edits and renders a preview', async () => {
    const { api } = await setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Speichern' }));
    expect(api.upsertMailTemplate).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    expect(api.previewMailPayload).toHaveBeenCalled();
    expect(await screen.findByText('Hallo Anzeigename')).toBeInTheDocument();
  });

  it('toasts when the template list fails to load', async () => {
    const api = {
      ...setupApi(),
      listMailTemplates: jest.fn(() => throwError(() => new Error('boom'))),
    };
    const { toast } = await setup(api);
    expect(toast.error).toHaveBeenCalledWith('Vorlagen konnten nicht geladen werden.');
  });

  it('patches the subject of the active language into the draft', async () => {
    const { view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.patch('subjectI18n', 'Neuer Betreff');
    expect(c.draft().subjectI18n.de).toBe('Neuer Betreff');
    // switching language keeps the other value untouched
    c.lang.set('en');
    c.patch('bodyI18n', 'New body');
    expect(c.draft().bodyI18n.en).toBe('New body');
    expect(c.draft().bodyI18n.de).toBe('Hallo {{name}}');
  });

  it('patch is a no-op without a selected draft', async () => {
    const api = { ...setupApi(), listMailTemplates: jest.fn(() => of([])) };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    expect(c.draft()).toBeNull();
    c.patch('subjectI18n', 'x');
    expect(c.draft()).toBeNull();
  });

  it('does not auto-select when the list is empty', async () => {
    const api = { ...setupApi(), listMailTemplates: jest.fn(() => of([])) };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    expect(c.selectedKey()).toBeNull();
    expect(c.placeholderList()).toEqual([]);
  });

  it('select ignores an unknown key', async () => {
    const { view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    const before = c.selectedKey();
    c.select('does-not-exist');
    expect(c.selectedKey()).toBe(before);
  });

  it('toasts and clears saving on a save failure', async () => {
    const api = {
      ...setupApi(),
      upsertMailTemplate: jest.fn(() => throwError(() => new Error('boom'))),
    };
    const { toast, view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(c.saving()).toBe(false);
  });

  it('ignores a save while one is already in flight', async () => {
    const { api, view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.saving.set(true);
    c.save();
    expect(api.upsertMailTemplate).not.toHaveBeenCalled();
  });

  it('save is a no-op without a draft', async () => {
    const api = { ...setupApi(), listMailTemplates: jest.fn(() => of([])) };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.save();
    expect(api.upsertMailTemplate).not.toHaveBeenCalled();
  });

  it('resets a template to its builtin default', async () => {
    const { api, toast, view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.reset();
    expect(api.resetMailTemplate).toHaveBeenCalledWith('magic_link');
    expect(c.resetting()).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('Auf Standard zurückgesetzt.');
  });

  it('toasts and clears resetting on a reset failure', async () => {
    const api = {
      ...setupApi(),
      resetMailTemplate: jest.fn(() => throwError(() => new Error('boom'))),
    };
    const { toast, view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.reset();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(c.resetting()).toBe(false);
  });

  it('ignores a reset while one is in flight and without a draft', async () => {
    const { api, view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.resetting.set(true);
    c.reset();
    expect(api.resetMailTemplate).not.toHaveBeenCalled();
    c.resetting.set(false);
    c.draft.set(null);
    c.reset();
    expect(api.resetMailTemplate).not.toHaveBeenCalled();
  });

  it('toasts and clears previewing on a preview failure', async () => {
    const api = {
      ...setupApi(),
      previewMailPayload: jest.fn(() => throwError(() => new Error('boom'))),
    };
    const { toast, view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.runPreview();
    expect(toast.error).toHaveBeenCalledWith('Vorschau fehlgeschlagen.');
    expect(c.previewing()).toBe(false);
  });

  it('ignores preview while one is in flight and without a draft', async () => {
    const { api, view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.previewing.set(true);
    c.runPreview();
    expect(api.previewMailPayload).not.toHaveBeenCalled();
    c.previewing.set(false);
    c.draft.set(null);
    c.runPreview();
    expect(api.previewMailPayload).not.toHaveBeenCalled();
  });

  it('builds the preview context using placeholder descriptions and key fallback', async () => {
    const tpl = {
      ...TPL,
      placeholders: { name: 'Anzeigename', code: '' },
    };
    const api = { ...setupApi(), listMailTemplates: jest.fn(() => of([tpl])) };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.runPreview();
    const arg = api.previewMailPayload.mock.calls[0][0];
    expect(arg.context).toEqual({ name: 'Anzeigename', code: 'code' });
    expect(arg.lang).toBe('de');
  });

  it('applyUpdate replaces only the matching template and leaves siblings alone', async () => {
    const other = { ...TPL, key: 'other', subjectI18n: { de: 'Andere', en: 'Other' } };
    const api = { ...setupApi(), listMailTemplates: jest.fn(() => of([TPL, other])) };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    // first template auto-selected → save upserts it; the "other" sibling is the else branch
    c.save();
    expect(c.templates().find((t: { key: string }) => t.key === 'other')).toEqual(other);
    expect(c.templates().find((t: { key: string }) => t.key === 'magic_link').source).toBe('override');
  });

  it('does not re-select after updating a non-selected template', async () => {
    const other = { ...TPL, key: 'other' };
    const api = {
      ...setupApi(),
      listMailTemplates: jest.fn(() => of([TPL, other])),
      upsertMailTemplate: jest.fn(() => of({ ...other, source: 'override' })),
    };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    // selected = magic_link, but the upsert returns 'other' → selectedKey !== tpl.key branch
    expect(c.selectedKey()).toBe('magic_link');
    c.save();
    expect(c.selectedKey()).toBe('magic_link');
  });

  it('keyLabel returns the raw key when unknown', async () => {
    const { view } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    expect(c.keyLabel('totally_unknown_key')).toBe('totally_unknown_key');
  });
});
