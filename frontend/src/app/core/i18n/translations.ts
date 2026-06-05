/** UI-String-Katalog. DE ist die Referenz; fehlende EN-Keys fallen auf DE zurück. */

export type Locale = 'de' | 'en';

export const SUPPORTED_LOCALES: readonly Locale[] = ['de', 'en'] as const;
export const DEFAULT_LOCALE: Locale = 'de';

export type TranslationKey = keyof typeof de;

export const de = {
  'app.title': 'StuPa Antragsplattform',
  'app.skipToContent': 'Zum Inhalt springen',

  'nav.dashboard': 'Dashboard',
  'nav.applications': 'Anträge',
  'nav.voting': 'Abstimmungen',
  'nav.meetings': 'Sitzungen',
  'nav.budget': 'Budget',
  'nav.admin': 'Verwaltung',
  'nav.apply': 'Antrag stellen',

  'action.login': 'Anmelden',
  'action.logout': 'Abmelden',
  'action.save': 'Speichern',
  'action.cancel': 'Abbrechen',
  'action.confirm': 'Bestätigen',
  'action.close': 'Schließen',

  'theme.toggle': 'Erscheinungsbild wechseln',
  'theme.light': 'Hell',
  'theme.dark': 'Dunkel',
  'theme.system': 'System',

  'lang.switch': 'Sprache wechseln',
  'lang.de': 'Deutsch',
  'lang.en': 'Englisch',

  'home.heading': 'Antragsplattform',
  'home.subtitle': 'Anträge, Abstimmungen, Sitzungsprotokolle und Budget — an einem Ort.',
  'home.cta': 'Jetzt Antrag stellen',

  'auth.signedInAs': 'Angemeldet als',
  'auth.account': 'Konto',
  'rbac.forbidden': 'Keine Berechtigung für diesen Bereich.',

  'dashboard.greeting': 'Willkommen, {name}',
  'dashboard.subtitle': 'Dein Überblick über offene Aufgaben, Anträge und Abstimmungen.',
  'dashboard.loading': 'Wird geladen …',
  'dashboard.viewAll': 'Alle ansehen',
  'dashboard.empty': 'Nichts offen.',
  'dashboard.tasks.title': 'Offene Aufgaben',
  'dashboard.applications.title': 'Meine Anträge',
  'dashboard.votes.title': 'Meine Abstimmungen',
  'dashboard.meetings.title': 'Sitzungen',
  'dashboard.budget.title': 'Budget',
  'dashboard.admin.title': 'Verwaltung',

  'notFound.heading': 'Seite nicht gefunden',
  'notFound.body': 'Die angeforderte Seite existiert nicht.',
  'notFound.back': 'Zur Startseite',

  'footer.coBranding': 'Eine Plattform des Studierendenparlaments',
  'footer.imprint': 'Impressum',
  'footer.privacy': 'Datenschutz',
} as const;

export const en: Partial<Record<TranslationKey, string>> = {
  'app.title': 'StuPa Application Platform',
  'app.skipToContent': 'Skip to content',

  'nav.dashboard': 'Dashboard',
  'nav.applications': 'Applications',
  'nav.voting': 'Votes',
  'nav.meetings': 'Meetings',
  'nav.budget': 'Budget',
  'nav.admin': 'Administration',
  'nav.apply': 'Submit application',

  'action.login': 'Sign in',
  'action.logout': 'Sign out',
  'action.save': 'Save',
  'action.cancel': 'Cancel',
  'action.confirm': 'Confirm',
  'action.close': 'Close',

  'theme.toggle': 'Toggle appearance',
  'theme.light': 'Light',
  'theme.dark': 'Dark',
  'theme.system': 'System',

  'lang.switch': 'Switch language',
  'lang.de': 'German',
  'lang.en': 'English',

  'home.heading': 'Application Platform',
  'home.subtitle': 'Applications, votes, meeting minutes and budget — in one place.',
  'home.cta': 'Submit an application',

  'auth.signedInAs': 'Signed in as',
  'auth.account': 'Account',
  'rbac.forbidden': 'You do not have access to this area.',

  'dashboard.greeting': 'Welcome, {name}',
  'dashboard.subtitle': 'Your overview of open tasks, applications and votes.',
  'dashboard.loading': 'Loading …',
  'dashboard.viewAll': 'View all',
  'dashboard.empty': 'Nothing pending.',
  'dashboard.tasks.title': 'Open tasks',
  'dashboard.applications.title': 'My applications',
  'dashboard.votes.title': 'My votes',
  'dashboard.meetings.title': 'Meetings',
  'dashboard.budget.title': 'Budget',
  'dashboard.admin.title': 'Administration',

  'notFound.heading': 'Page not found',
  'notFound.body': 'The requested page does not exist.',
  'notFound.back': 'Back to start',

  'footer.coBranding': 'A platform of the Student Parliament',
  'footer.imprint': 'Imprint',
  'footer.privacy': 'Privacy',
};

export const CATALOG: Record<Locale, Partial<Record<TranslationKey, string>>> = { de, en };
