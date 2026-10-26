import { LoadMoreComponent } from '@shared/ui/load-more/load-more.component';
import { ListItemComponent } from '@stupa-makers/ui-kit';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { forkJoin, from } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { placeholdersOf, samePlaceholders } from '@core/i18n/placeholders';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { type TranslationKey, de, loadCatalog } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui';
import { FabComponent } from '@shared/ui/fab/fab.component';
import {
  ButtonComponent,
  ConfirmDialogComponent,
  DialogComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  InfiniteScrollDirective,
  InputComponent,
  NoteComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SearchPillComponent,
  SkeletonComponent,
  BadgeComponent,
  StickyBarComponent,
  SwitchComponent,
  TextareaComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { type AdminUiLanguage, TranslationsApiService } from './translations-api.service';

/** Every key of the catalog, in catalog order. */
const ALL_KEYS = Object.keys(de) as TranslationKey[];

/** The rows that the list shows at first and adds each time the end of the list comes into view. */
export const PAGE_SIZE = 50;

/** The search waits this long after the last key stroke. */
const SEARCH_DEBOUNCE_MS = 250;

/** A BCP 47 tag of a new language; the server checks the same pattern. */
export const LANGUAGE_CODE = /^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$/;

/** The area of a key: its first segment (`meetings` of `meetings.overview.open`). */
export function areaOf(key: string): string {
  const dot = key.indexOf('.');
  return dot < 0 ? key : key.slice(0, dot);
}

/** The draft of the language dialog. `code` is null when the dialog renames a language. */
interface LanguageDraft {
  code: string | null;
  newCode: string;
  name: string;
}

/**
 * "Übersetzungen" (permission `admin.translations`): the UI texts of every key, per locale,
 * and the extra UI languages.
 *
 * - The language chip picks the locale to edit: DE, EN or an extra language (inactive ones
 *   too). Each row shows the key and the text that applies without an override (the built-in
 *   text; for an extra language the EN text, then DE), and a field for the override. An empty
 *   field restores that text.
 * - The EN catalog is a lazy chunk that the app loads only in EN. The page loads it before it
 *   shows the list, so the reference of EN and of an extra language is never the DE text.
 * - An override must hold exactly the placeholders (`{count}`) of the built-in text; the row
 *   names the difference, and "Speichern" stays off until it is fixed. The server checks the
 *   same rule.
 * - Search (key and texts), area chip (first segment of the key), chip "Geändert". The list
 *   shows {@link PAGE_SIZE} rows and adds more when its end comes into view (infinite
 *   scroll, with "Mehr laden" beside the sentinel as the fallback).
 * - "Sprachen": DE and EN are built in. An extra language has the switch "Aktiv" (only an
 *   active language shows in the language switch of the app), rename and delete (with all
 *   its texts) in the ⋮ menu.
 * - The floating button is "Speichern" while a text differs from the server, else "Sprache"
 *   (new language). A save sends only the changed keys of each locale and puts the result in
 *   place at once (`I18nService.applyOverrides`).
 */
@Component({
  selector: 'app-admin-translations',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ListItemComponent,
    LoadMoreComponent,
    ButtonComponent,
    ConfirmDialogComponent,
    DialogComponent,
    EmptyStateComponent,
    FabComponent,
    FilterSelectComponent,
    FormsModule,
    IconComponent,
    InfiniteScrollDirective,
    InputComponent,
    NoteComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SearchPillComponent,
    SkeletonComponent,
    BadgeComponent,
    StickyBarComponent,
    SwitchComponent,
    TextareaComponent,
    TranslatePipe,
  ],
  templateUrl: './translations.component.html',
  styleUrl: './translations.component.scss',
})
export class AdminTranslationsComponent {
  private readonly api = inject(TranslationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly languages = signal<AdminUiLanguage[]>([]);

  /** The locale that the list edits. */
  protected readonly locale = signal('de');
  /** Locale → key → stored override. */
  private readonly stored = signal<Record<string, Record<string, string>>>({});
  /** Locale → key → edited text ('' = restore the built-in text). */
  private readonly draft = signal<Record<string, Record<string, string>>>({});

  protected readonly searchText = signal('');
  private readonly query = signal('');
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  protected readonly area = signal('');
  protected readonly changedOnly = signal(false);
  protected readonly limit = signal(PAGE_SIZE);

  protected readonly saving = signal(false);
  protected readonly dialog = signal<LanguageDraft | null>(null);
  protected readonly dialogBusy = signal(false);
  protected readonly dialogError = signal<TranslationKey | null>(null);
  protected readonly confirmDelete = signal<AdminUiLanguage | null>(null);
  protected readonly toggling = signal<string | null>(null);

  constructor() {
    forkJoin({
      catalog: from(loadCatalog('en')),
      languages: this.api.languages(),
      de: this.api.texts('de'),
      en: this.api.texts('en'),
    }).subscribe({
      next: ({ languages, de: deTexts, en }) => {
        this.languages.set(languages);
        this.stored.set({ de: deTexts.overrides, en: en.overrides });
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** The chip options: DE, EN, then the extra languages (inactive ones marked). */
  protected readonly localeOptions = computed<FilterSelectOption[]>(() => [
    { value: 'de', label: this.i18n.translate('shell.lang.de') },
    { value: 'en', label: this.i18n.translate('shell.lang.en') },
    ...this.languages().map((l) => ({
      value: l.code,
      label: l.active ? l.name : this.i18n.translate('admin.translations.inactiveName', { name: l.name }),
    })),
  ]);

  protected readonly localeText = computed(
    () => this.localeOptions().find((o) => o.value === this.locale())?.label ?? this.locale(),
  );

  protected readonly areaOptions = computed<FilterSelectOption[]>(() => {
    const areas = [...new Set(ALL_KEYS.map(areaOf))].sort();
    return [
      { value: '', label: this.i18n.translate('admin.translations.allAreas') },
      ...areas.map((a) => ({ value: a, label: a })),
    ];
  });

  protected readonly changedOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.translations.allTexts') },
    { value: 'changed', label: this.i18n.translate('admin.translations.changedOnly') },
  ]);

  /** The text of a key without an override in the edited locale. */
  protected reference(key: TranslationKey): string {
    const loc = this.locale();
    const deText = de[key];
    if (loc === 'de') return deText;
    const en = this.i18n.builtIn(key, 'en') ?? deText;
    if (loc === 'en') return en;
    return this.stored()['en']?.[key] ?? en;
  }

  /** The text in the field of a key: the draft, else the stored override, else empty. */
  protected value(key: TranslationKey): string {
    const loc = this.locale();
    return this.draft()[loc]?.[key] ?? this.stored()[loc]?.[key] ?? '';
  }

  protected isChanged(key: TranslationKey): boolean {
    return this.value(key).trim() !== '';
  }

  /** The placeholders that the field lacks or adds, or null when it is fine. */
  protected placeholderError(key: TranslationKey): string | null {
    const text = this.value(key);
    if (!text.trim() || samePlaceholders(text, de[key])) return null;
    const names = placeholdersOf(de[key]).map((n) => `{${n}}`);
    return names.length
      ? this.i18n.translate('admin.translations.placeholders', { names: names.join(' ') })
      : this.i18n.translate('admin.translations.noPlaceholders');
  }

  private readonly filtered = computed(() => {
    const loc = this.locale();
    const q = this.query().trim().toLocaleLowerCase();
    const area = this.area();
    const changedOnly = this.changedOnly();
    this.stored();
    this.draft();
    return ALL_KEYS.filter((key) => {
      if (area && areaOf(key) !== area) return false;
      if (changedOnly && !this.isChanged(key)) return false;
      if (!q) return true;
      return (
        key.toLocaleLowerCase().includes(q) ||
        this.reference(key).toLocaleLowerCase().includes(q) ||
        this.value(key).toLocaleLowerCase().includes(q) ||
        (loc !== 'de' && de[key].toLocaleLowerCase().includes(q))
      );
    });
  });

  protected readonly rows = computed(() => this.filtered().slice(0, this.limit()));
  protected readonly hasMore = computed(() => this.filtered().length > this.limit());

  /** Locale → the changes to send: key → text or null. */
  private readonly changes = computed(() => {
    const out: Record<string, Record<string, string | null>> = {};
    for (const [loc, edits] of Object.entries(this.draft())) {
      for (const [key, text] of Object.entries(edits)) {
        const next = text.trim() ? text : null;
        const before = this.stored()[loc]?.[key] ?? null;
        if (next === before) continue;
        (out[loc] ??= {})[key] = next;
      }
    }
    return out;
  });

  protected readonly dirty = computed(() => Object.keys(this.changes()).length > 0);

  /** True while an edited text in any locale breaks the placeholder rule. */
  protected readonly invalid = computed(() =>
    Object.values(this.changes()).some((edits) =>
      Object.entries(edits).some(
        ([key, text]) => text !== null && !samePlaceholders(text, de[key as TranslationKey]),
      ),
    ),
  );

  protected setLocale(code: string): void {
    this.locale.set(code || 'de');
    this.limit.set(PAGE_SIZE);
    if (this.stored()[code] === undefined) {
      this.api.texts(code).subscribe({
        next: (t) => this.stored.update((s) => ({ ...s, [code]: t.overrides })),
        error: () => this.toast.error(this.i18n.translate('admin.translations.loadError')),
      });
    }
  }

  protected setSearch(text: string): void {
    this.searchText.set(text);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.flushSearch(), SEARCH_DEBOUNCE_MS);
  }

  protected flushSearch(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = null;
    this.query.set(this.searchText());
    this.limit.set(PAGE_SIZE);
  }

  protected setArea(area: string): void {
    this.area.set(area);
    this.limit.set(PAGE_SIZE);
  }

  protected setChanged(value: string): void {
    this.changedOnly.set(value === 'changed');
    this.limit.set(PAGE_SIZE);
  }

  protected more(): void {
    this.limit.update((n) => n + PAGE_SIZE);
  }

  protected edit(key: TranslationKey, text: string): void {
    const loc = this.locale();
    this.draft.update((d) => ({ ...d, [loc]: { ...d[loc], [key]: text } }));
  }

  protected reset(key: TranslationKey): void {
    this.edit(key, '');
  }

  protected discard(): void {
    this.draft.set({});
  }

  protected save(): void {
    if (this.saving() || this.invalid()) return;
    const changes = this.changes();
    const locales = Object.keys(changes);
    if (!locales.length) return;
    this.saving.set(true);
    forkJoin(locales.map((loc) => this.api.saveTexts(loc, changes[loc]))).subscribe({
      next: (results) => {
        this.stored.update((s) => {
          const next = { ...s };
          for (const r of results) next[r.locale] = r.overrides;
          return next;
        });
        for (const r of results) this.i18n.applyOverrides(r.locale, r.overrides);
        this.draft.set({});
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected languageMenu(): RowMenuSection[] {
    return [
      {
        items: [
          { id: 'rename', label: this.i18n.translate('admin.translations.rename'), icon: 'edit' },
          { id: 'delete', label: this.i18n.translate('action.delete'), icon: 'trash', danger: true },
        ],
      },
    ];
  }

  protected onLanguageMenu(item: RowMenuItem, lang: AdminUiLanguage): void {
    if (item.id === 'rename') this.openDialog(lang);
    else this.confirmDelete.set(lang);
  }

  protected setActive(lang: AdminUiLanguage, active: boolean): void {
    this.toggling.set(lang.code);
    this.api.updateLanguage(lang.code, { active }).subscribe({
      next: (row) => {
        this.replaceLanguage(row);
        this.toggling.set(null);
      },
      error: () => {
        this.toggling.set(null);
        this.replaceLanguage({ ...lang });
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected openDialog(lang: AdminUiLanguage | null): void {
    this.dialogError.set(null);
    this.dialog.set(lang ? { code: lang.code, newCode: lang.code, name: lang.name } : { code: null, newCode: '', name: '' });
  }

  protected patchDialog(patch: Partial<LanguageDraft>): void {
    this.dialogError.set(null);
    this.dialog.update((d) => (d ? { ...d, ...patch } : d));
  }

  /** The error of the code field, or empty while it is fine or untouched. */
  protected readonly codeError = computed(() => {
    const d = this.dialog();
    if (!d || d.code !== null || !d.newCode) return '';
    if (!LANGUAGE_CODE.test(d.newCode)) return this.i18n.translate('admin.translations.codeInvalid');
    if (d.newCode === 'de' || d.newCode === 'en' || this.languages().some((l) => l.code === d.newCode)) {
      return this.i18n.translate('admin.translations.codeTaken');
    }
    return '';
  });

  protected readonly dialogValid = computed(() => {
    const d = this.dialog();
    if (!d || !d.name.trim()) return false;
    return d.code !== null || (!!d.newCode && !this.codeError());
  });

  protected submitDialog(): void {
    const d = this.dialog();
    if (!d || !this.dialogValid() || this.dialogBusy()) return;
    this.dialogBusy.set(true);
    const name = d.name.trim();
    const call =
      d.code === null
        ? this.api.createLanguage({ code: d.newCode, name })
        : this.api.updateLanguage(d.code, { name });
    call.subscribe({
      next: (row) => {
        if (d.code === null) {
          this.languages.update((list) => [...list, row].sort((a, b) => a.code.localeCompare(b.code)));
          this.stored.update((s) => ({ ...s, [row.code]: {} }));
          this.locale.set(row.code);
        } else {
          this.replaceLanguage(row);
        }
        this.dialogBusy.set(false);
        this.dialog.set(null);
      },
      error: (err: unknown) => {
        this.dialogBusy.set(false);
        const conflict = err instanceof HttpErrorResponse && err.status === 409;
        this.dialogError.set(conflict ? 'admin.translations.codeTaken' : 'admin.common.saveFailed');
      },
    });
  }

  protected deleteLanguage(): void {
    const lang = this.confirmDelete();
    if (!lang) return;
    this.confirmDelete.set(null);
    this.api.deleteLanguage(lang.code).subscribe({
      next: () => {
        this.languages.update((list) => list.filter((l) => l.code !== lang.code));
        this.draft.update((d) => Object.fromEntries(Object.entries(d).filter(([loc]) => loc !== lang.code)));
        if (this.locale() === lang.code) this.locale.set('de');
        this.toast.success(this.i18n.translate('admin.translations.deleted', { name: lang.name }));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  private replaceLanguage(row: AdminUiLanguage): void {
    this.languages.update((list) => list.map((l) => (l.code === row.code ? row : l)));
  }
}
