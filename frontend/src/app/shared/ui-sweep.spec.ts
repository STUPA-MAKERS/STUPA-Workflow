/**
 * App specs 000661 to 000677 of the UI/UX sweep, as far as the catalog and the styles carry
 * them: one name for a create action, one pattern for a search field, "Tickets" in
 * Verwaltung, and the title size of the login page. jsdom applies no styles, so the style
 * part reads the source.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { I18nService } from '@core/i18n/i18n.service';
import de from '@core/i18n/catalog/de.json';
import en from '@core/i18n/catalog/en.json';
import { searchPlaceholder } from './util/search-placeholder';

const DE = de as Record<string, string>;
const EN = en as Record<string, string>;
const APP = join(__dirname, '..');

describe('createFormNames (§000666)', () => {
  /** The floating button, then the title of the form or dialog that it opens. */
  it.each([
    ['fab.expense', 'expenses.add'],
    ['fab.invoice', 'invoices.add'],
    ['fab.todo', 'todos.new.title'],
    ['fab.meeting', 'meetings.create.title'],
    ['poll.new.fab', 'poll.new.title'],
  ])('%s and %s have one text', (button, title) => {
    expect(DE[title]).toBe(DE[button]);
    expect(EN[title]).toBe(EN[button]);
    expect(DE[button]).toMatch(/ anlegen$/);
  });

  it('keeps "hinzufügen" for an item that is added to another item', () => {
    const create = Object.entries(DE).filter(([key]) => key.startsWith('fab.'));
    expect(create.length).toBeGreaterThan(5);
    for (const [, text] of create) expect(text).not.toMatch(/hinzufügen/);
    expect(DE['todos.board.addCard']).toBe('To-Do anlegen');
  });
});

describe('searchPlaceholder (§000661)', () => {
  const i18n = {
    translate: (key: string, params?: Record<string, unknown>) =>
      (DE[key] ?? key).replace('{count}', String(params?.['count'] ?? '')),
  } as unknown as I18nService;

  it.each([
    ['Tickets', { plain: 'tickets.list.searchLabel', one: 'tickets.list.searchOne', many: 'tickets.list.search' }, 'Ticket'],
    ['Gremien', { plain: 'gremien.list.searchLabel', one: 'gremien.list.searchOne', many: 'gremien.list.search' }, 'Gremium'],
    ['Aufgaben', { plain: 'tasks.search', one: 'tasks.searchCountOne', many: 'tasks.searchCount' }, 'Aufgabe'],
    ['Buchungen', { plain: 'expenses.searchLabel', one: 'expenses.searchCountOne', many: 'expenses.searchCount' }, 'Buchung'],
    ['Rechnungen', { plain: 'invoices.searchLabel', one: 'invoices.searchCountOne', many: 'invoices.searchCount' }, 'Rechnung'],
    ['Abstimmungen', { plain: 'voting.list.search', one: 'voting.list.searchCountOne', many: 'voting.list.searchCount' }, 'Abstimmung'],
  ] as const)('%s: no item, one item and two items', (plural, keys, singular) => {
    const texts = keys as unknown as Parameters<typeof searchPlaceholder>[1];
    expect(searchPlaceholder(i18n, texts, 0, true)).toBe(`${plural} durchsuchen`);
    expect(searchPlaceholder(i18n, texts, 0)).toBe(`0 ${plural} durchsuchen`);
    expect(searchPlaceholder(i18n, texts, 1)).toBe(`1 ${singular} durchsuchen`);
    expect(searchPlaceholder(i18n, texts, 1, true)).toBe(`1 ${singular} durchsuchen`);
    expect(searchPlaceholder(i18n, texts, 2)).toBe(`2 ${plural} durchsuchen`);
  });

  it('no list search field uses "suchen …" or names its columns', () => {
    const fields = Object.entries(DE).filter(([key]) => /\.search(Count|CountOne|One|Placeholder)?$/.test(key));
    expect(fields.length).toBeGreaterThan(8);
    for (const [key, text] of fields) {
      if (/durchsuchen/.test(text)) expect(`${key}: ${text}`).not.toMatch(/…|\(/);
    }
  });
});

describe('ticketsInAdmin (§000676)', () => {
  it('the page "Hilfe & Tickets" says "Tickets", not "Meldungen"', () => {
    const texts = Object.entries(DE).filter(([key]) => key.startsWith('admin.helpTickets.'));
    expect(texts.length).toBeGreaterThan(5);
    for (const [key, text] of texts) expect(`${key}: ${text}`).not.toMatch(/Meldung/);
  });
});

describe('phoneDetailTabs (§000673)', () => {
  it('the ticket detail does not stretch its tabs, so they are packed at the start', () => {
    const css = readFileSync(join(APP, 'pages/tickets/ticket-detail.component.scss'), 'utf8');
    expect(css).not.toMatch(/\.td__tabs[^{]*\.tabs__tab/);
  });
});

describe('loginTitle (§000677)', () => {
  it('the title of the login page sets no size of its own, so it has the size of "Antrag stellen"', () => {
    const login = readFileSync(join(APP, 'pages/login/login.component.scss'), 'utf8');
    const apply = readFileSync(join(APP, 'features/apply/apply-wizard.component.scss'), 'utf8');
    const rule = (css: string, selector: string) =>
      new RegExp(`\\n${selector.replace('.', '\\.')} \\{([^}]*)\\}`).exec(css)?.[1] ?? '';
    expect(rule(login, '.lg__heading')).not.toMatch(/font-size|line-height/);
    expect(rule(apply, '.wz__title')).not.toMatch(/font-size|line-height/);
  });
});
