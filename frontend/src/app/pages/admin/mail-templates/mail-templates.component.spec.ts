import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
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
    const { view } = await setup();
    const fixture = view.fixture;
    expect(await screen.findByRole('button', { name: /Anmelde-Link/ })).toHaveAttribute('aria-current', 'true');
    // ngModel writes the subject into the field after a tick.
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByDisplayValue('Anmeldung')).toBeInTheDocument();
    // The placeholder reference lists the "name" token.
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
    // Save upserts the auto-selected first template. The "other" sibling covers the else branch.
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
    // magic_link stays selected while the upsert returns 'other'.
    // This covers the branch where the selected key differs from the updated key.
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

  it('switches the language of the fields and marks an override', async () => {
    const override = { ...TPL, key: 'status_update', source: 'override', bodyHtmlI18n: { de: '<p>Hi</p>' } };
    const api = {
      ...setupApi(),
      listMailTemplates: jest.fn(() => of([TPL, override])),
      previewMailPayload: jest.fn(() => of({ subject: 'S', text: 'T', html: '<p>Hi</p>', lang: 'en' })),
    };
    const { view } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    // A builtin template has no reset.
    expect(screen.queryByRole('button', { name: 'Auf Standard zurücksetzen' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Status-Änderung/ }));
    expect(screen.getAllByText('angepasst')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Auf Standard zurücksetzen' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
    expect(c.lang()).toBe('en');
    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    expect(api.previewMailPayload).toHaveBeenCalledWith(expect.objectContaining({ lang: 'en' }));
    expect(screen.getByText('Vorschau (EN)')).toBeInTheDocument();
    expect(view.container.querySelector('.mt__previewHtml')?.innerHTML).toContain('Hi');
    c.setLang('de');
    expect(c.lang()).toBe('de');
    c.setLang(null);
    expect(c.lang()).toBe('de');
  });

  describe('on a phone', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.phone)));
    afterEach(() => restore());

    it('picks the template with a chip instead of the list', async () => {
      const { view } = await setup({ ...setupApi(), listMailTemplates: jest.fn(() => of([TPL, { ...TPL, key: 'task_new', source: 'override' }])) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = view.fixture.componentInstance as any;
      expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
      expect(c.templateOptions()).toEqual([
        { value: 'magic_link', label: 'Anmelde-Link' },
        { value: 'task_new', label: 'Neue Aufgabe · angepasst' },
      ]);
      expect(screen.getByRole('button', { name: /Vorlage/ })).toBeInTheDocument();
    });
  });
});
