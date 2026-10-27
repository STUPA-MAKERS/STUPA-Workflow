import { HttpErrorResponse } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { loadCatalog } from '@core/i18n/translations';
import { AdminTranslationsComponent, LANGUAGE_CODE, PAGE_SIZE, areaOf } from './translations.component';
import { type AdminUiLanguage, TranslationsApiService } from './translations-api.service';

const FR: AdminUiLanguage = { code: 'fr', name: 'Français', active: false };

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  const texts: Record<string, Record<string, string>> = {
    de: { 'nav.dashboard': 'Mein Überblick' },
    en: { 'nav.tasks': 'To do' },
    fr: { 'nav.dashboard': 'Tableau de bord' },
  };
  return {
    languages: jest.fn(() => of([{ ...FR }])),
    texts: jest.fn((locale: string) => of({ locale, overrides: { ...texts[locale] } })),
    saveTexts: jest.fn((locale: string, changes: Record<string, string | null>) => {
      const next = { ...texts[locale] };
      for (const [k, v] of Object.entries(changes)) {
        if (v === null) delete next[k];
        else next[k] = v;
      }
      return of({ locale, overrides: next });
    }),
    createLanguage: jest.fn((body: { code: string; name: string }) => of({ ...body, active: false })),
    updateLanguage: jest.fn((code: string, body: { name?: string; active?: boolean }) =>
      of({ ...FR, code, ...body }),
    ),
    deleteLanguage: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(api = makeApi(), toast = makeToast()) {
  const view = await render(AdminTranslationsComponent, {
    providers: [
      { provide: TranslationsApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  // The page waits for the lazy EN catalog (loaded in `beforeAll`) before it shows the list.
  await Promise.resolve();
  view.fixture.detectChanges();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inst = view.fixture.componentInstance as any;
  const i18n = view.fixture.debugElement.injector.get(I18nService);
  return { ...view, api, toast, inst, i18n };
}

describe('AdminTranslationsComponent', () => {
  beforeAll(() => loadCatalog('en'));
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the languages and the first page of keys with their overrides', async () => {
    const { inst } = await setup();
    expect(screen.getByText('Français')).toBeInTheDocument();
    expect(screen.getAllByText('Eingebaut')).toHaveLength(2);
    expect(inst.rows()).toHaveLength(PAGE_SIZE);
    expect(inst.value('nav.dashboard')).toBe('Mein Überblick');
    expect(inst.reference('nav.dashboard')).toBe('Dashboard');
    expect(inst.hasMore()).toBe(true);
    inst.more();
    expect(inst.rows()).toHaveLength(2 * PAGE_SIZE);
  });

  it('shows the built-in EN text as the reference of EN while the app runs in DE', async () => {
    const { inst } = await setup();
    inst.setLocale('en');
    expect(inst.reference('nav.dashboard')).toBe('Dashboard');
    expect(inst.reference('action.save')).toBe('Save');
  });

  it('shows a load error', async () => {
    await setup(makeApi({ languages: jest.fn(() => throwError(() => new Error('x'))) }));
    expect(screen.getByRole('alert')).toHaveTextContent('Übersetzungen konnten nicht geladen werden.');
  });

  it('filters by search, area and changed texts', async () => {
    jest.useFakeTimers();
    try {
      const { inst } = await setup();
      inst.setSearch('mein überblick');
      expect(inst.rows().length).toBeGreaterThan(1);
      jest.advanceTimersByTime(300);
      expect(inst.rows()).toEqual(['nav.dashboard']);
      inst.setSearch('');
      inst.flushSearch();
      inst.setArea('meetings');
      expect(inst.rows().every((k: string) => k.startsWith('meetings.'))).toBe(true);
      inst.setArea('');
      inst.setChanged('changed');
      expect(inst.rows()).toEqual(['nav.dashboard']);
      inst.setChanged('');
      expect(inst.rows()).toHaveLength(PAGE_SIZE);
    } finally {
      jest.useRealTimers();
    }
  });

  it('finds an EN or extra text by its DE text too', async () => {
    const { inst } = await setup();
    inst.setLocale('en');
    inst.setSearch('Aufgaben');
    inst.flushSearch();
    expect(inst.rows()).toContain('nav.tasks');
    expect(inst.reference('nav.tasks')).toBe('Tasks');
  });

  it('uses the EN text as the reference of an extra language and loads its overrides once', async () => {
    const { inst, api } = await setup();
    inst.setLocale('fr');
    expect(api.texts).toHaveBeenCalledWith('fr');
    expect(inst.value('nav.dashboard')).toBe('Tableau de bord');
    expect(inst.reference('nav.tasks')).toBe('To do');
    expect(inst.reference('action.login')).toBe('Sign in');
    expect(inst.localeText()).toBe('Français (inaktiv)');
    inst.setLocale('de');
    inst.setLocale('fr');
    expect(api.texts).toHaveBeenCalledTimes(3);
    inst.setLocale('');
    expect(inst.locale()).toBe('de');
  });

  it('toasts when the overrides of a locale do not load', async () => {
    const api = makeApi();
    const toast = makeToast();
    const { inst } = await setup(api, toast);
    api.texts.mockReturnValueOnce(throwError(() => new Error('x')));
    inst.setLocale('fr');
    expect(toast.error).toHaveBeenCalled();
  });

  it('saves only the changed keys of each locale and applies them at once', async () => {
    const { inst, api, i18n, toast } = await setup();
    const apply = jest.spyOn(i18n, 'applyOverrides');
    expect(inst.dirty()).toBe(false);
    inst.edit('nav.tasks', 'Zu tun');
    inst.edit('nav.dashboard', 'Mein Überblick');
    inst.reset('meetings.overview.open');
    inst.setLocale('en');
    inst.edit('nav.tasks', '  ');
    expect(inst.dirty()).toBe(true);
    inst.save();
    expect(api.saveTexts).toHaveBeenCalledWith('de', { 'nav.tasks': 'Zu tun' });
    expect(api.saveTexts).toHaveBeenCalledWith('en', { 'nav.tasks': null });
    expect(apply).toHaveBeenCalledWith('de', { 'nav.dashboard': 'Mein Überblick', 'nav.tasks': 'Zu tun' });
    expect(inst.dirty()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    inst.save();
    expect(api.saveTexts).toHaveBeenCalledTimes(2);
  });

  it('discards the edits', async () => {
    const { inst } = await setup();
    inst.edit('nav.tasks', 'X');
    inst.discard();
    expect(inst.dirty()).toBe(false);
  });

  it('blocks a save while a text breaks the placeholders', async () => {
    const { inst, api, fixture } = await setup();
    inst.edit('shell.nav.tasksOpen', 'offen');
    expect(inst.placeholderError('shell.nav.tasksOpen')).toBe('Muss genau diese Platzhalter enthalten: {count}');
    inst.edit('nav.tasks', 'Aufgaben {x}');
    expect(inst.placeholderError('nav.tasks')).toBe('Darf keine Platzhalter enthalten');
    expect(inst.invalid()).toBe(true);
    inst.save();
    expect(api.saveTexts).not.toHaveBeenCalled();
    inst.edit('shell.nav.tasksOpen', '{count} zu tun');
    inst.edit('nav.tasks', '');
    expect(inst.placeholderError('shell.nav.tasksOpen')).toBeNull();
    expect(inst.invalid()).toBe(false);
    fixture.detectChanges();
  });

  it('toasts a failed save and keeps the edits', async () => {
    const toast = makeToast();
    const { inst } = await setup(makeApi({ saveTexts: jest.fn(() => throwError(() => new Error('x'))) }), toast);
    inst.edit('nav.tasks', 'Zu tun');
    inst.save();
    expect(toast.error).toHaveBeenCalled();
    expect(inst.dirty()).toBe(true);
  });

  it('switches a language on and puts it back when the patch fails', async () => {
    const api = makeApi();
    const toast = makeToast();
    const { inst } = await setup(api, toast);
    inst.setActive(FR, true);
    expect(api.updateLanguage).toHaveBeenCalledWith('fr', { active: true });
    expect(inst.languages()[0].active).toBe(true);
    api.updateLanguage.mockReturnValueOnce(throwError(() => new Error('x')));
    inst.setActive({ ...FR, active: true }, false);
    expect(inst.languages()[0].active).toBe(true);
    expect(toast.error).toHaveBeenCalled();
  });

  it('creates a language and selects it', async () => {
    const { inst, api } = await setup();
    inst.openDialog(null);
    expect(inst.dialogValid()).toBe(false);
    inst.patchDialog({ newCode: 'French' });
    expect(inst.codeError()).toBe('Kein gültiger Sprachcode (z. B. fr, pt-BR)');
    inst.patchDialog({ newCode: 'fr' });
    expect(inst.codeError()).toBe('Diese Sprache gibt es schon');
    inst.patchDialog({ newCode: 'en' });
    expect(inst.codeError()).toBe('Diese Sprache gibt es schon');
    inst.patchDialog({ newCode: 'pt-BR', name: ' Português ' });
    expect(inst.codeError()).toBe('');
    expect(inst.dialogValid()).toBe(true);
    inst.submitDialog();
    expect(api.createLanguage).toHaveBeenCalledWith({ code: 'pt-BR', name: 'Português' });
    expect(inst.languages().map((l: AdminUiLanguage) => l.code)).toEqual(['fr', 'pt-BR']);
    expect(inst.locale()).toBe('pt-BR');
    expect(inst.dialog()).toBeNull();
    inst.submitDialog();
    expect(api.createLanguage).toHaveBeenCalledTimes(1);
  });

  it('names a conflict and a failure of the dialog', async () => {
    const api = makeApi({
      createLanguage: jest.fn(() => throwError(() => new HttpErrorResponse({ status: 409 }))),
    });
    const { inst } = await setup(api);
    inst.openDialog(null);
    inst.patchDialog({ newCode: 'it', name: 'Italiano' });
    inst.submitDialog();
    expect(inst.dialogError()).toBe('admin.translations.codeTaken');
    api.createLanguage.mockReturnValueOnce(throwError(() => new Error('x')));
    inst.submitDialog();
    expect(inst.dialogError()).toBe('admin.common.saveFailed');
  });

  it('renames a language from its menu', async () => {
    const { inst, api } = await setup();
    expect(inst.languageMenu()[0].items.map((i: { id: string }) => i.id)).toEqual(['rename', 'delete']);
    inst.onLanguageMenu({ id: 'rename', label: '' }, FR);
    expect(inst.dialog()).toEqual({ code: 'fr', newCode: 'fr', name: 'Français' });
    expect(inst.codeError()).toBe('');
    inst.patchDialog({ name: 'Francais' });
    inst.submitDialog();
    expect(api.updateLanguage).toHaveBeenCalledWith('fr', { name: 'Francais' });
    expect(inst.languages()[0].name).toBe('Francais');
  });

  it('deletes a language after the confirmation', async () => {
    const { inst, api, toast } = await setup();
    inst.setLocale('fr');
    inst.edit('nav.tasks', 'Tâches');
    inst.onLanguageMenu({ id: 'delete', label: '' }, FR);
    expect(inst.confirmDelete()).toEqual(FR);
    inst.deleteLanguage();
    expect(api.deleteLanguage).toHaveBeenCalledWith('fr');
    expect(inst.languages()).toEqual([]);
    expect(inst.locale()).toBe('de');
    expect(inst.dirty()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    inst.deleteLanguage();
    expect(api.deleteLanguage).toHaveBeenCalledTimes(1);
  });

  it('toasts a failed delete', async () => {
    const toast = makeToast();
    const { inst } = await setup(makeApi({ deleteLanguage: jest.fn(() => throwError(() => new Error('x'))) }), toast);
    inst.confirmDelete.set(FR);
    inst.deleteLanguage();
    expect(toast.error).toHaveBeenCalled();
  });

  it('knows the area of a key and the code pattern', () => {
    expect(areaOf('meetings.overview.open')).toBe('meetings');
    expect(areaOf('plain')).toBe('plain');
    expect(LANGUAGE_CODE.test('sr-Latn')).toBe(true);
    expect(LANGUAGE_CODE.test('es-419')).toBe(true);
    expect(LANGUAGE_CODE.test('FR')).toBe(false);
  });

  it('covers the edges of the drafts and the dialog', async () => {
    const { inst } = await setup(makeApi({ languages: jest.fn(() => of([{ ...FR }, { code: 'it', name: 'Italiano', active: true }])) }));
    expect(inst.codeError()).toBe('');
    expect(inst.dialogValid()).toBe(false);
    inst.patchDialog({ name: 'x' });
    expect(inst.dialog()).toBeNull();
    inst.setLocale('it');
    expect(inst.reference('nav.dashboard')).toBe('Dashboard');
    expect(inst.value('nav.dashboard')).toBe('');
    expect(inst.localeText()).toBe('Italiano');
    inst.locale.set('xx');
    expect(inst.localeText()).toBe('xx');
    inst.locale.set('de');
    inst.edit('nav.dashboard', 'Mein Überblick');
    expect(inst.dirty()).toBe(false);
    inst.edit('nav.tasks', 'A');
    inst.edit('nav.dashboard', 'B');
    expect(inst.dirty()).toBe(true);
    inst.confirmDelete.set(FR);
    inst.deleteLanguage();
    expect(inst.locale()).toBe('de');
    expect(inst.dirty()).toBe(true);
  });
});
